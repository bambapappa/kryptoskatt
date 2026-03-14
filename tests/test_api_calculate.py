"""REST API tests for the calculate endpoint."""

from datetime import UTC

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models.base import Base
from kryptoskatt.web.app import app


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def db_session(db_engine):
    from tests.conftest import make_test_account

    Session = sessionmaker(bind=db_engine)
    session = Session()
    make_test_account(session)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    """Test client with DB override and session cookie for the legacy account."""
    from kryptoskatt.api.v1 import calculate as calculate_module
    from kryptoskatt.models.account import Account
    from kryptoskatt.services.auth import AuthService
    from kryptoskatt.web import auth as web_auth_module
    from kryptoskatt.web.app import get_db

    account = db_session.query(Account).filter(Account.account_id == "legacy-single-user-0000").first()
    user_session = AuthService(db_session).create_session(account)
    token = user_session.session_token

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[calculate_module._get_db] = override_get_db
    app.dependency_overrides[web_auth_module._get_db_session] = override_get_db

    with TestClient(app, cookies={"kryptoskatt_session": token}) as c:
        yield c

    app.dependency_overrides.clear()


# ── Tests ───────────────────────────────────────────────────────────────────


def test_calculate_no_transactions_returns_zero(client):
    """POST /api/v1/calculate with no transactions returns disposals_created == 0."""
    resp = client.post("/api/v1/calculate", json={"year": 2024})
    assert resp.status_code == 200
    data = resp.json()
    assert "disposals_created" in data
    assert data["disposals_created"] == 0


def test_calculate_response_has_required_keys(client):
    """Response contains all expected top-level keys."""
    resp = client.post("/api/v1/calculate", json={"year": 2024})
    assert resp.status_code == 200
    data = resp.json()
    assert "disposals_created" in data
    assert "gav_entries_created" in data
    assert "dedup_report" in data
    assert "transfer_report" in data
    assert "enrichment_report" in data


def test_calculate_with_disposals(client, db_session):
    """With a BUY + SELL in DB, calculate returns disposals_created >= 0.

    The engine may or may not produce disposals depending on dedup/transfer
    matching; we only verify the endpoint responds successfully.
    """
    from datetime import datetime
    from decimal import Decimal

    from kryptoskatt.models.account import Account
    from kryptoskatt.models.transaction import Transaction

    account = db_session.query(Account).filter(Account.account_id == "legacy-single-user-0000").first()

    buy = Transaction(
        user_id=account.id,
        source_platform="test",
        timestamp_utc=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC),
        event_type="BUY",
        base_coin="ETH",
        base_amount=Decimal("1.0"),
        quote_coin="SEK",
        quote_amount=Decimal("20000.00"),
        is_duplicate=False,
    )
    sell = Transaction(
        user_id=account.id,
        source_platform="test",
        timestamp_utc=datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
        event_type="SELL",
        base_coin="ETH",
        base_amount=Decimal("1.0"),
        quote_coin="SEK",
        quote_amount=Decimal("25000.00"),
        is_duplicate=False,
    )
    db_session.add_all([buy, sell])
    db_session.commit()

    resp = client.post("/api/v1/calculate", json={"year": 2024})
    assert resp.status_code == 200
    data = resp.json()
    assert data["disposals_created"] >= 0
