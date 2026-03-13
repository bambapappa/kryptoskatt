"""Tests for custom chain configuration and registry building."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.models.base import Base
from kryptoskatt.models.custom_chain_config import CustomChainConfig

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


def _make_chain_config(
    db_session,
    *,
    account_id: int,
    chain_name: str,
    adapter_type: str,
    explorer_url: str = "https://explorer.example.io/api",
    native_coin: str = "MCH",
) -> CustomChainConfig:
    cfg = CustomChainConfig(
        account_id=account_id,
        chain_name=chain_name,
        explorer_url=explorer_url,
        api_key=None,
        adapter_type=adapter_type,
        native_coin=native_coin,
        chain_id=None,
        created_at=datetime.now(UTC),
    )
    db_session.add(cfg)
    db_session.commit()
    return cfg


class TestGetRegistryForUser:
    def test_get_registry_for_user_includes_custom_blockscout(self, db_session):
        from kryptoskatt.chains import get_registry_for_user

        _make_chain_config(
            db_session,
            account_id=1,
            chain_name="MYCHAIN",
            adapter_type="blockscout",
        )

        registry = get_registry_for_user(db_session, 1)

        assert registry.get_adapter("MYCHAIN") is not None

    def test_get_registry_for_user_includes_custom_etherscan(self, db_session):
        from kryptoskatt.chains import get_registry_for_user

        _make_chain_config(
            db_session,
            account_id=1,
            chain_name="MYEVMCHAIN",
            adapter_type="etherscan",
            native_coin="ETH",
        )

        registry = get_registry_for_user(db_session, 1)

        assert registry.get_adapter("MYEVMCHAIN") is not None

    def test_get_registry_for_user_unknown_adapter_type_skipped(self, db_session):
        from kryptoskatt.chains import get_registry_for_user

        _make_chain_config(
            db_session,
            account_id=1,
            chain_name="GHOSTCHAIN",
            adapter_type="unknown_type",
        )

        registry = get_registry_for_user(db_session, 1)

        assert registry.get_adapter("GHOSTCHAIN") is None

    def test_get_registry_for_user_only_loads_own_chains(self, db_session):
        from kryptoskatt.chains import get_registry_for_user
        from kryptoskatt.models.account import Account

        # Chain belongs to account 1
        _make_chain_config(
            db_session,
            account_id=1,
            chain_name="ACCOUNT1CHAIN",
            adapter_type="blockscout",
        )

        # Create a second account
        now = datetime.now(UTC)
        account2 = Account(
            account_id="other-test-user-0001",
            created_at=now,
            last_active_at=now,
            is_active=True,
        )
        db_session.add(account2)
        db_session.commit()
        db_session.refresh(account2)

        registry2 = get_registry_for_user(db_session, account2.id)

        assert registry2.get_adapter("ACCOUNT1CHAIN") is None
