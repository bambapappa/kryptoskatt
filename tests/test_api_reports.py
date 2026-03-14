"""REST API tests for report endpoints."""

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
    from kryptoskatt.api.v1 import issues as issues_module
    from kryptoskatt.api.v1 import reports as reports_module
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
    app.dependency_overrides[reports_module._get_db] = override_get_db
    app.dependency_overrides[issues_module._get_db] = override_get_db
    app.dependency_overrides[web_auth_module._get_db_session] = override_get_db

    with TestClient(app, cookies={"kryptoskatt_session": token}) as c:
        yield c

    app.dependency_overrides.clear()


# ── Tests ───────────────────────────────────────────────────────────────────


def test_k4_report_empty(client):
    """GET /api/v1/reports/k4/2024 returns 200 with a 'rows' key."""
    resp = client.get("/api/v1/reports/k4/2024")
    assert resp.status_code == 200
    data = resp.json()
    assert "rows" in data
    assert isinstance(data["rows"], list)


def test_k4_report_contains_year(client):
    """Response body includes the requested year."""
    resp = client.get("/api/v1/reports/k4/2024")
    assert resp.status_code == 200
    assert resp.json()["year"] == 2024


def test_k4_csv_download(client):
    """GET /api/v1/reports/k4/2024/csv returns 200 with text/csv content-type."""
    resp = client.get("/api/v1/reports/k4/2024/csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")


def test_issues_empty(client):
    """GET /api/v1/issues returns 200 with the expected structure."""
    resp = client.get("/api/v1/issues")
    assert resp.status_code == 200
    data = resp.json()
    assert "flagged_disposals" in data
    assert "flagged_transactions" in data
    assert isinstance(data["flagged_disposals"], list)
    assert isinstance(data["flagged_transactions"], list)


def test_gav_history_empty(client):
    """GET /api/v1/reports/gav-history?coin=BTC returns 200 with 'snapshots'."""
    resp = client.get("/api/v1/reports/gav-history", params={"coin": "BTC"})
    assert resp.status_code == 200
    data = resp.json()
    assert "snapshots" in data
    assert isinstance(data["snapshots"], list)


def test_net_position_empty(client):
    """GET /api/v1/reports/net-position/2024 returns 200 with 'rows'."""
    resp = client.get("/api/v1/reports/net-position/2024")
    assert resp.status_code == 200
    data = resp.json()
    assert "rows" in data
    assert isinstance(data["rows"], list)
