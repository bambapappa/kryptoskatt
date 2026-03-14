"""Tests for middleware: API version header, security headers, CORS."""

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
    """Unauthenticated test client."""
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


def test_api_version_header(client):
    """GET /api/v1/health must include X-API-Version: 1 in response headers."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.headers.get("x-api-version") == "1"


def test_api_version_header_not_on_non_api(client):
    """Non-/api/ paths must not include X-API-Version header."""
    # /auth/login is an HTML route, not under /api/
    resp = client.get("/auth/login")
    assert "x-api-version" not in resp.headers


def test_security_headers_on_html(client):
    """HTML responses must include X-Content-Type-Options, X-Frame-Options and Referrer-Policy."""
    resp = client.get("/auth/login")
    # /auth/login renders an HTML template
    assert resp.status_code == 200
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_security_headers_absent_on_json(client):
    """JSON API responses must not receive HTML security headers."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    # JSON response — security headers should not be added
    assert resp.headers.get("x-frame-options") is None


def test_cors_allowed_origin(client):
    """Requests from an allowed origin must receive Access-Control-Allow-Origin header."""
    resp = client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_preflight(client):
    """OPTIONS preflight for allowed origin must return 200 with CORS headers."""
    resp = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers
