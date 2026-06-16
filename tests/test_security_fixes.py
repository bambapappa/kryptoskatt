"""Security regression tests for the hardening in this change set.

Covers:
  * SSRF guard (utils.url_guard) and its use in DynamicBlockscoutAdapter
  * login rate limiting on POST /api/v1/auth/session
  * per-account (multi-tenant) isolation of the coin blacklist in the GAV engine
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models.base import Base
from kryptoskatt.utils.url_guard import UnsafeURLError, validate_outbound_url

# ── SSRF guard ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata (link-local)
        "http://127.0.0.1:6379/",                      # loopback (e.g. redis)
        "http://10.0.0.5/api",                         # private
        "http://192.168.1.1/",                         # private
        "http://172.16.0.1/api",                       # private
        "http://[::1]/api",                            # loopback IPv6
        "http://[::ffff:169.254.169.254]/",            # IPv4-mapped link-local
        "http://0.0.0.0/",                             # unspecified
    ],
)
def test_validate_outbound_url_blocks_internal(url):
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "gopher://1.1.1.1/",
        "redis://127.0.0.1:6379",
        "",
        "not-a-url",
    ],
)
def test_validate_outbound_url_blocks_bad_scheme(url):
    with pytest.raises(UnsafeURLError):
        validate_outbound_url(url)


@pytest.mark.parametrize("url", ["http://1.1.1.1/api", "https://8.8.8.8/api"])
def test_validate_outbound_url_allows_public(url):
    assert validate_outbound_url(url) == url


def test_dynamic_blockscout_adapter_blocks_ssrf():
    """A user-configured Blockscout URL pointing at metadata must not be fetched."""
    from kryptoskatt.chains.blockscout import DynamicBlockscoutAdapter

    adapter = DynamicBlockscoutAdapter(
        chain_name="EVIL", base_url="http://169.254.169.254/api", native_coin="EVIL"
    )
    with pytest.raises(UnsafeURLError):
        adapter.fetch_transactions("0xabc", "EVIL")


# ── Login rate limiting ─────────────────────────────────────────────────────────


def _db_override(session):
    def override():
        try:
            yield session
        finally:
            pass

    return override


def test_login_is_rate_limited():
    """POST /api/v1/auth/session is throttled per client to slow account_id brute force."""
    from fastapi.testclient import TestClient

    from kryptoskatt.api.v1 import auth as auth_module
    from kryptoskatt.services.rate_limiter import login_limiter
    from kryptoskatt.web import auth as web_auth_module
    from kryptoskatt.web.app import app, get_db

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    override = _db_override(session)
    app.dependency_overrides[get_db] = override
    app.dependency_overrides[auth_module._get_db] = override
    app.dependency_overrides[web_auth_module._get_db_session] = override

    login_limiter._windows.clear()  # isolate from other tests sharing the singleton
    try:
        with TestClient(app) as c:
            # First 10 attempts are allowed through (invalid account_id → 401)
            statuses = [
                c.post("/api/v1/auth/session", json={"account_id": "bad-x-y-0000"}).status_code
                for _ in range(10)
            ]
            assert statuses == [401] * 10
            # The 11th within the window is rejected by the rate limiter
            blocked = c.post("/api/v1/auth/session", json={"account_id": "bad-x-y-0000"})
            assert blocked.status_code == 429
    finally:
        login_limiter._windows.clear()
        app.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(engine)


# ── Per-tenant coin blacklist ────────────────────────────────────────────────────


def _gav_session():
    from tests.conftest import make_test_account

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    make_test_account(session)  # legacy account → id 1
    return session


def _buy_sell(session, user_id: int) -> None:
    from kryptoskatt.models.transaction import Transaction

    session.add(
        Transaction(
            user_id=user_id, source_platform="TEST",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY", base_coin="SPAM", base_amount=Decimal("1"),
            quote_coin="SEK", quote_amount=Decimal("20000"),
            price_sek=Decimal("20000"), is_duplicate=False,
        )
    )
    session.add(
        Transaction(
            user_id=user_id, source_platform="TEST",
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            event_type="SELL", base_coin="SPAM", base_amount=Decimal("-0.5"),
            quote_coin="SEK", quote_amount=Decimal("12500"),
            price_sek=Decimal("25000"), is_duplicate=False,
        )
    )
    session.commit()


def test_coin_blacklist_is_per_tenant_in_gav():
    """One account's blacklist must not affect another account's tax calculation."""
    from kryptoskatt.engine.gav import GavEngine
    from kryptoskatt.models.coin_blacklist import CoinBlacklist
    from kryptoskatt.services.auth import AuthService

    session = _gav_session()
    try:
        account2, _ = AuthService(session).create_account()
        _buy_sell(session, 1)
        _buy_sell(session, account2.id)

        # Account 1 blacklists SPAM; account 2 does not.
        session.add(CoinBlacklist(user_id=1, coin_symbol="SPAM"))
        session.commit()

        # Account 1: SPAM excluded → no disposals.
        assert len(GavEngine(session, 1).calculate().disposals) == 0
        # Account 2: SPAM still counted → disposal present.
        assert len(GavEngine(session, account2.id).calculate().disposals) == 1
    finally:
        session.close()


def test_coin_blacklist_rows_are_scoped_by_user():
    from kryptoskatt.models.coin_blacklist import CoinBlacklist
    from kryptoskatt.services.auth import AuthService

    session = _gav_session()
    try:
        account2, _ = AuthService(session).create_account()
        session.add(CoinBlacklist(user_id=1, coin_symbol="FOO"))
        session.commit()

        a1 = session.query(CoinBlacklist).filter(CoinBlacklist.user_id == 1).all()
        a2 = session.query(CoinBlacklist).filter(CoinBlacklist.user_id == account2.id).all()
        assert [r.coin_symbol for r in a1] == ["FOO"]
        assert a2 == []
    finally:
        session.close()
