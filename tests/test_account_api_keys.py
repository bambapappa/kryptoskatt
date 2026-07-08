"""Tests for per-account API keys and their injection into the chain registry."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kryptoskatt.models.account_api_key import AccountApiKey
from kryptoskatt.models.base import Base
from kryptoskatt.services import api_keys as ak


@pytest.fixture
def session():
    from tests.conftest import make_test_account

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    make_test_account(sess)
    yield sess
    sess.close()


def test_set_and_get_account_key(session):
    ak.set_account_api_key(session, 1, "etherscan", "MYKEY")
    keys = ak.get_account_api_keys(session, 1)
    assert keys == {"etherscan": "MYKEY"}


def test_empty_value_removes_key(session):
    ak.set_account_api_key(session, 1, "helius", "K")
    assert "helius" in ak.get_account_api_keys(session, 1)
    ak.set_account_api_key(session, 1, "helius", "")
    assert ak.get_account_api_keys(session, 1) == {}
    assert session.query(AccountApiKey).count() == 0


def test_update_existing_key(session):
    ak.set_account_api_key(session, 1, "etherscan", "OLD")
    ak.set_account_api_key(session, 1, "etherscan", "NEW")
    assert ak.get_account_api_keys(session, 1) == {"etherscan": "NEW"}
    assert session.query(AccountApiKey).count() == 1


def test_unknown_provider_raises(session):
    with pytest.raises(ValueError):
        ak.set_account_api_key(session, 1, "bogus", "x")


def test_resolve_prefers_account_key_over_settings(session, monkeypatch):
    from kryptoskatt.config import settings

    monkeypatch.setattr(settings, "etherscan_api_key", "INSTANCE", raising=False)
    ak.set_account_api_key(session, 1, "etherscan", "ACCOUNT")
    resolved = ak.resolve_api_keys(session, 1)
    assert resolved["etherscan"] == "ACCOUNT"


def test_resolve_falls_back_to_settings(session, monkeypatch):
    from kryptoskatt.config import settings

    monkeypatch.setattr(settings, "etherscan_api_key", "INSTANCE", raising=False)
    resolved = ak.resolve_api_keys(session, 1)
    assert resolved["etherscan"] == "INSTANCE"


def test_registry_uses_account_key(session, monkeypatch):
    from kryptoskatt.chains import get_registry_for_user
    from kryptoskatt.config import settings

    monkeypatch.setattr(settings, "etherscan_api_key", "INSTANCE", raising=False)
    ak.set_account_api_key(session, 1, "etherscan", "ACCOUNT")

    registry = get_registry_for_user(session, 1)
    adapter = registry.get_adapter("ETHEREUM")
    assert adapter is not None
    assert adapter._key == "ACCOUNT"


def test_status_reports_own_and_fallback(session, monkeypatch):
    from kryptoskatt.config import settings

    monkeypatch.setattr(settings, "etherscan_api_key", "INSTANCE", raising=False)
    monkeypatch.setattr(settings, "helius_api_key", "", raising=False)
    ak.set_account_api_key(session, 1, "etherscan", "ACCOUNT")

    status = {s["slug"]: s for s in ak.account_key_status(session, 1)}
    assert status["etherscan"]["has_own_key"] is True
    assert status["helius"]["has_own_key"] is False
    assert status["helius"]["instance_fallback"] is False
