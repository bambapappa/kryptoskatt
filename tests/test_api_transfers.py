"""REST API tests for transfer link endpoints."""

from datetime import UTC, datetime
from decimal import Decimal

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
    from kryptoskatt.api.v1 import transfers as transfers_module
    from kryptoskatt.models.account import Account
    from kryptoskatt.services.auth import AuthService
    from kryptoskatt.web import auth as web_auth_module
    from kryptoskatt.web.app import get_db

    account = db_session.query(Account).filter(Account.account_id == "legacy-single-user-0000").first()
    _, token = AuthService(db_session).create_session(account)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[transfers_module._get_db] = override_get_db
    app.dependency_overrides[web_auth_module._get_db_session] = override_get_db

    with TestClient(app, cookies={"kryptoskatt_session": token}) as c:
        yield c

    app.dependency_overrides.clear()


def _make_tx(db_session, user_id: int, event_type: str, tx_hash: str | None = None):
    """Create a minimal Transaction row and return its id."""
    from kryptoskatt.models.transaction import Transaction

    tx = Transaction(
        user_id=user_id,
        source_platform="test",
        timestamp_utc=datetime(2024, 6, 1, 12, 0, tzinfo=UTC),
        event_type=event_type,
        base_coin="ETH",
        base_amount=Decimal("1.0"),
        tx_hash=tx_hash,
        is_duplicate=False,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return tx.id


# ── Tests ───────────────────────────────────────────────────────────────────


def test_list_transfers_empty(client):
    """GET /api/v1/transfers returns empty list when no links exist."""
    resp = client.get("/api/v1/transfers")
    assert resp.status_code == 200
    assert resp.json() == {"links": []}


def test_create_manual_transfer(client, db_session):
    """POST /api/v1/transfers/manual creates a link and returns 201."""
    from kryptoskatt.models.account import Account

    account = db_session.query(Account).filter(Account.account_id == "legacy-single-user-0000").first()
    tx_out_id = _make_tx(db_session, account.id, "TRANSFER_OUT", tx_hash="0xabc")
    tx_in_id = _make_tx(db_session, account.id, "TRANSFER_IN", tx_hash="0xdef")

    resp = client.post("/api/v1/transfers/manual", json={"tx_out_id": tx_out_id, "tx_in_id": tx_in_id})
    assert resp.status_code == 201
    data = resp.json()
    assert data["tx_out_id"] == tx_out_id
    assert data["tx_in_id"] == tx_in_id
    assert data["match_method"] == "manual"
    assert data["is_manual"] is True
    assert "id" in data


def test_delete_transfer(client, db_session):
    """DELETE /api/v1/transfers/{id} removes the link and returns 200."""
    from kryptoskatt.models.account import Account
    from kryptoskatt.models.transfer_link import TransferLink

    account = db_session.query(Account).filter(Account.account_id == "legacy-single-user-0000").first()
    tx_out_id = _make_tx(db_session, account.id, "TRANSFER_OUT")
    tx_in_id = _make_tx(db_session, account.id, "TRANSFER_IN")

    link = TransferLink(tx_out_id=tx_out_id, tx_in_id=tx_in_id, match_method="manual")
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)
    link_id = link.id

    resp = client.delete(f"/api/v1/transfers/{link_id}")
    assert resp.status_code == 204

    # Verify deleted
    remaining = db_session.query(TransferLink).filter(TransferLink.id == link_id).first()
    assert remaining is None


def test_delete_nonexistent_transfer(client):
    """DELETE /api/v1/transfers/999 returns 404."""
    resp = client.delete("/api/v1/transfers/999")
    assert resp.status_code == 404
