"""Tests for TransferMatcher - TDD approach."""

import pytest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kryptoskatt.models.base import Base
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.transfer_link import TransferLink
from kryptoskatt.engine.transfers import TransferMatcher, TransferMatchReport
from kryptoskatt.enums import EventType


# Test addresses
MY_ETH_ADDR = "0x85fB22b3C15C7C2c93F26E83F446950D9408ba67"
MY_SOL_ADDR = "CAGfWWXbwW3NkbkHFxbhXn1RU7kywHTDaSipsRKeLhR8"
EXTERNAL_ADDR = "0xDEADBEEF1234567890abcdef1234567890abcdef"


@pytest.fixture
def db_session():
    """In-memory SQLite session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def my_addresses():
    """User's wallet addresses."""
    return {
        (MY_ETH_ADDR, "ETHEREUM"),
        (MY_SOL_ADDR, "SOLANA"),
    }


def create_transaction(
    session,
    source_platform="coinbase",
    timestamp_utc=None,
    event_type=None,
    base_coin="ETH",
    base_amount=None,
    tx_hash=None,
    from_address=None,
    to_address=None,
):
    """Helper to create a transaction for testing."""
    if timestamp_utc is None:
        timestamp_utc = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    if base_amount is None:
        base_amount = Decimal("1.0")
    if event_type is None:
        event_type = EventType.TRANSFER_OUT

    tx = Transaction(
        import_batch_id=None,
        wallet_id=None,
        source_platform=source_platform,
        timestamp_utc=timestamp_utc,
        event_type=event_type,
        base_coin=base_coin,
        base_amount=base_amount,
        tx_hash=tx_hash,
        from_address=from_address,
        to_address=to_address,
        is_duplicate=False,
    )
    session.add(tx)
    session.commit()
    return tx


class TestNoTransfers:
    """Test case 1: No TRANSFER_OUT transactions."""

    def test_no_transfers(self, db_session, my_addresses):
        """No TRANSFER_OUT transactions → report shows 0s."""
        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        assert report.total_checked == 0
        assert report.matched == 0
        assert report.unmatched == 0
        assert report.ambiguous == 0


class TestTxHashMatch:
    """Test case 2: TX_HASH matching."""

    def test_tx_hash_match(self, db_session, my_addresses):
        """TRANSFER_OUT + TRANSFER_IN with same tx_hash, to_address is mine → TX_HASH match."""
        # Create TRANSFER_OUT: 1.0 ETH sent from my wallet
        tx_out = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-1.0"),
            tx_hash="0xabc123",
            to_address=MY_ETH_ADDR,  # to my own address (internal transfer)
        )

        # Create TRANSFER_IN: 1.0 ETH received, same tx_hash
        tx_in = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("1.0"),
            tx_hash="0xabc123",  # same hash
            from_address=MY_ETH_ADDR,
            to_address=MY_ETH_ADDR,
        )

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        # Verify report counts
        assert report.total_checked == 1
        assert report.matched == 1
        assert report.unmatched == 0
        assert report.ambiguous == 0

        # Verify TransferLink created
        link = db_session.query(TransferLink).filter(TransferLink.tx_out_id == tx_out.id).first()

        assert link is not None
        assert link.tx_in_id == tx_in.id
        assert link.match_method == "TX_HASH"
        assert link.confidence == Decimal("0.9500")


class TestAmountTimeMatch:
    """Test case 3: AMOUNT_TIME matching."""

    def test_amount_time_match(self, db_session, my_addresses):
        """Same coin, similar amount (±5% fee), timestamp within 30 min → AMOUNT_TIME match."""
        # Create TRANSFER_OUT: 1.0 ETH sent from my wallet (no tx_hash)
        tx_out = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-1.0"),
            tx_hash=None,  # null hash
            to_address=MY_ETH_ADDR,
        )

        # Create TRANSFER_IN: 0.99 ETH received (within 5% fee tolerance), 15 min later
        tx_in = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("0.99"),
            tx_hash=None,
            from_address=MY_ETH_ADDR,
            to_address=MY_ETH_ADDR,
            timestamp_utc=tx_out.timestamp_utc + timedelta(minutes=15),
        )

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        # Verify report counts
        assert report.total_checked == 1
        assert report.matched == 1
        assert report.unmatched == 0
        assert report.ambiguous == 0

        # Verify TransferLink created
        link = db_session.query(TransferLink).filter(TransferLink.tx_out_id == tx_out.id).first()

        assert link is not None
        assert link.tx_in_id == tx_in.id
        assert link.match_method == "AMOUNT_TIME"
        assert link.confidence == Decimal("0.7500")


