"""Tests for the web i18n layer (language cookie, translation, fallback)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models.base import Base
from kryptoskatt.services.auth import AuthService
from kryptoskatt.web.i18n import set_language, translate


class TestTranslate:
    def test_swedish_is_identity(self):
        set_language("sv")
        assert translate("Plånböcker") == "Plånböcker"

    def test_english_translation(self):
        set_language("en")
        try:
            assert translate("Plånböcker") == "Wallets"
            assert translate("Åtgärder") == "Actions"
        finally:
            set_language("sv")

    def test_missing_key_falls_back_to_source(self):
        set_language("en")
        try:
            assert translate("Helt oöversatt sträng") == "Helt oöversatt sträng"
        finally:
            set_language("sv")


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    acc, token = AuthService(db).create_account()

    from kryptoskatt.db import get_db
    from kryptoskatt.web import auth as web_auth
    from kryptoskatt.web.app import app

    def ov():
        yield db

    app.dependency_overrides[get_db] = ov
    app.dependency_overrides[web_auth._get_db_session] = ov
    try:
        yield token
    finally:
        app.dependency_overrides.clear()


class TestLanguageRoute:
    def test_default_is_swedish(self, client):
        c = TestClient(app_import(), follow_redirects=False)
        r = c.get("/auth/login")
        assert 'lang="sv"' in r.text
        assert ">Plånböcker<" in r.text

    def test_switch_sets_cookie_and_redirects(self, client):
        c = TestClient(app_import(), follow_redirects=False)
        r = c.get("/lang/en", headers={"referer": "http://testserver/auth/login"})
        assert r.status_code == 303
        assert r.headers["location"] == "/auth/login"
        assert "lang=en" in r.headers.get("set-cookie", "")

    def test_english_cookie_translates_nav(self, client):
        c = TestClient(app_import(), cookies={"lang": "en"}, follow_redirects=False)
        r = c.get("/auth/login")
        assert 'lang="en"' in r.text
        assert ">Wallets<" in r.text and ">Settings<" in r.text
        assert "Plånböcker" not in r.text

    def test_invalid_lang_falls_back_to_sv(self, client):
        c = TestClient(app_import(), follow_redirects=False)
        r = c.get("/lang/zz", headers={"referer": "http://testserver/"})
        assert "lang=sv" in r.headers.get("set-cookie", "")

    def test_cross_origin_referer_ignored(self, client):
        c = TestClient(app_import(), follow_redirects=False)
        r = c.get("/lang/en", headers={"referer": "http://evil.example.com/x"})
        assert r.headers["location"] == "/"


def app_import():
    from kryptoskatt.web.app import app
    return app
