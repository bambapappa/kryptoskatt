"""Tests for the DeduplicationEngine."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from kryptoskatt.models.base import Base
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.engine.dedup import DeduplicationEngine, DeduplicationReport
from datetime import datetime, timezone, timedelta
from decimal import Decimal


@pytest.fixture
def db_session():
    """Create an in-memory SQLite session for testing."""
    from tests.conftest import make_test_account

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    make_test_account(session)
    yield session
    session.close()


def create_transaction(
    session: Session,
    source_platform: str,
    timestamp_utc: datetime,
    base_coin: str,
    base_amount: Decimal,
    tx_hash: str | None = None,
    is_duplicate: bool = False,
    event_type: str = "TRANSFER_IN",
    user_id: int = 1,
) -> Transaction:
    """Helper to create a Transaction in the test database."""
    tx = Transaction(
        user_id=user_id,
        source_platform=source_platform,
        timestamp_utc=timestamp_utc,
        event_type=event_type,
        base_coin=base_coin,
        base_amount=base_amount,
        tx_hash=tx_hash,
        is_duplicate=is_duplicate,
        import_batch_id=None,
        wallet_id=None,
    )
    session.add(tx)
    session.commit()
    return tx


class TestNoDuplicates:
    """Tests for when there are no duplicates."""

    def test_no_duplicates(self, db_session: Session):
        """All unique tx_hashes should result in nothing marked."""
        # Create transactions with unique tx_hashes
        create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )
        create_transaction(
            db_session,
            source_platform="COINBASE",
            timestamp_utc=datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="ETH",
            base_amount=Decimal("1.0"),
            tx_hash="0xdef456",
        )

        engine = DeduplicationEngine(db_session, 1)
        report = engine.deduplicate_all()

        assert report.exact_matches == 0
        assert report.heuristic_matches == 0
        assert report.kept_count == 2
        assert report.removed_count == 0


class TestExactTxHashDedup:
    """Tests for exact tx_hash matching."""

    def test_exact_tx_hash_dedup(self, db_session: Session):
        """Same tx_hash on CSV + on-chain should mark CSV as duplicate."""
        # On-chain transaction (canonical)
        on_chain_tx = create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )

        # CSV transaction (should be marked duplicate)
        create_transaction(
            db_session,
            source_platform="COINBASE",
            timestamp_utc=datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )

        engine = DeduplicationEngine(db_session, 1)
        report = engine.deduplicate_all()

        assert report.exact_matches == 1
        assert report.kept_count == 1
        assert report.removed_count == 1

        # Refresh and check
        db_session.refresh(on_chain_tx)
        assert on_chain_tx.is_duplicate is False


class TestMexcSuffixStripping:
    """Tests for MEXC TxID suffix stripping."""

    def test_mexc_suffix_stripping(self, db_session: Session):
        """hash:010 should match hash - CSV should be marked duplicate."""
        # On-chain transaction (canonical)
        on_chain_tx = create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM",
        )

        # MEXC transaction with suffix (should be matched)
        create_transaction(
            db_session,
            source_platform="MEXC",
            timestamp_utc=datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM:010",
        )

        engine = DeduplicationEngine(db_session, 1)
        report = engine.deduplicate_all()

        assert report.exact_matches == 1
        assert report.kept_count == 1
        assert report.removed_count == 1

        db_session.refresh(on_chain_tx)
        assert on_chain_tx.is_duplicate is False


class TestHeuristicDedup:
    """Tests for heuristic matching when tx_hash is null."""

    def test_heuristic_dedup_same_coin_amount_time(self, db_session: Session):
        """Same coin, amount, timestamp within 5 min should be duplicate."""
        # On-chain transaction (canonical)
        on_chain_tx = create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash=None,
        )

        # CSV transaction (should be marked duplicate)
        create_transaction(
            db_session,
            source_platform="COINBASE",
            timestamp_utc=datetime(2024, 1, 1, 10, 3, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash=None,
        )

        engine = DeduplicationEngine(db_session, 1)
        report = engine.deduplicate_all()

        assert report.heuristic_matches == 1
        assert report.kept_count == 1
        assert report.removed_count == 1

        db_session.refresh(on_chain_tx)
        assert on_chain_tx.is_duplicate is False

    def test_heuristic_no_match_different_coin(self, db_session: Session):
        """Different coins should not match even with same amount/time."""
        create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash=None,
        )
        create_transaction(
            db_session,
            source_platform="COINBASE",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="ETH",
            base_amount=Decimal("0.01"),
            tx_hash=None,
        )

        engine = DeduplicationEngine(db_session, 1)
        report = engine.deduplicate_all()

        assert report.heuristic_matches == 0

    def test_heuristic_no_match_time_too_far(self, db_session: Session):
        """Timestamp >5 min apart should not match."""
        create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash=None,
        )
        create_transaction(
            db_session,
            source_platform="COINBASE",
            timestamp_utc=datetime(2024, 1, 1, 10, 10, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash=None,
        )

        engine = DeduplicationEngine(db_session, 1)
        report = engine.deduplicate_all()

        assert report.heuristic_matches == 0


class TestPriorityHandling:
    """Tests for source platform priority."""

    def test_on_chain_preferred_over_csv(self, db_session: Session):
        """ON_CHAIN should be kept, CSV marked as duplicate."""
        # CSV transaction first
        csv_tx = create_transaction(
            db_session,
            source_platform="COINBASE",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )

        # On-chain transaction second
        on_chain_tx = create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )

        engine = DeduplicationEngine(db_session, 1)
        report = engine.deduplicate_all()

        db_session.refresh(csv_tx)
        db_session.refresh(on_chain_tx)

        assert csv_tx.is_duplicate is True
        assert on_chain_tx.is_duplicate is False
        assert report.exact_matches == 1


class TestReportCounts:
    """Tests for deduplication report accuracy."""

    def test_dedup_report_counts(self, db_session: Session):
        """Verify report has correct counts."""
        # 3 unique transactions
        create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )
        create_transaction(
            db_session,
            source_platform="COINBASE",
            timestamp_utc=datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )
        # 1 unique
        create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="ETH",
            base_amount=Decimal("1.0"),
            tx_hash="0xdef456",
        )

        engine = DeduplicationEngine(db_session, 1)
        report = engine.deduplicate_all()

        assert report.total_checked == 3
        assert report.exact_matches == 1
        assert report.heuristic_matches == 0
        assert report.kept_count == 2
        assert report.removed_count == 1


class TestAlreadyDuplicate:
    """Tests for handling already-marked duplicates."""

    def test_already_duplicate_skipped(self, db_session: Session):
        """Transactions with is_duplicate=True should be skipped."""
        # Already marked duplicate - should be ignored
        create_transaction(
            db_session,
            source_platform="COINBASE",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
            is_duplicate=True,
        )

        # New on-chain transaction - should not be marked duplicate
        on_chain_tx = create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 1, 10, 5, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )

        engine = DeduplicationEngine(db_session, 1)
        report = engine.deduplicate_all()

        db_session.refresh(on_chain_tx)

        # The on-chain should be kept, but the duplicate was already marked
        # So exact_matches should be 0 since we don't process already-duplicate txs
        assert on_chain_tx.is_duplicate is False


class TestMultipleDuplicates:
    """Tests for multiple duplicates of the same hash."""

    def test_multiple_duplicates_same_hash(self, db_session: Session):
        """3+ transactions with same hash - only one should be kept."""
        # First: COINBASE
        coinbase_tx = create_transaction(
            db_session,
            source_platform="COINBASE",
            timestamp_utc=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )

        # Second: CRYPTO_COM (lower priority than COINBASE)
        crypto_com_tx = create_transaction(
            db_session,
            source_platform="CRYPTO_COM",
            timestamp_utc=datetime(2024, 1, 1, 10, 1, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )

        # Third: ON_CHAIN (highest priority)
        on_chain_tx = create_transaction(
            db_session,
            source_platform="ON_CHAIN",
            timestamp_utc=datetime(2024, 1, 1, 10, 2, 0, tzinfo=timezone.utc),
            base_coin="BTC",
            base_amount=Decimal("0.01"),
            tx_hash="0xabc123",
        )

        engine = DeduplicationEngine(db_session, 1)
        report = engine.deduplicate_all()

        db_session.refresh(coinbase_tx)
        db_session.refresh(crypto_com_tx)
        db_session.refresh(on_chain_tx)

        # ON_CHAIN should be kept
        assert on_chain_tx.is_duplicate is False
        # Others should be marked duplicate
        assert coinbase_tx.is_duplicate is True
        assert crypto_com_tx.is_duplicate is True

        assert report.exact_matches == 1
        assert report.kept_count == 1
        assert report.removed_count == 2


class TestNormalizeTxHash:
    """Unit tests for normalize_tx_hash method."""

    def test_normalize_tx_hash_static(self):
        """Test the static normalize_tx_hash method."""
        # No suffix
        assert DeduplicationEngine.normalize_tx_hash("0xabc123") == "0xabc123"

        # With MEXC suffix
        assert (
            DeduplicationEngine.normalize_tx_hash("O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM:010")
            == "O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM"
        )

        # Multiple digits
        assert DeduplicationEngine.normalize_tx_hash("hash:123") == "hash"

        # No trailing digits (should not match)
        assert DeduplicationEngine.normalize_tx_hash("hash:abc") == "hash:abc"

        # Empty suffix
        assert DeduplicationEngine.normalize_tx_hash("hash:") == "hash:"
