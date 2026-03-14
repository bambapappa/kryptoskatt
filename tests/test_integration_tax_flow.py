"""Integration test: complete tax calculation flow from import to K4 report."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kryptoskatt.engine.dedup import DeduplicationEngine
from kryptoskatt.engine.gav import GavEngine
from kryptoskatt.engine.transfers import TransferMatcher
from kryptoskatt.models.base import Base
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.transfer_link import TransferLink
from kryptoskatt.reports.issues import FlaggedIssuesGenerator
from kryptoskatt.reports.k4 import K4ReportGenerator


@pytest.fixture
def db_session():
    """In-memory SQLite session with all tables created and a test account."""
    from tests.conftest import make_test_account

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    make_test_account(session)
    yield session
    session.close()


def _tx(
    session: Session,
    event_type: str,
    base_coin: str,
    base_amount: Decimal,
    price_sek: Decimal | None,
    timestamp_utc: datetime,
    *,
    user_id: int = 1,
    tx_hash: str | None = None,
    from_address: str | None = None,
    to_address: str | None = None,
) -> Transaction:
    """Create and persist a Transaction, returning the saved instance."""
    tx = Transaction(
        user_id=user_id,
        source_platform="TEST",
        timestamp_utc=timestamp_utc,
        event_type=event_type,
        base_coin=base_coin,
        base_amount=base_amount,
        price_sek=price_sek,
        tx_hash=tx_hash,
        from_address=from_address,
        to_address=to_address,
        import_batch_id=None,
    )
    session.add(tx)
    session.commit()
    return tx


class TestFullBuySellFlow:
    """Complete pipeline: BUY × 2 → SELL → dedup → transfer-match → GAV → K4."""

    def test_full_buy_sell_flow(self, db_session: Session):
        """
        1. Create two BUY transactions at different prices
        2. Create one SELL for half the holdings
        3. Run DeduplicationEngine
        4. Run TransferMatcher
        5. Run GavEngine
        6. Verify K4Report has correct disposal with GAV-based cost basis
        """
        # Step 1: two BUY transactions
        _tx(
            db_session,
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("10000"),
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
        )
        _tx(
            db_session,
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("20000"),
            timestamp_utc=datetime(2024, 3, 1, 10, 0, 0, tzinfo=UTC),
        )

        # Step 2: sell half
        _tx(
            db_session,
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-1"),
            price_sek=Decimal("18000"),
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
        )

        # Step 3: deduplication (no duplicates expected here)
        dedup = DeduplicationEngine(db_session, user_id=1)
        dedup_report = dedup.deduplicate_all()
        assert dedup_report.removed_count == 0

        # Step 4: transfer matching (no transfers, should be a no-op)
        matcher = TransferMatcher(db_session, my_addresses=set(), user_id=1)
        match_report = matcher.match_all()
        assert match_report.matched == 0

        # Step 5: GAV calculation
        gav = GavEngine(db_session, user_id=1)
        result = gav.calculate(year=2024)

        # GAV = (10000 + 20000) / 2 = 15000
        assert len(result.disposals) == 1
        disposal = result.disposals[0]
        assert disposal.coin == "ETH"
        assert disposal.sell_amount == Decimal("1")
        assert disposal.gav_at_disposal == Decimal("15000")
        # cost_basis = 1 * 15000 = 15000
        assert disposal.cost_basis_sek == Decimal("15000")
        # proceeds = 1 * 18000 = 18000
        assert disposal.proceeds_sek == Decimal("18000")
        # gain = 18000 - 15000 = 3000
        assert disposal.gain_loss_sek == Decimal("3000")

        # All monetary values must be Decimal
        assert isinstance(disposal.proceeds_sek, Decimal)
        assert isinstance(disposal.cost_basis_sek, Decimal)
        assert isinstance(disposal.gain_loss_sek, Decimal)
        assert isinstance(disposal.gav_at_disposal, Decimal)

        # Step 6: K4 report
        k4_gen = K4ReportGenerator(db_session, user_id=1)
        report = k4_gen.generate(year=2024)

        assert report.tax_year == 2024
        assert len(report.rows) == 1
        eth_row = report.rows[0]
        assert eth_row.coin == "ETH"
        assert eth_row.proceeds_sek == Decimal("18000.00")
        assert eth_row.cost_basis_sek == Decimal("15000.00")
        assert eth_row.gain_loss_sek == Decimal("3000.00")
        assert report.total_gains == Decimal("3000.00")
        assert report.total_losses == Decimal("0.00")


class TestGavCarryForwardAcrossYears:
    """GAV from year N must be correctly carried forward to year N+1."""

    def test_gav_carries_forward_across_years(self, db_session: Session):
        """
        År 1: Köp 1 ETH @ 10000 SEK
        År 2: Köp 1 ETH @ 20000 SEK, sälj 1 ETH
        Förväntat: GAV = (10000+20000)/2 = 15000, vinst = säljpris - 15000
        """
        # Year 1 purchase
        _tx(
            db_session,
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("10000"),
            timestamp_utc=datetime(2023, 6, 1, 10, 0, 0, tzinfo=UTC),
        )

        # Year 2 purchase
        _tx(
            db_session,
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1"),
            price_sek=Decimal("20000"),
            timestamp_utc=datetime(2024, 3, 1, 10, 0, 0, tzinfo=UTC),
        )

        # Year 2 sale — sell exactly 1 ETH
        _tx(
            db_session,
            event_type="SELL",
            base_coin="ETH",
            base_amount=Decimal("-1"),
            price_sek=Decimal("25000"),
            timestamp_utc=datetime(2024, 9, 1, 10, 0, 0, tzinfo=UTC),
        )

        gav = GavEngine(db_session, user_id=1)

        # Compute with year filter so only 2024 disposals are returned;
        # the engine still processes all historical events to build correct GAV.
        result = gav.calculate(year=2024)

        assert len(result.disposals) == 1
        disposal = result.disposals[0]

        # GAV at disposal: (10000 + 20000) / 2 = 15000
        assert disposal.gav_at_disposal == Decimal("15000")
        assert disposal.cost_basis_sek == Decimal("15000")
        assert disposal.proceeds_sek == Decimal("25000")
        assert disposal.gain_loss_sek == Decimal("10000")
        assert disposal.tax_year == 2024

        # No year-1 disposals should appear in the 2024 result
        for d in result.disposals:
            assert d.tax_year == 2024


class TestMatchedTransferNotTaxable:
    """A linked transfer (both wallets owned) must NOT create a taxable disposal."""

    def test_matched_transfer_not_taxable(self, db_session: Session):
        """
        1. Buy 1 BTC.
        2. Transfer 1 BTC from address A → B (both owned).
        3. Create TransferLink so GAV engine knows it is internal.
        4. Run GavEngine — no Disposal should be created.
        """
        wallet_a = "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divfna"
        wallet_b = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"

        # Acquisition
        _tx(
            db_session,
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("1"),
            price_sek=Decimal("400000"),
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
        )

        # Internal transfer out
        tx_out = _tx(
            db_session,
            event_type="TRANSFER_OUT",
            base_coin="BTC",
            base_amount=Decimal("-1"),
            price_sek=Decimal("400000"),
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            tx_hash="0xdeadbeef001",
            from_address=wallet_a,
            to_address=wallet_b,
        )

        # Internal transfer in
        tx_in = _tx(
            db_session,
            event_type="TRANSFER_IN",
            base_coin="BTC",
            base_amount=Decimal("1"),
            price_sek=Decimal("400000"),
            timestamp_utc=datetime(2024, 6, 1, 10, 5, 0, tzinfo=UTC),
            tx_hash="0xdeadbeef001",
            from_address=wallet_a,
            to_address=wallet_b,
        )

        # Create TransferLink
        link = TransferLink(
            tx_out_id=tx_out.id,
            tx_in_id=tx_in.id,
            match_method="TX_HASH",
            confidence=Decimal("0.95"),
        )
        db_session.add(link)
        db_session.commit()

        # Run TransferMatcher with both addresses registered as owned
        my_addresses = {(wallet_a, "BTC"), (wallet_b, "BTC")}
        matcher = TransferMatcher(db_session, my_addresses=my_addresses, user_id=1)
        # Link already created above; matcher should report 0 unmatched
        # (tx_out already linked, so matcher will skip it)
        match_report = matcher.match_all()
        # tx_out is already linked, so nothing new to match
        assert match_report.matched == 0 or match_report.total_checked == 0

        # GAV calculation must produce no disposals
        gav = GavEngine(db_session, user_id=1)
        result = gav.calculate(year=2024)

        assert len(result.disposals) == 0, (
            f"Expected no disposals for internal transfer but got {result.disposals}"
        )

        # Holdings should be preserved: still 1 BTC with cost basis 400000
        from sqlalchemy import select as sa_select

        from kryptoskatt.models.gav_ledger import GavLedger

        ledger = db_session.execute(
            sa_select(GavLedger)
            .where(GavLedger.user_id == 1, GavLedger.coin == "BTC")
            .order_by(GavLedger.timestamp)
        ).scalars().all()

        # Last ledger entry should show 1 BTC remaining
        final = ledger[-1]
        assert final.total_amount == Decimal("1")
        assert final.total_cost_sek == Decimal("400000")


class TestUnbalancedSwapFlagged:
    """SWAP_IN without a SWAP_OUT counterpart within 30 minutes is flagged."""

    def test_orphaned_swap_in_flagged_in_issues(self, db_session: Session):
        """A SWAP_IN with no matching SWAP_OUT should produce a WARNING issue."""
        _tx(
            db_session,
            event_type="SWAP_IN",
            base_coin="ETH",
            base_amount=Decimal("0.5"),
            price_sek=Decimal("30000"),
            timestamp_utc=datetime(2024, 5, 1, 12, 0, 0, tzinfo=UTC),
        )

        gen = FlaggedIssuesGenerator(db_session, user_id=1)
        report = gen.generate(year=2024)

        unbalanced = [i for i in report.issues if i.category == "unbalanced_swap"]
        assert len(unbalanced) == 1
        assert unbalanced[0].coin == "ETH"
        assert unbalanced[0].severity == "WARNING"

    def test_balanced_swap_not_flagged(self, db_session: Session):
        """A SWAP_IN paired with a SWAP_OUT within 30 minutes must NOT be flagged."""
        _tx(
            db_session,
            event_type="SWAP_OUT",
            base_coin="BTC",
            base_amount=Decimal("-0.01"),
            price_sek=Decimal("400000"),
            timestamp_utc=datetime(2024, 5, 1, 12, 0, 0, tzinfo=UTC),
        )
        _tx(
            db_session,
            event_type="SWAP_IN",
            base_coin="ETH",
            base_amount=Decimal("0.1"),
            price_sek=Decimal("40000"),
            timestamp_utc=datetime(2024, 5, 1, 12, 0, 30, tzinfo=UTC),
        )

        gen = FlaggedIssuesGenerator(db_session, user_id=1)
        report = gen.generate(year=2024)

        unbalanced = [i for i in report.issues if i.category == "unbalanced_swap"]
        assert len(unbalanced) == 0
