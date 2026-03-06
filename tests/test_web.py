"""Tests for KryptoSkatt web application."""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models.base import Base
from kryptoskatt.models.disposal import Disposal
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
    # Create all tables
    Base.metadata.create_all(engine)

    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        # Drop all tables after test
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create test client with overridden database dependency."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    # Clear dependency overrides
    app.dependency_overrides.clear()


@pytest.fixture
def sample_disposals(db_session):
    """Create sample disposal records for testing."""
    disposals = [
        Disposal(
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("150000.00"),
            cost_basis_sek=Decimal("100000.00"),
            gain_loss_sek=Decimal("50000.00"),
            gav_at_disposal=Decimal("200000.00"),
        ),
        Disposal(
            tax_year=2024,
            coin="ETH",
            sell_timestamp=datetime(2024, 7, 20, 14, 0, 0, tzinfo=timezone.utc),
            sell_amount=Decimal("-2.0"),
            proceeds_sek=Decimal("40000.00"),
            cost_basis_sek=Decimal("35000.00"),
            gain_loss_sek=Decimal("5000.00"),
            gav_at_disposal=Decimal("17500.00"),
        ),
        Disposal(
            tax_year=2023,
            coin="BTC",
            sell_timestamp=datetime(2023, 5, 10, 12, 0, 0, tzinfo=timezone.utc),
            sell_amount=Decimal("-0.25"),
            proceeds_sek=Decimal("50000.00"),
            cost_basis_sek=Decimal("60000.00"),
            gain_loss_sek=Decimal("-10000.00"),
            gav_at_disposal=Decimal("240000.00"),
        ),
    ]

    for d in disposals:
        db_session.add(d)
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
        assert "Inga transaktioner hittades" in response.text


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
        assert "Vinst/Förlust SEK" in response.text

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
        assert "Inga försäljningar registrerade" in response.text


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