class TestExternalTransfer:
    """Test case 4: External transfer not matched."""

    def test_external_transfer_not_matched(self, db_session, my_addresses):
        """TRANSFER_OUT to external address (NOT in my_addresses) → no TransferLink."""
        # Create TRANSFER_OUT: 1.0 ETH sent to external address
        tx_out = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-1.0"),
            to_address=EXTERNAL_ADDR,  # external address
        )

        # Even if there's a TRANSFER_IN, it shouldn't match external withdrawal
        tx_in = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("1.0"),
            from_address=EXTERNAL_ADDR,
            to_address=MY_ETH_ADDR,
        )

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        # Verify report counts - external transfers are "unmatched" (potential taxable)
        assert report.total_checked == 1
        assert report.matched == 0
        assert report.unmatched == 1
        assert report.ambiguous == 0

        # Verify NO TransferLink created
        link = db_session.query(TransferLink).filter(TransferLink.tx_out_id == tx_out.id).first()
        assert link is None


class TestFeeTolerance:
    """Test case 5-6: Fee tolerance testing."""

    def test_fee_tolerance(self, db_session, my_addresses):
        """Withdrawal of 1.0 ETH, receipt of 0.96 ETH → still matches (within 5%)."""
        tx_out = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-1.0"),
            tx_hash=None,
            to_address=MY_ETH_ADDR,
        )

        # 0.96 is within 5% of 1.0 (tolerance: 0.95 to 1.05)
        tx_in = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("0.96"),
            tx_hash=None,
            from_address=MY_ETH_ADDR,
            to_address=MY_ETH_ADDR,
            timestamp_utc=tx_out.timestamp_utc + timedelta(minutes=10),
        )

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        assert report.matched == 1
        link = db_session.query(TransferLink).first()
        assert link.match_method == "AMOUNT_TIME"

    def test_fee_tolerance_exceeded(self, db_session, my_addresses):
        """Withdrawal of 1.0 ETH, receipt of 0.5 ETH → no match (>5% difference)."""
        tx_out = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-1.0"),
            tx_hash=None,
            to_address=MY_ETH_ADDR,
        )

        # 0.5 is OUTSIDE 5% of 1.0
        tx_in = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("0.5"),
            tx_hash=None,
            from_address=MY_ETH_ADDR,
            to_address=MY_ETH_ADDR,
            timestamp_utc=tx_out.timestamp_utc + timedelta(minutes=10),
        )

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        # No match - amount difference too large
        assert report.matched == 0
        assert report.unmatched == 1
        link = db_session.query(TransferLink).first()
        assert link is None


class TestTimeWindow:
    """Test case 7: Time window testing."""

    def test_time_window_exceeded(self, db_session, my_addresses):
        """Same coin+amount but timestamp >30 min apart → no match."""
        tx_out = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-1.0"),
            tx_hash=None,
            to_address=MY_ETH_ADDR,
            timestamp_utc=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
        )

        # 45 minutes later (>30 min window)
        tx_in = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("1.0"),
            tx_hash=None,
            from_address=MY_ETH_ADDR,
            to_address=MY_ETH_ADDR,
            timestamp_utc=datetime(2024, 1, 15, 10, 45, 0, tzinfo=timezone.utc),
        )

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        assert report.matched == 0
        assert report.unmatched == 1


class TestDifferentCoin:
    """Test case 8: Different coins don't match."""

    def test_different_coin_no_match(self, db_session, my_addresses):
        """TRANSFER_OUT ETH, TRANSFER_IN BTC → no match."""
        tx_out = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_coin="ETH",
            base_amount=Decimal("-1.0"),
            tx_hash=None,
            to_address=MY_ETH_ADDR,
        )

        tx_in = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_coin="BTC",  # different coin
            base_amount=Decimal("1.0"),
            tx_hash=None,
            from_address=MY_ETH_ADDR,
            to_address=MY_ETH_ADDR,
            timestamp_utc=tx_out.timestamp_utc + timedelta(minutes=5),
        )

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        assert report.matched == 0
        assert report.unmatched == 1


