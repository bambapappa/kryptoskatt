"""Tests for account export and deletion endpoints."""

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
    from kryptoskatt.api.v1 import account as account_module
    from kryptoskatt.models.account import Account
    from kryptoskatt.services.auth import AuthService
    from kryptoskatt.web import auth as web_auth_module
    from kryptoskatt.web.app import get_db

    account = db_session.query(Account).filter(
        Account.account_id == "legacy-single-user-0000"
    ).first()
    _, token = AuthService(db_session).create_session(account)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[account_module._get_db] = override_get_db
    app.dependency_overrides[web_auth_module._get_db_session] = override_get_db

    with TestClient(app, cookies={"kryptoskatt_session": token}) as c:
        yield c

    app.dependency_overrides.clear()


def test_export_returns_json(client):
    """GET /api/v1/account/export returns JSON with account data."""
    resp = client.get("/api/v1/account/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "content-disposition" in resp.headers
    data = resp.json()
    assert "account_id" in data
    assert "wallets" in data
    assert "transactions" in data
    assert "disposals" in data
    assert "exported_at" in data


def test_export_unauthenticated(db_session):
    """GET /api/v1/account/export without cookie returns 401."""
    from kryptoskatt.web.app import get_db

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/api/v1/account/export")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_delete_account_wrong_confirm(client):
    """DELETE /api/v1/account with wrong confirm string returns 400."""
    resp = client.request("DELETE", "/api/v1/account", json={"confirm": "yes please"})
    assert resp.status_code == 400


def test_delete_account_success(client, db_session):
    """DELETE /api/v1/account with correct confirm string removes account."""
    from kryptoskatt.models.account import Account

    resp = client.request("DELETE", "/api/v1/account", json={"confirm": "DELETE MY ACCOUNT"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Account is gone from DB
    remaining = db_session.query(Account).filter(
        Account.account_id == "legacy-single-user-0000"
    ).first()
    assert remaining is None
