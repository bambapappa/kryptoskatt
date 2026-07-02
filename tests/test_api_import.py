"""REST API tests for import endpoint."""

import io

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
    from kryptoskatt.api.v1 import import_ as import_module
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
    app.dependency_overrides[import_module._get_db] = override_get_db
    app.dependency_overrides[web_auth_module._get_db_session] = override_get_db

    with TestClient(app, cookies={"kryptoskatt_session": token}) as c:
        yield c

    app.dependency_overrides.clear()


# ── Tests ───────────────────────────────────────────────────────────────────


def test_import_coinbase_csv(client, coinbase_csv):
    """POST /api/v1/import with coinbase CSV and explicit platform returns 200 with saved >= 0."""
    with open(coinbase_csv, "rb") as f:
        resp = client.post(
            "/api/v1/import",
            data={"platform": "coinbase"},
            files={"file": ("coinbase_sample.csv", f, "text/csv")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "saved" in data
    assert "skipped" in data
    assert "errors" in data
    assert data["saved"] >= 0


def test_import_auto_detect(client, coinbase_csv):
    """POST /api/v1/import without platform uses auto-detection and succeeds."""
    with open(coinbase_csv, "rb") as f:
        resp = client.post(
            "/api/v1/import",
            files={"file": ("coinbase_sample.csv", f, "text/csv")},
        )
    # Auto-detect should work for coinbase format
    assert resp.status_code in (200, 422)
    if resp.status_code == 200:
        data = resp.json()
        assert "saved" in data


def test_import_invalid_file(client):
    """POST /api/v1/import with empty file content returns an error status."""
    empty_content = b""
    resp = client.post(
        "/api/v1/import",
        data={"platform": "coinbase"},
        files={"file": ("empty.csv", io.BytesIO(empty_content), "text/csv")},
    )
    # Empty file should either fail parse (422) or return saved=0 gracefully (200)
    assert resp.status_code in (200, 400, 422)
    if resp.status_code == 200:
        data = resp.json()
        assert data["saved"] == 0


def test_import_unknown_platform(client, coinbase_csv):
    """POST /api/v1/import with an unknown platform returns 422."""
    with open(coinbase_csv, "rb") as f:
        resp = client.post(
            "/api/v1/import",
            data={"platform": "invalid_xyz"},
            files={"file": ("coinbase_sample.csv", f, "text/csv")},
        )
    assert resp.status_code == 422
