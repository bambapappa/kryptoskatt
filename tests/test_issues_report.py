"""Tests for the Flagged Issues Report Generator."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kryptoskatt.models.base import Base
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.transfer_link import TransferLink
from kryptoskatt.reports.issues import FlaggedIssuesGenerator, FlaggedIssuesReport


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


def _create_transaction(
    session: Session,
    timestamp_utc: datetime,
    event_type: str,
    base_coin: str,
    base_amount: Decimal,
    price_sek: Decimal | None = None,
    is_duplicate: bool = False,
    user_id: int = 1,
) -> Transaction:
    """Helper to create a Transaction in the test database."""
    tx = Transaction(
        user_id=user_id,
        source_platform="test",
        timestamp_utc=timestamp_utc,
        event_type=event_type,
        base_coin=base_coin,
        base_amount=base_amount,
        price_sek=price_sek,
        is_duplicate=is_duplicate,
    )
    session.add(tx)
    session.commit()
    return tx


def _create_disposal(
    session: Session,
    tax_year: int,
    coin: str,
    sell_timestamp: datetime,
    sell_amount: Decimal,
    proceeds_sek: Decimal,
    cost_basis_sek: Decimal,
    gain_loss_sek: Decimal,
    gav_at_disposal: Decimal,
    user_id: int = 1,
) -> Disposal:
    """Helper to create a Disposal in the test database."""
    disposal = Disposal(
        user_id=user_id,
        tax_year=tax_year,
        coin=coin,
        sell_timestamp=sell_timestamp,
        sell_amount=sell_amount,
        proceeds_sek=proceeds_sek,
        cost_basis_sek=cost_basis_sek,
        gain_loss_sek=gain_loss_sek,
        gav_at_disposal=gav_at_disposal,
    )
    session.add(disposal)
    session.commit()
    return disposal


def _create_transfer_link(
    session: Session,
    tx_out_id: int,
    tx_in_id: int,
) -> TransferLink:
    """Helper to create a TransferLink in the test database."""
    link = TransferLink(
        tx_out_id=tx_out_id,
        tx_in_id=tx_in_id,
        match_method="MANUAL",
    )
    session.add(link)
    session.commit()
    return link


class TestReportStructure:
    """Test basic report structure."""

    def test_generate_returns_report_structure(self, session: Session):
        """Verify generate returns proper FlaggedIssuesReport structure."""
        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        assert isinstance(report, FlaggedIssuesReport)
        assert report.year == 2024
        assert isinstance(report.issues, list)
        assert report.total_errors == 0
        assert report.total_warnings == 0
        assert report.total_info == 0

    def test_empty_when_no_issues(self, session: Session):
        """Report should be empty when there are no issues."""
        # Create a normal transaction with price
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("0.1"),
            price_sek=Decimal("50000"),
        )

        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        assert len(report.issues) == 0
        assert report.total_errors == 0
        assert report.total_warnings == 0
        assert report.total_info == 0

    def test_filter_by_year(self, session: Session):
        """Test that filtering by year works correctly."""
        # Create transaction in 2024 with missing price
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("0.1"),
            price_sek=None,  # Missing price
        )

        # Create transaction in 2023 with missing price
        _create_transaction(
            session,
            timestamp_utc=datetime(2023, 6, 15, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            base_coin="ETH",
            base_amount=Decimal("1.0"),
            price_sek=None,  # Missing price
        )

        # Filter by 2024 should only return 2024 issues
        generator = FlaggedIssuesGenerator(session, 1)
        report_2024 = generator.generate(year=2024)

        assert len(report_2024.issues) == 1
        assert report_2024.issues[0].coin == "BTC"

        # Filter by 2023 should only return 2023 issues
        report_2023 = generator.generate(year=2023)

        assert len(report_2023.issues) == 1
        assert report_2023.issues[0].coin == "ETH"

        # No filter should return both
        report_all = generator.generate(year=None)

        assert len(report_all.issues) == 2


class TestMissingPrices:
    """Test detection of missing prices."""

    def test_detects_missing_prices(self, session: Session):
        """Transactions with missing price_sek should be flagged as ERROR."""
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("0.1"),
            price_sek=None,  # Missing price
        )

        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        assert len(report.issues) == 1
        issue = report.issues[0]
        assert issue.severity == "ERROR"
        assert issue.category == "missing_price"
        assert issue.coin == "BTC"
        assert report.total_errors == 1

    def test_transaction_with_price_not_flagged(self, session: Session):
        """Transactions with price_sek should NOT be flagged."""
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("0.1"),
            price_sek=Decimal("50000"),
        )

        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        # Should not flag missing price for transactions with price
        missing_price_issues = [i for i in report.issues if i.category == "missing_price"]
        assert len(missing_price_issues) == 0


class TestUnknownCostBasis:
    """Test detection of unknown cost basis."""

    def test_detects_unknown_cost_basis(self, session: Session):
        """Disposals with zero cost_basis_sek should be flagged as ERROR."""
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.1"),
            proceeds_sek=Decimal("50000"),
            cost_basis_sek=Decimal("0"),  # Unknown cost basis
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("500000"),
        )

        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        assert len(report.issues) == 1
        issue = report.issues[0]
        assert issue.severity == "ERROR"
        assert issue.category == "unknown_cost_basis"
        assert issue.coin == "BTC"
        assert report.total_errors == 1


class TestUnmatchedTransfers:
    """Test detection of unmatched transfers."""

    def test_detects_unmatched_transfers(self, session: Session):
        """TRANSFER_OUT without TransferLink should be flagged as WARNING."""
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            event_type="TRANSFER_OUT",
            base_coin="BTC",
            base_amount=Decimal("-0.1"),
            price_sek=Decimal("50000"),
        )

        # Don't create a TransferLink - this is an unmatched transfer

        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        assert len(report.issues) == 1
        issue = report.issues[0]
        assert issue.severity == "WARNING"
        assert issue.category == "unmatched_transfer"
        assert issue.coin == "BTC"
        assert report.total_warnings == 1

    def test_matched_transfer_not_flagged(self, session: Session):
        """TRANSFER_OUT with TransferLink should NOT be flagged."""
        tx_out = _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            event_type="TRANSFER_OUT",
            base_coin="BTC",
            base_amount=Decimal("-0.1"),
            price_sek=Decimal("50000"),
        )

        tx_in = _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC),
            event_type="TRANSFER_IN",
            base_coin="BTC",
            base_amount=Decimal("0.1"),
            price_sek=Decimal("50000"),
        )

        # Create a TransferLink
        _create_transfer_link(session, tx_out.id, tx_in.id)

        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        # Should not flag unmatched transfer
        unmatched_issues = [i for i in report.issues if i.category == "unmatched_transfer"]
        assert len(unmatched_issues) == 0


class TestHeuristicDedup:
    """Test detection of heuristic duplicates."""

    def test_detects_heuristic_dedup(self, session: Session):
        """Transactions with is_duplicate=True should be flagged as INFO."""
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("0.1"),
            price_sek=Decimal("50000"),
            is_duplicate=True,
        )

        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        assert len(report.issues) == 1
        issue = report.issues[0]
        assert issue.severity == "INFO"
        assert issue.category == "heuristic_dedup"
        assert issue.coin == "BTC"
        assert report.total_info == 1


class TestSellExceedsHold:
    """Test detection of sells exceeding holdings."""

    def test_detects_sell_exceeds_hold(self, session: Session):
        """Disposals where cost_basis > proceeds * 10 should be flagged as WARNING."""
        # High cost basis relative to proceeds indicates oversell
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.1"),
            proceeds_sek=Decimal("10000"),
            cost_basis_sek=Decimal("200000"),  # Much higher than proceeds
            gain_loss_sek=Decimal("-190000"),
            gav_at_disposal=Decimal("100000"),
        )

        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        assert len(report.issues) == 1
        issue = report.issues[0]
        assert issue.severity == "WARNING"
        assert issue.category == "sell_exceeds_hold"
        assert issue.coin == "BTC"
        assert report.total_warnings == 1

    def test_normal_disposal_not_flagged(self, session: Session):
        """Normal disposals should NOT be flagged."""
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.1"),
            proceeds_sek=Decimal("50000"),
            cost_basis_sek=Decimal("40000"),
            gain_loss_sek=Decimal("10000"),
            gav_at_disposal=Decimal("400000"),
        )

        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        # Should not flag sell exceeds hold
        oversell_issues = [i for i in report.issues if i.category == "sell_exceeds_hold"]
        assert len(oversell_issues) == 0


class TestMultipleIssues:
    """Test detection of multiple issue types."""

    def test_multiple_issues_all_captured(self, session: Session):
        """All issue types should be captured when they exist."""
        # Missing price transaction
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("0.1"),
            price_sek=None,
        )

        # Unknown cost basis disposal
        _create_disposal(
            session,
            tax_year=2024,
            coin="ETH",
            sell_timestamp=datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-1.0"),
            proceeds_sek=Decimal("30000"),
            cost_basis_sek=Decimal("0"),
            gain_loss_sek=Decimal("30000"),
            gav_at_disposal=Decimal("30000"),
        )

        # Unmatched transfer
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 7, 1, 10, 0, 0, tzinfo=UTC),
            event_type="TRANSFER_OUT",
            base_coin="SOL",
            base_amount=Decimal("-10"),
            price_sek=Decimal("1000"),
        )

        # Duplicate transaction
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 8, 1, 10, 0, 0, tzinfo=UTC),
            event_type="BUY",
            base_coin="DOGE",
            base_amount=Decimal("1000"),
            price_sek=Decimal("100"),
            is_duplicate=True,
        )

        generator = FlaggedIssuesGenerator(session, 1)
        report = generator.generate(year=2024)

        assert len(report.issues) == 4
        assert report.total_errors == 2  # missing_price + unknown_cost_basis
        assert report.total_warnings == 1  # unmatched_transfer
        assert report.total_info == 1  # heuristic_dedup

        categories = {issue.category for issue in report.issues}
        assert "missing_price" in categories
        assert "unknown_cost_basis" in categories
        assert "unmatched_transfer" in categories
        assert "heuristic_dedup" in categories
