"""REST API tests for wallet endpoints."""

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
    from kryptoskatt.api.v1 import wallets as wallets_module
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
    app.dependency_overrides[wallets_module._get_db] = override_get_db
    app.dependency_overrides[web_auth_module._get_db_session] = override_get_db

    with TestClient(app, cookies={"kryptoskatt_session": token}) as c:
        yield c

    app.dependency_overrides.clear()


# ── Tests ───────────────────────────────────────────────────────────────────


def test_list_wallets_empty(client):
    """GET /api/v1/wallets with no wallets returns empty list."""
    resp = client.get("/api/v1/wallets")
    assert resp.status_code == 200
    assert resp.json() == {"wallets": []}


def test_add_wallet_success(client):
    """POST /api/v1/wallets creates a wallet and returns 201."""
    payload = {
        "address": "0xDeAdBeEf000000000000000000000000DeAdBeEf",
        "chain": "ETHEREUM",
        "label": "Test wallet",
        "is_mine": True,
    }
    resp = client.post("/api/v1/wallets", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["address"] == payload["address"]
    assert data["chain"] == "ETHEREUM"
    assert data["label"] == "Test wallet"
    assert data["is_mine"] is True
    assert "id" in data


def test_add_wallet_duplicate_raises_400(client):
    """Posting the same address+chain twice returns 400."""
    payload = {
        "address": "0xD00000000000000000000000000000000000CAFE",
        "chain": "ETHEREUM",
        "label": "First",
        "is_mine": True,
    }
    r1 = client.post("/api/v1/wallets", json=payload)
    assert r1.status_code == 201

    r2 = client.post("/api/v1/wallets", json=payload)
    assert r2.status_code == 400


def test_add_unknown_chain_accepted(client):
    """An unrecognised chain value is stored; validation is deferred to fetch time."""
    payload = {
        "address": "unknown-chain-addr-1",
        "chain": "MYUNKNOWNCHAIN",
        "label": "Unknown Chain",
        "is_mine": True,
    }
    resp = client.post("/api/v1/wallets", json=payload)
    assert resp.status_code == 201
    assert resp.json()["chain"] == "MYUNKNOWNCHAIN"


def test_delete_wallet(client):
    """Adding then deleting a wallet returns 200."""
    add_resp = client.post(
        "/api/v1/wallets",
        json={
            "address": "0xDe1e7e0000000000000000000000000000000001",
            "chain": "ETHEREUM",
            "label": "Delete me",
            "is_mine": True,
        },
    )
    assert add_resp.status_code == 201
    wallet_id = add_resp.json()["id"]

    del_resp = client.delete(f"/api/v1/wallets/{wallet_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True

    # Verify it's gone
    list_resp = client.get("/api/v1/wallets")
    ids = [w["id"] for w in list_resp.json()["wallets"]]
    assert wallet_id not in ids


def test_unsupported_wallets(client):
    """Wallet with unknown chain appears in /wallets/unsupported."""
    client.post(
        "/api/v1/wallets",
        json={
            "address": "unsupported-addr-1",
            "chain": "FUTURECHAIN",
            "label": "Unsupported",
            "is_mine": True,
        },
    )
    resp = client.get("/api/v1/wallets/unsupported")
    assert resp.status_code == 200
    chains = [w["chain"] for w in resp.json()["wallets"]]
    assert "FUTURECHAIN" in chains
