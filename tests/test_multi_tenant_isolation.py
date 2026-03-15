"""Verify that accounts cannot access each other's data."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from kryptoskatt.engine.dedup import DeduplicationEngine
from kryptoskatt.models.base import Base
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.gav_ledger import GavLedger
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.reports.gav_history import GavHistoryReport
from kryptoskatt.reports.k4 import K4ReportGenerator
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.auth import AuthService
from kryptoskatt.services.wallet import WalletService


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture(scope="module")
def session(engine):
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture(scope="module")
def two_accounts(session):
    """Create two independent accounts and return their Account objects."""
    account1, _ = AuthService(session).create_account()
    account2, _ = AuthService(session).create_account()
    return account1, account2


# ── Tests ────────────────────────────────────────────────────────────────────


def test_wallet_isolation(session, two_accounts):
    """Wallet added for account1 is invisible to account2."""
    account1, account2 = two_accounts
    svc1 = WalletService(session, account1.id)
    svc2 = WalletService(session, account2.id)

    svc1.add_wallet(
        WalletCreate(
            address="0xIsolationTest0000000000000000000000001",
            chain="ETHEREUM",
            label="Account1 only",
            is_mine=True,
        ),
        strict_validation=False,
    )

    wallets2 = svc2.list_wallets()
    addresses = [w.address for w in wallets2]
    assert "0xIsolationTest0000000000000000000000001" not in addresses


def test_disposal_isolation(session, two_accounts):
    """Disposal created for account1 is invisible to K4Report for account2."""
    account1, account2 = two_accounts

    disposal = Disposal(
        user_id=account1.id,
        tax_year=2024,
        coin="BTC",
        sell_timestamp=datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC),
        sell_amount=Decimal("-0.1"),
        proceeds_sek=Decimal("50000"),
        cost_basis_sek=Decimal("40000"),
        gain_loss_sek=Decimal("10000"),
        gav_at_disposal=Decimal("400000"),
    )
    session.add(disposal)
    session.commit()

    report2 = K4ReportGenerator(session, account2.id).generate(2024)
    # account2 should see no rows from account1's disposal
    assert len(report2.rows) == 0


def test_gav_isolation(session, two_accounts):
    """GavLedger entry for account1 is invisible to GavHistoryReport for account2."""
    account1, account2 = two_accounts

    ledger_entry = GavLedger(
        user_id=account1.id,
        coin="ETH",
        timestamp=datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC),
        event_type="BUY",
        amount_change=Decimal("1.0"),
        total_amount=Decimal("1.0"),
        total_cost_sek=Decimal("30000"),
        gav_per_unit_sek=Decimal("30000"),
    )
    session.add(ledger_entry)
    session.commit()

    history2 = GavHistoryReport(session, account2.id).generate(coin="ETH")
    assert history2 == []


def test_transaction_isolation(session, two_accounts):
    """Transaction for account1 is not seen by DeduplicationEngine for account2."""
    account1, account2 = two_accounts

    tx = Transaction(
        user_id=account1.id,
        source_platform="coinbase",
        timestamp_utc=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        event_type="BUY",
        base_coin="SOL",
        base_amount=Decimal("10"),
        is_duplicate=False,
    )
    session.add(tx)
    session.commit()

    dedup2 = DeduplicationEngine(session, account2.id)
    report = dedup2.deduplicate_all()
    # account2 should have no transactions to check
    assert report.total_checked == 0