class TestAmbiguousMatch:
    """Test case 9: Ambiguous matches."""

    def test_ambiguous_multiple_matches(self, db_session, my_addresses):
        """TRANSFER_OUT matches 2+ TRANSFER_IN → ambiguous (no link created)."""
        tx_out = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-1.0"),
            tx_hash=None,
            to_address=MY_ETH_ADDR,
        )

        # Two possible TRANSFER_IN matches
        tx_in1 = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("1.0"),
            tx_hash=None,
            from_address=MY_ETH_ADDR,
            to_address=MY_ETH_ADDR,
            timestamp_utc=tx_out.timestamp_utc + timedelta(minutes=5),
        )

        tx_in2 = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("1.0"),
            tx_hash=None,
            from_address=MY_ETH_ADDR,
            to_address=MY_ETH_ADDR,
            timestamp_utc=tx_out.timestamp_utc + timedelta(minutes=10),
        )

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        # Ambiguous - no link created
        assert report.ambiguous == 1
        assert report.matched == 0
        assert report.unmatched == 0
        assert report.total_checked == 1

        # Verify NO TransferLink created
        links = db_session.query(TransferLink).filter(TransferLink.tx_out_id == tx_out.id).all()
        assert len(links) == 0


class TestMatchReport:
    """Test case 10: Report counts."""

    def test_match_report_counts(self, db_session, my_addresses):
        """Verify all counts in TransferMatchReport."""
        # 2 transfers that will be matched
        tx_out1 = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-1.0"),
            tx_hash="0x111",
            to_address=MY_ETH_ADDR,
        )
        tx_in1 = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("1.0"),
            tx_hash="0x111",
        )

        tx_out2 = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-2.0"),
            tx_hash="0x222",
            to_address=MY_ETH_ADDR,
        )

        # 1 unmatched external
        tx_out3 = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-3.0"),
            to_address=EXTERNAL_ADDR,
        )

        # 1 ambiguous
        tx_out4 = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-4.0"),
            tx_hash=None,
            to_address=MY_SOL_ADDR,
        )
        create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("4.0"),
            tx_hash=None,
            timestamp_utc=tx_out4.timestamp_utc + timedelta(minutes=5),
        )
        create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("4.0"),
            tx_hash=None,
            timestamp_utc=tx_out4.timestamp_utc + timedelta(minutes=7),
        )

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        # Total: 4 TRANSFER_OUT examined (tx_out1-4)
        # Matched: 1 (tx_out1 via TX_HASH)
        # Unmatched: 1 (tx_out3 external)
        # Ambiguous: 1 (tx_out4 multiple matches)
        # Remaining 1 (tx_out2) should still be unmatched since there's no matching IN
        assert report.total_checked == 4
        assert report.matched == 1
        assert report.unmatched == 2  # tx_out2 + tx_out3
        assert report.ambiguous == 1


class TestAlreadyLinked:
    """Test case 11: Already linked transactions."""

    def test_already_linked_skipped(self, db_session, my_addresses):
        """TRANSFER_OUT already in TransferLink → skipped."""
        # Create existing link
        tx_out = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-1.0"),
            tx_hash="0xabc",
            to_address=MY_ETH_ADDR,
        )
        tx_in = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("1.0"),
            tx_hash="0xabc",
        )

        # Create existing TransferLink
        existing_link = TransferLink(
            tx_out_id=tx_out.id,
            tx_in_id=tx_in.id,
            match_method="TX_HASH",
            confidence=Decimal("0.9500"),
        )
        db_session.add(existing_link)
        db_session.commit()

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        # Should skip the already-linked transaction
        assert report.total_checked == 0
        assert report.matched == 0


class TestNegativeAmount:
    """Test case 12: Negative amount handling."""

    def test_negative_amount_handling(self, db_session, my_addresses):
        """TRANSFER_OUT has negative amount, TRANSFER_IN positive → abs() used."""
        # TRANSFER_OUT has NEGATIVE amount (-1.0)
        tx_out = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_OUT,
            base_amount=Decimal("-1.0"),  # negative
            tx_hash=None,
            to_address=MY_ETH_ADDR,
        )

        # TRANSFER_IN has POSITIVE amount (1.0)
        tx_in = create_transaction(
            db_session,
            event_type=EventType.TRANSFER_IN,
            base_amount=Decimal("1.0"),  # positive
            tx_hash=None,
            from_address=MY_ETH_ADDR,
            to_address=MY_ETH_ADDR,
            timestamp_utc=tx_out.timestamp_utc + timedelta(minutes=5),
        )

        matcher = TransferMatcher(db_session, my_addresses)
        report = matcher.match_all()

        # Should match - abs() used for comparison
        assert report.matched == 1
        link = db_session.query(TransferLink).first()
        assert link is not None
