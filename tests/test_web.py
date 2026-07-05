"""Tests for KryptoSkatt web application."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models.base import Base
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.web.app import app, get_db

# Create in-memory SQLite database with shared connection
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    from tests.conftest import make_test_account

    # Create all tables
    Base.metadata.create_all(engine)

    session = TestingSession()
    make_test_account(session)
    try:
        yield session
    finally:
        session.close()
        # Drop all tables after test
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create test client with overridden database and auth dependencies."""
    from kryptoskatt.models.account import Account
    from kryptoskatt.web.auth import get_optional_account

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    # Return the legacy test account so auth guards pass
    def override_get_optional_account():
        return db_session.query(Account).filter(Account.account_id == "legacy-single-user-0000").first()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_optional_account] = override_get_optional_account

    with TestClient(app) as test_client:
        yield test_client

    # Clear dependency overrides
    app.dependency_overrides.clear()


@pytest.fixture
def sample_disposals(db_session):
    """Create sample disposal records for testing."""
    disposals = [
        Disposal(
            user_id=1,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("150000.00"),
            cost_basis_sek=Decimal("100000.00"),
            gain_loss_sek=Decimal("50000.00"),
            gav_at_disposal=Decimal("200000.00"),
        ),
        Disposal(
            user_id=1,
            tax_year=2024,
            coin="ETH",
            sell_timestamp=datetime(2024, 7, 20, 14, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-2.0"),
            proceeds_sek=Decimal("40000.00"),
            cost_basis_sek=Decimal("35000.00"),
            gain_loss_sek=Decimal("5000.00"),
            gav_at_disposal=Decimal("17500.00"),
        ),
        Disposal(
            user_id=1,
            tax_year=2023,
            coin="BTC",
            sell_timestamp=datetime(2023, 5, 10, 12, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.25"),
            proceeds_sek=Decimal("50000.00"),
            cost_basis_sek=Decimal("60000.00"),
            gain_loss_sek=Decimal("-10000.00"),
            gav_at_disposal=Decimal("240000.00"),
        ),
    ]

    for d in disposals:
        db_session.add(d)

    # Add matching Transaction rows so the /year/{year}/transactions page has data
    transactions = [
        Transaction(
            user_id=1,
            source_platform="test",
            timestamp_utc=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            event_type="SELL",
            base_coin="BTC",
            base_amount=Decimal("-0.5"),
            is_duplicate=False,
        ),
        Transaction(
            user_id=1,
            source_platform="test",
            timestamp_utc=datetime(2024, 7, 20, 14, 0, 0, tzinfo=UTC),
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-2.0"),
            is_duplicate=False,
        ),
    ]
    for tx in transactions:
        db_session.add(tx)

    db_session.commit()

    return disposals


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_returns_ok(self, client):
        """GET /health should return 200 OK with status ok."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestDashboardEndpoint:
    """Tests for dashboard endpoint."""

    def test_dashboard_returns_200(self, client):
        """GET / should return 200 OK."""
        response = client.get("/")

        assert response.status_code == 200

    def test_dashboard_shows_years(self, client, sample_disposals):
        """GET / should show available tax years."""
        response = client.get("/")

        assert response.status_code == 200
        assert "2024" in response.text
        assert "2023" in response.text

    def test_dashboard_empty_when_no_data(self, client):
        """GET / should show empty state when no disposals."""
        response = client.get("/")

        assert response.status_code == 200
        assert "Inga beräknade avyttringar hittades" in response.text


class TestYearSummaryEndpoint:
    """Tests for year summary endpoint."""

    def test_year_summary_returns_200(self, client, sample_disposals):
        """GET /year/2024 should return 200 OK."""
        response = client.get("/year/2024")

        assert response.status_code == 200

    def test_year_summary_shows_k4_table(self, client, sample_disposals):
        """GET /year/2024 should show K4 summary table with Swedish headers."""
        response = client.get("/year/2024")

        assert response.status_code == 200
        assert "Tillgång" in response.text
        assert "Försäljningspris SEK" in response.text
        assert "Omkostnadsbelopp SEK" in response.text
        assert "Vinst" in response.text and "Förlust" in response.text

    def test_year_summary_shows_coin_data(self, client, sample_disposals):
        """GET /year/2024 should show BTC and ETH data."""
        response = client.get("/year/2024")

        assert response.status_code == 200
        assert "BTC" in response.text
        assert "ETH" in response.text

    def test_year_summary_404_for_invalid_year(self, client, sample_disposals):
        """GET /year/9999 should return 200 (empty result, not 404)."""
        response = client.get("/year/9999")

        # Returns empty result, not 404
        assert response.status_code == 200
        assert "Inga försäljningar med känt pris" in response.text


class TestApiKeysSettings:
    """Tests for the per-account API keys section on the settings page."""

    def test_settings_page_shows_api_keys(self, client):
        response = client.get("/settings")
        assert response.status_code == 200
        assert "Egna API-nycklar" in response.text
        assert "Etherscan" in response.text

    def test_save_and_clear_api_key(self, client, db_session):
        from kryptoskatt.services.api_keys import get_account_api_keys

        acct = db_session.query(
            __import__("kryptoskatt.models.account", fromlist=["Account"]).Account
        ).filter_by(account_id="legacy-single-user-0000").first()

        r = client.post(
            "/settings/api-keys/save",
            data={"provider": "etherscan", "api_key": "SECRET123"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert get_account_api_keys(db_session, acct.id) == {"etherscan": "SECRET123"}

        # Empty value clears it
        client.post(
            "/settings/api-keys/save",
            data={"provider": "etherscan", "api_key": ""},
            follow_redirects=False,
        )
        assert get_account_api_keys(db_session, acct.id) == {}


class TestCarryoverEndpoint:
    """Tests for the year-to-year GAV carryover page."""

    def test_carryover_page_returns_200(self, client, sample_disposals):
        response = client.get("/year/2024/carryover")
        assert response.status_code == 200
        assert "GAV-överföring" in response.text

    def test_carryover_download_is_csv(self, client, sample_disposals):
        response = client.get("/year/2024/download/carryover")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "Ingående omkostnad SEK" in response.text


class TestTransactionsEndpoint:
    """Tests for transactions endpoint."""

    def test_transactions_returns_200(self, client, sample_disposals):
        """GET /year/2024/transactions should return 200 OK."""
        response = client.get("/year/2024/transactions")

        assert response.status_code == 200

    def test_transactions_shows_data(self, client, sample_disposals):
        """GET /year/2024/transactions should show transaction list."""
        response = client.get("/year/2024/transactions")

        assert response.status_code == 200
        assert "BTC" in response.text
        assert "ETH" in response.text

    def test_transactions_pagination(self, client, sample_disposals):
        """GET /year/2024/transactions should support pagination."""
        response = client.get("/year/2024/transactions?page=1")

        assert response.status_code == 200
        # Should show 2 items per page (we have 2 for 2024)
        assert "0.5" in response.text  # BTC amount
        assert "2.0" in response.text  # ETH amount

    def test_transactions_empty_for_year(self, client, sample_disposals):
        """GET /year/2025/transactions should show empty state."""
        response = client.get("/year/2025/transactions")

        assert response.status_code == 200
        assert "Inga transaktioner registrerade" in response.text


class TestDownloadEndpoints:
    """Tests for download endpoints."""

    def test_download_csv_returns_csv(self, client, sample_disposals):
        """GET /year/2024/download/csv should return CSV content."""
        response = client.get("/year/2024/download/csv")

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "k4_2024.csv" in response.headers["content-disposition"]

        # Check CSV content
        content = response.text
        assert "Tillgång" in content
        assert "BTC" in content
        assert "ETH" in content

    def test_download_json_returns_json(self, client, sample_disposals):
        """GET /year/2024/download/json should return JSON content."""
        response = client.get("/year/2024/download/json")

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]
        assert "k4_2024.json" in response.headers["content-disposition"]

        # Check JSON content
        data = response.json()
        assert data["tax_year"] == 2024
        assert len(data["rows"]) == 2


class TestPlaceholderEndpoints:
    """Tests for placeholder endpoints."""

    def test_gav_history_returns_200(self, client):
        """GET /year/2024/gav/BTC should return 200 OK."""
        response = client.get("/year/2024/gav/BTC")

        assert response.status_code == 200
        assert "GAV-historik" in response.text

    def test_issues_returns_200(self, client):
        """GET /year/2024/issues should return 200 OK."""
        response = client.get("/year/2024/issues")

        assert response.status_code == 200
        assert "Flaggade problem" in response.text
