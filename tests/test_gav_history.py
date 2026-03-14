"""Tests for the GAV History Report."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kryptoskatt.models.base import Base
from kryptoskatt.models.gav_ledger import GavLedger
from kryptoskatt.reports.gav_history import GavHistoryReport


@pytest.fixture
def session():
    """Create an in-memory SQLite session for testing."""
    from tests.conftest import make_test_account

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    make_test_account(sess)
    yield sess
    sess.close()


def _create_gav_ledger(
    session: Session,
    coin: str,
    timestamp: datetime,
    event_type: str,
    amount_change: Decimal,
    total_amount: Decimal,
    total_cost_sek: Decimal,
    gav_per_unit_sek: Decimal,
    user_id: int = 1,
) -> GavLedger:
    """Helper to create a GavLedger entry in the test database."""
    entry = GavLedger(
        user_id=user_id,
        coin=coin,
        timestamp=timestamp,
        event_type=event_type,
        amount_change=amount_change,
        total_amount=total_amount,
        total_cost_sek=total_cost_sek,
        gav_per_unit_sek=gav_per_unit_sek,
    )
    session.add(entry)
    session.commit()
    return entry


class TestGenerateAllCoins:
    """Test generating report without filters."""

    def test_generate_all_coins(self, session: Session):
        """No filters → returns all GAV ledger entries."""
        _create_gav_ledger(
            session,
            coin="BTC",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("1"),
            total_amount=Decimal("1"),
            total_cost_sek=Decimal("400000"),
            gav_per_unit_sek=Decimal("400000"),
        )
        _create_gav_ledger(
            session,
            coin="ETH",
            timestamp=datetime(2024, 2, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("10"),
            total_amount=Decimal("10"),
            total_cost_sek=Decimal("200000"),
            gav_per_unit_sek=Decimal("20000"),
        )

        generator = GavHistoryReport(session, 1)
        snapshots = generator.generate()

        assert len(snapshots) == 2
        coins = [s.coin for s in snapshots]
        assert "BTC" in coins
        assert "ETH" in coins


class TestFilterByCoin:
    """Test filtering by coin."""

    def test_generate_filter_by_coin(self, session: Session):
        """Filter by coin → returns only entries for that coin."""
        _create_gav_ledger(
            session,
            coin="BTC",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("1"),
            total_amount=Decimal("1"),
            total_cost_sek=Decimal("400000"),
            gav_per_unit_sek=Decimal("400000"),
        )
        _create_gav_ledger(
            session,
            coin="ETH",
            timestamp=datetime(2024, 2, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("10"),
            total_amount=Decimal("10"),
            total_cost_sek=Decimal("200000"),
            gav_per_unit_sek=Decimal("20000"),
        )

        generator = GavHistoryReport(session, 1)
        snapshots = generator.generate(coin="ETH")

        assert len(snapshots) == 1
        assert snapshots[0].coin == "ETH"


class TestFilterByYear:
    """Test filtering by year."""

    def test_generate_filter_by_year(self, session: Session):
        """Filter by year → returns only entries within that year."""
        _create_gav_ledger(
            session,
            coin="BTC",
            timestamp=datetime(2023, 6, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("1"),
            total_amount=Decimal("1"),
            total_cost_sek=Decimal("300000"),
            gav_per_unit_sek=Decimal("300000"),
        )
        _create_gav_ledger(
            session,
            coin="BTC",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("1"),
            total_amount=Decimal("1"),
            total_cost_sek=Decimal("400000"),
            gav_per_unit_sek=Decimal("400000"),
        )
        _create_gav_ledger(
            session,
            coin="ETH",
            timestamp=datetime(2024, 2, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("10"),
            total_amount=Decimal("10"),
            total_cost_sek=Decimal("200000"),
            gav_per_unit_sek=Decimal("20000"),
        )

        generator = GavHistoryReport(session, 1)
        snapshots = generator.generate(year=2024)

        assert len(snapshots) == 2
        for s in snapshots:
            assert s.timestamp.year == 2024


class TestFilterByCoinAndYear:
    """Test filtering by both coin and year."""

    def test_generate_filter_by_coin_and_year(self, session: Session):
        """Filter by coin and year → returns only matching entries."""
        _create_gav_ledger(
            session,
            coin="BTC",
            timestamp=datetime(2023, 6, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("1"),
            total_amount=Decimal("1"),
            total_cost_sek=Decimal("300000"),
            gav_per_unit_sek=Decimal("300000"),
        )
        _create_gav_ledger(
            session,
            coin="BTC",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("1"),
            total_amount=Decimal("1"),
            total_cost_sek=Decimal("400000"),
            gav_per_unit_sek=Decimal("400000"),
        )
        _create_gav_ledger(
            session,
            coin="ETH",
            timestamp=datetime(2024, 2, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("10"),
            total_amount=Decimal("10"),
            total_cost_sek=Decimal("200000"),
            gav_per_unit_sek=Decimal("20000"),
        )

        generator = GavHistoryReport(session, 1)
        snapshots = generator.generate(coin="BTC", year=2024)

        assert len(snapshots) == 1
        assert snapshots[0].coin == "BTC"
        assert snapshots[0].timestamp.year == 2024


class TestEmptyResult:
    """Test empty result scenarios."""

    def test_generate_empty(self, session: Session):
        """No matching entries → returns empty list."""
        # Create entries for a different year
        _create_gav_ledger(
            session,
            coin="BTC",
            timestamp=datetime(2023, 1, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("1"),
            total_amount=Decimal("1"),
            total_cost_sek=Decimal("400000"),
            gav_per_unit_sek=Decimal("400000"),
        )

        generator = GavHistoryReport(session, 1)
        snapshots = generator.generate(year=2024)

        assert snapshots == []


class TestSnapshotFields:
    """Test that snapshots have correct fields."""

    def test_snapshots_have_correct_fields(self, session: Session):
        """Verify all required fields are present in snapshots."""
        _create_gav_ledger(
            session,
            coin="BTC",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("1"),
            total_amount=Decimal("1"),
            total_cost_sek=Decimal("400000"),
            gav_per_unit_sek=Decimal("400000"),
        )

        generator = GavHistoryReport(session, 1)
        snapshots = generator.generate()

        assert len(snapshots) == 1
        s = snapshots[0]

        assert s.coin == "BTC"
        # SQLite may strip timezone info, so compare date components instead
        assert s.timestamp.year == 2024
        assert s.timestamp.month == 1
        assert s.timestamp.day == 1
        assert s.event_type == "BUY"
        assert s.amount_change == Decimal("1")
        assert s.total_units == Decimal("1")
        assert s.total_cost == Decimal("400000")
        assert s.gav_per_unit == Decimal("400000")


class TestOrdering:
    """Test result ordering."""

    def test_snapshots_ordered_by_coin_and_timestamp(self, session: Session):
        """Results ordered by coin, then timestamp."""
        # Create entries in random order
        _create_gav_ledger(
            session,
            coin="ETH",
            timestamp=datetime(2024, 3, 1, 10, 0, 0, tzinfo=UTC),
            event_type="SELL",
            amount_change=Decimal("-5"),
            total_amount=Decimal("5"),
            total_cost_sek=Decimal("100000"),
            gav_per_unit_sek=Decimal("20000"),
        )
        _create_gav_ledger(
            session,
            coin="BTC",
            timestamp=datetime(2024, 2, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("1"),
            total_amount=Decimal("1"),
            total_cost_sek=Decimal("400000"),
            gav_per_unit_sek=Decimal("400000"),
        )
        _create_gav_ledger(
            session,
            coin="ETH",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("10"),
            total_amount=Decimal("10"),
            total_cost_sek=Decimal("200000"),
            gav_per_unit_sek=Decimal("20000"),
        )

        generator = GavHistoryReport(session, 1)
        snapshots = generator.generate(year=2024)

        assert len(snapshots) == 3
        # Should be ordered: BTC first (2024-02), then ETH (2024-01), then ETH (2024-03)
        assert snapshots[0].coin == "BTC"
        assert snapshots[1].coin == "ETH"
        assert snapshots[1].timestamp.month == 1
        assert snapshots[2].coin == "ETH"
        assert snapshots[2].timestamp.month == 3


class TestDecimalTypes:
    """Test that all monetary values are Decimal."""

    def test_all_monetary_values_are_decimal(self, session: Session):
        """All monetary values are Decimal instances."""
        _create_gav_ledger(
            session,
            coin="BTC",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            amount_change=Decimal("1"),
            total_amount=Decimal("1"),
            total_cost_sek=Decimal("400000"),
            gav_per_unit_sek=Decimal("400000"),
        )

        generator = GavHistoryReport(session, 1)
        snapshots = generator.generate()

        s = snapshots[0]
        assert isinstance(s.amount_change, Decimal)
        assert isinstance(s.total_units, Decimal)
        assert isinstance(s.total_cost, Decimal)
        assert isinstance(s.gav_per_unit, Decimal)
