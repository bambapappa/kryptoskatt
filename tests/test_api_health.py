"""Tests for GET /api/v1/health and GET /api/v1/info."""

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
def client(db_engine):
    """Unauthenticated test client — health/info need no auth."""
    from kryptoskatt.web import auth as web_auth_module
    from kryptoskatt.web.app import get_db

    Session = sessionmaker(bind=db_engine)
    session = Session()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[web_auth_module._get_db_session] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    session.close()


def test_health_returns_ok(client):
    """GET /api/v1/health returns 200 with status == 'ok'."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_health_no_auth_required(client):
    """Health endpoint must not require authentication."""
    # No cookie, no token — still succeeds
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_info_returns_chains(client):
    """GET /api/v1/info returns supported_chains as a non-empty list."""
    resp = client.get("/api/v1/info")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["supported_chains"], list)
    assert len(data["supported_chains"]) > 0


def test_info_has_version(client):
    """GET /api/v1/info returns version string."""
    from kryptoskatt import __version__

    resp = client.get("/api/v1/info")
    assert resp.status_code == 200
    assert resp.json()["version"] == __version__


def test_info_has_adapter_types(client):
    """GET /api/v1/info returns adapter_types list."""
    resp = client.get("/api/v1/info")
    assert resp.status_code == 200
    assert "adapter_types" in resp.json()
    assert isinstance(resp.json()["adapter_types"], list)
