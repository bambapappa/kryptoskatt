"""REST API tests for T2 entries and T2 report endpoints."""

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
    from kryptoskatt.api.v1 import reports as reports_module
    from kryptoskatt.api.v1 import t2_entries as t2_entries_module
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
    app.dependency_overrides[reports_module._get_db] = override_get_db
    app.dependency_overrides[t2_entries_module._get_db] = override_get_db
    app.dependency_overrides[web_auth_module._get_db_session] = override_get_db

    with TestClient(app, cookies={"kryptoskatt_session": token}) as c:
        yield c

    app.dependency_overrides.clear()


# ── T2 entries tests ─────────────────────────────────────────────────────────


def test_list_t2_entries_empty(client):
    """GET /api/v1/t2-entries with no entries returns empty list."""
    resp = client.get("/api/v1/t2-entries")
    assert resp.status_code == 200
    data = resp.json()
    assert "entries" in data
    assert data["entries"] == []


def test_list_t2_entries_filtered_by_year(client):
    """GET /api/v1/t2-entries?year=2024 returns only entries for that year."""
    resp = client.get("/api/v1/t2-entries", params={"year": 2024})
    assert resp.status_code == 200
    assert resp.json()["entries"] == []


def test_create_t2_entry(client):
    """POST /api/v1/t2-entries creates an entry and returns 201 with entry_id."""
    payload = {
        "year": 2024,
        "description": "Inköp ASIC miner",
        "amount_sek": "15000.00",
        "vendor": "Inet",
        "entry_date": "2024-03-15",
    }
    resp = client.post("/api/v1/t2-entries", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["description"] == "Inköp ASIC miner"
    assert data["year"] == 2024
    assert data["amount_sek"] == "15000.00"
    assert data["vendor"] == "Inet"
    assert data["entry_date"] == "2024-03-15"


def test_create_t2_entry_appears_in_list(client):
    """After creating an entry it should appear when listing."""
    client.post("/api/v1/t2-entries", json={
        "year": 2024,
        "description": "Elkostnad Q1",
        "amount_sek": "2500.00",
    })
    resp = client.get("/api/v1/t2-entries", params={"year": 2024})
    assert resp.status_code == 200
    descriptions = [e["description"] for e in resp.json()["entries"]]
    assert "Elkostnad Q1" in descriptions


def test_delete_t2_entry(client):
    """Create then delete an entry — should return 200 and the entry should be gone."""
    create_resp = client.post("/api/v1/t2-entries", json={
        "year": 2024,
        "description": "Radera mig",
        "amount_sek": "999.00",
    })
    assert create_resp.status_code == 201
    entry_id = create_resp.json()["id"]

    del_resp = client.delete(f"/api/v1/t2-entries/{entry_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True

    list_resp = client.get("/api/v1/t2-entries")
    ids = [e["id"] for e in list_resp.json()["entries"]]
    assert entry_id not in ids


def test_delete_nonexistent_t2_entry(client):
    """Deleting an entry that does not exist returns 404."""
    resp = client.delete("/api/v1/t2-entries/999999")
    assert resp.status_code == 404


def test_create_t2_entry_invalid_amount(client):
    """POST with non-positive amount_sek should return 422."""
    resp = client.post("/api/v1/t2-entries", json={
        "year": 2024,
        "description": "Negativt belopp",
        "amount_sek": "-100.00",
    })
    assert resp.status_code == 422


def test_create_t2_entry_empty_description(client):
    """POST with empty description should return 422."""
    resp = client.post("/api/v1/t2-entries", json={
        "year": 2024,
        "description": "   ",
        "amount_sek": "500.00",
    })
    assert resp.status_code == 422


# ── T2 report tests ──────────────────────────────────────────────────────────


def test_t2_report_empty(client):
    """GET /api/v1/reports/t2/2024 returns 200 with correct structure."""
    resp = client.get("/api/v1/reports/t2/2024")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tax_year"] == 2024
    assert "income_rows" in data
    assert "cost_rows" in data
    assert "manual_cost_rows" in data
    assert isinstance(data["income_rows"], list)
    assert isinstance(data["cost_rows"], list)
    assert isinstance(data["manual_cost_rows"], list)


def test_t2_report_includes_manual_entry(client):
    """A created manual entry should appear in the T2 report."""
    client.post("/api/v1/t2-entries", json={
        "year": 2024,
        "description": "Server rack",
        "amount_sek": "4200.00",
        "vendor": "Dustin",
    })
    resp = client.get("/api/v1/reports/t2/2024")
    assert resp.status_code == 200
    data = resp.json()
    manual = data["manual_cost_rows"]
    assert len(manual) == 1
    assert manual[0]["description"] == "Server rack"
    assert manual[0]["amount_sek"] == "4200.00"
