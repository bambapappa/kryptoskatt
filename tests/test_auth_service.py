"""Tests for AuthService — account creation, session management, authentication."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models.base import Base
from kryptoskatt.models.user_session import UserSession
from kryptoskatt.services.auth import AuthService, get_legacy_user_id, hash_token

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Fresh in-memory DB for each test, with legacy account pre-inserted."""
    from tests.conftest import make_test_account

    Base.metadata.create_all(engine)
    session = TestingSession()
    make_test_account(session)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def auth_service(db_session):
    return AuthService(db_session)


class TestCreateAccount:
    def test_create_account_returns_account_and_token(self, auth_service):
        account, token = auth_service.create_account()

        assert account.id is not None
        assert len(token) == 64
        assert all(c in "0123456789abcdef" for c in token)

    def test_create_account_generates_wordlist_id(self, auth_service):
        account, _ = auth_service.create_account()

        assert re.match(r"^[a-z]+-[a-z]+-[a-z]+-\d{4}$", account.account_id)

    def test_create_account_saves_to_db(self, auth_service, db_session):
        from kryptoskatt.models.account import Account

        account, _ = auth_service.create_account()

        stored = db_session.query(Account).filter(Account.id == account.id).first()
        assert stored is not None
        assert stored.account_id == account.account_id


class TestSessionTokenHashing:
    def test_token_stored_hashed_not_raw(self, auth_service, db_session):
        _, token = auth_service.create_account()

        row = db_session.query(UserSession).order_by(UserSession.id.desc()).first()
        assert row.session_token != token
        assert row.session_token == hash_token(token)

    def test_create_session_returns_raw_token_that_authenticates(self, auth_service):
        account, _ = auth_service.create_account()

        _, raw_token = auth_service.create_session(account)

        result = auth_service.authenticate(raw_token)
        assert result is not None
        assert result.id == account.id


class TestAuthenticate:
    def test_authenticate_valid_token_returns_account(self, auth_service):
        account, token = auth_service.create_account()

        result = auth_service.authenticate(token)

        assert result is not None
        assert result.id == account.id

    def test_authenticate_invalid_token_returns_none(self, auth_service):
        result = auth_service.authenticate("bad-token")

        assert result is None

    def test_authenticate_expired_token_returns_none(self, auth_service, db_session):
        account, token = auth_service.create_account()

        # Expire the session manually (DB stores the hash, not the raw token)
        session_row = (
            db_session.query(UserSession)
            .filter(UserSession.session_token == hash_token(token))
            .first()
        )
        session_row.expires_at = datetime.now(UTC) - timedelta(days=1)
        db_session.commit()

        result = auth_service.authenticate(token)

        assert result is None

    def test_authenticate_extends_expiry(self, auth_service, db_session):
        account, token = auth_service.create_account()

        before = datetime.now(UTC)
        result = auth_service.authenticate(token)

        assert result is not None
        session_row = (
            db_session.query(UserSession)
            .filter(UserSession.session_token == hash_token(token))
            .first()
        )
        # SQLite returns naive datetimes; normalise to UTC for comparison
        last_used = session_row.last_used_at
        if last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=UTC)
        assert last_used >= before


class TestLogout:
    def test_logout_removes_session(self, auth_service):
        _, token = auth_service.create_account()

        auth_service.logout(token)

        assert auth_service.authenticate(token) is None

    def test_logout_nonexistent_token_is_noop(self, auth_service):
        # Must not raise
        auth_service.logout("nonexistent-token-that-does-not-exist")


class TestGetAccountById:
    def test_get_account_by_id_found(self, auth_service):
        account, _ = auth_service.create_account()

        result = auth_service.get_account_by_id(account.account_id)

        assert result is not None
        assert result.id == account.id

    def test_get_account_by_id_not_found(self, auth_service):
        result = auth_service.get_account_by_id("does-not-exist")

        assert result is None


class TestGetLegacyUserId:
    def test_get_legacy_user_id_returns_int(self, db_session):
        result = get_legacy_user_id(db_session)

        assert isinstance(result, int)
        assert result >= 1
