"""REST API tests for auth endpoints."""

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
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _make_db_override(db_session):
    def override():
        try:
            yield db_session
        finally:
            pass
    return override


@pytest.fixture
def client(db_session):
    """Unauthenticated test client with overridden DB."""
    from kryptoskatt.api.v1 import auth as auth_module
    from kryptoskatt.api.v1 import wallets as wallets_module
    from kryptoskatt.web import auth as web_auth_module
    from kryptoskatt.web.app import get_db

    override = _make_db_override(db_session)

    app.dependency_overrides[get_db] = override
    app.dependency_overrides[auth_module._get_db] = override
    app.dependency_overrides[wallets_module._get_db] = override
    app.dependency_overrides[web_auth_module._get_db_session] = override

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ── Helper ───────────────────────────────────────────────────────────────────


def _create_account(client: TestClient) -> tuple[str, str]:
    """Create a new account and return (account_id, session_cookie_value)."""
    resp = client.post("/api/v1/auth/account")
    assert resp.status_code == 201
    account_id = resp.json()["account_id"]
    cookie = resp.cookies.get("kryptoskatt_session")
    assert cookie, "Expected session cookie after account creation"
    return account_id, cookie


# ── Tests ────────────────────────────────────────────────────────────────────


def test_create_account(client):
    """POST /api/v1/auth/account creates account and sets cookie."""
    resp = client.post("/api/v1/auth/account")
    assert resp.status_code == 201
    data = resp.json()
    assert "account_id" in data
    # Format: word-word-word-NNNN
    parts = data["account_id"].split("-")
    assert len(parts) == 4
    assert parts[-1].isdigit()
    assert "kryptoskatt_session" in resp.cookies


def test_login_valid(client):
    """POST /api/v1/auth/session with a valid account_id returns {ok: true}."""
    account_id, _ = _create_account(client)

    resp = client.post("/api/v1/auth/session", json={"account_id": account_id})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "kryptoskatt_session" in resp.cookies


def test_login_invalid(client):
    """POST /api/v1/auth/session with a bad account_id returns 401."""
    resp = client.post("/api/v1/auth/session", json={"account_id": "bad-account-id-0000"})
    assert resp.status_code == 401


def test_logout(client):
    """DELETE /api/v1/auth/session clears the session."""
    account_id, cookie = _create_account(client)
    # Set cookie on client so subsequent requests are authenticated
    client.cookies.set("kryptoskatt_session", cookie)

    resp = client.delete("/api/v1/auth/session")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    client.cookies.clear()


def test_get_me(client):
    """GET /api/v1/auth/me returns masked account_id."""
    account_id, cookie = _create_account(client)
    client.cookies.set("kryptoskatt_session", cookie)

    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert "account_id_masked" in data
    assert data["account_id_masked"].endswith("****")

    client.cookies.clear()


def test_protected_route_without_cookie(client):
    """GET /api/v1/wallets without a session cookie returns 401."""
    resp = client.get("/api/v1/wallets")
    assert resp.status_code == 401
