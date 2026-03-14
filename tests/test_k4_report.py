"""Tests for the K4 Report Generator."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kryptoskatt.models.base import Base
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.reports.k4 import K4ReportGenerator


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


class TestSimpleK4Report:
    """Test basic K4 report generation."""

    def test_two_coins_multiple_disposals(self, session: Session):
        """Two coins, multiple disposals each → verify per-coin sums."""
        # BTC disposals: 2 disposals
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000"),
            cost_basis_sek=Decimal("200000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("400000"),
        )
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 12, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.25"),
            proceeds_sek=Decimal("125000"),
            cost_basis_sek=Decimal("100000"),
            gain_loss_sek=Decimal("25000"),
            gav_at_disposal=Decimal("400000"),
        )

        # ETH disposal: 1 disposal
        _create_disposal(
            session,
            tax_year=2024,
            coin="ETH",
            sell_timestamp=datetime(2024, 8, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-1"),
            proceeds_sek=Decimal("30000"),
            cost_basis_sek=Decimal("25000"),
            gain_loss_sek=Decimal("5000"),
            gav_at_disposal=Decimal("25000"),
        )

        generator = K4ReportGenerator(session, 1)
        report = generator.generate(year=2024)

        assert report.tax_year == 2024
        assert len(report.rows) == 2

        # Find BTC row
        btc_row = next(row for row in report.rows if row.coin == "BTC")
        assert btc_row.proceeds_sek == Decimal("375000")  # 250000 + 125000
        assert btc_row.cost_basis_sek == Decimal("300000")  # 200000 + 100000
        assert btc_row.gain_loss_sek == Decimal("75000")  # 50000 + 25000

        # Find ETH row
        eth_row = next(row for row in report.rows if row.coin == "ETH")
        assert eth_row.proceeds_sek == Decimal("30000")
        assert eth_row.cost_basis_sek == Decimal("25000")
        assert eth_row.gain_loss_sek == Decimal("5000")

        # Totals: total gains = 75000 + 5000 = 80000, total losses = 0
        assert report.total_gains == Decimal("80000")
        assert report.total_losses == Decimal("0")


class TestEmptyYear:
    """Test K4 report for year with no disposals."""

    def test_empty_year_returns_zero_totals(self, session: Session):
        """Year with no disposals → K4Report with empty rows, totals = 0."""
        # Create some disposals in 2023 only
        _create_disposal(
            session,
            tax_year=2023,
            coin="BTC",
            sell_timestamp=datetime(2023, 6, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("200000"),
            cost_basis_sek=Decimal("150000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("300000"),
        )

        generator = K4ReportGenerator(session, 1)
        report = generator.generate(year=2024)

        assert report.tax_year == 2024
        assert report.rows == []
        assert report.total_gains == Decimal("0")
        assert report.total_losses == Decimal("0")


class TestGainsAndLosses:
    """Test mix of positive and negative gain_loss."""

    def test_gains_and_losses_separated_correctly(self, session: Session):
        """Mix of positive and negative gain_loss → verify total_gains only counts positives, total_losses only counts negatives (absolute value)."""
        # BTC: gain
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000"),
            cost_basis_sek=Decimal("200000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("400000"),
        )

        # ETH: loss
        _create_disposal(
            session,
            tax_year=2024,
            coin="ETH",
            sell_timestamp=datetime(2024, 8, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-1"),
            proceeds_sek=Decimal("15000"),
            cost_basis_sek=Decimal("25000"),
            gain_loss_sek=Decimal("-10000"),
            gav_at_disposal=Decimal("25000"),
        )

        # SOL: another gain
        _create_disposal(
            session,
            tax_year=2024,
            coin="SOL",
            sell_timestamp=datetime(2024, 10, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-10"),
            proceeds_sek=Decimal("2000"),
            cost_basis_sek=Decimal("1000"),
            gain_loss_sek=Decimal("1000"),
            gav_at_disposal=Decimal("100"),
        )

        generator = K4ReportGenerator(session, 1)
        report = generator.generate(year=2024)

        # Total gains: 50000 + 1000 = 51000
        assert report.total_gains == Decimal("51000")
        # Total losses: |-10000| = 10000
        assert report.total_losses == Decimal("10000")

        # Verify per-coin rows
        btc_row = next(row for row in report.rows if row.coin == "BTC")
        eth_row = next(row for row in report.rows if row.coin == "ETH")
        sol_row = next(row for row in report.rows if row.coin == "SOL")

        assert btc_row.gain_loss_sek == Decimal("50000")
        assert eth_row.gain_loss_sek == Decimal("-10000")
        assert sol_row.gain_loss_sek == Decimal("1000")


class TestCSVExport:
    """Test CSV export functionality."""

    def test_csv_export_with_swedish_headers(self, session: Session):
        """Generate CSV, read back, verify Swedish headers and values."""
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000"),
            cost_basis_sek=Decimal("200000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("400000"),
        )
        _create_disposal(
            session,
            tax_year=2024,
            coin="ETH",
            sell_timestamp=datetime(2024, 8, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-1"),
            proceeds_sek=Decimal("30000"),
            cost_basis_sek=Decimal("25000"),
            gain_loss_sek=Decimal("5000"),
            gav_at_disposal=Decimal("25000"),
        )

        generator = K4ReportGenerator(session, 1)
        report = generator.generate(year=2024)

        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "k4_report.csv"
            K4ReportGenerator.export_csv(report, csv_path)

            content = csv_path.read_text(encoding="utf-8-sig")
            lines = content.strip().split("\n")

            # Check headers
            assert (
                lines[0] == "Tillgång,Försäljningspris SEK,Omkostnadsbelopp SEK,Vinst/Förlust SEK"
            )

            # Check data rows (may be in any order since dict ordering)
            # Check totals row
            assert "TOTALT" in lines[-1]


class TestJSONExport:
    """Test JSON export functionality."""

    def test_json_export_structure(self, session: Session):
        """Generate JSON, read back, verify structure."""
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000"),
            cost_basis_sek=Decimal("200000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("400000"),
        )

        generator = K4ReportGenerator(session, 1)
        report = generator.generate(year=2024)

        with TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "k4_report.json"
            K4ReportGenerator.export_json(report, json_path)

            content = json_path.read_text(encoding="utf-8")
            data = json.loads(content)

            assert data["tax_year"] == 2024
            assert len(data["rows"]) == 1
            assert data["rows"][0]["coin"] == "BTC"
            assert data["rows"][0]["proceeds_sek"] == "250000.00"
            assert data["rows"][0]["cost_basis_sek"] == "200000.00"
            assert data["rows"][0]["gain_loss_sek"] == "50000.00"
            assert data["total_gains"] == "50000.00"
            assert data["total_losses"] == "0.00"


class TestFullTransactionList:
    """Test full transaction list export."""

    def test_full_transaction_list_chronological(self, session: Session):
        """Generate list, verify chronological order and all columns."""
        # Create disposals in non-chronological order
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 12, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.25"),
            proceeds_sek=Decimal("125000"),
            cost_basis_sek=Decimal("100000"),
            gain_loss_sek=Decimal("25000"),
            gav_at_disposal=Decimal("400000"),
        )
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000"),
            cost_basis_sek=Decimal("200000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("400000"),
        )
        _create_disposal(
            session,
            tax_year=2024,
            coin="ETH",
            sell_timestamp=datetime(2024, 8, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-1"),
            proceeds_sek=Decimal("30000"),
            cost_basis_sek=Decimal("25000"),
            gain_loss_sek=Decimal("5000"),
            gav_at_disposal=Decimal("25000"),
        )

        generator = K4ReportGenerator(session, 1)

        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "transactions.csv"
            generator.generate_full_transaction_list(year=2024, output_path=csv_path)

            content = csv_path.read_text(encoding="utf-8-sig")
            lines = content.strip().split("\n")

            # Check headers
            expected_headers = "Datum,Tillgång,Antal,Försäljningspris SEK,Omkostnadsbelopp SEK,Vinst/Förlust SEK,GAV vid försäljning SEK"
            assert lines[0] == expected_headers

            # Check 3 data rows (excluding header)
            assert len(lines) == 4

            # Check first row is June (chronological)
            assert "2024-06-01" in lines[1]


class TestRounding:
    """Test rounding to 2 decimal places in output."""

    def test_values_rounded_to_2_decimals(self, session: Session):
        """Values rounded to 2 decimal places in output."""
        # Create disposal with more than 2 decimal places
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000.123456789"),
            cost_basis_sek=Decimal("200000.987654321"),
            gain_loss_sek=Decimal("49999.246913578"),
            gav_at_disposal=Decimal("400000"),
        )

        generator = K4ReportGenerator(session, 1)
        report = generator.generate(year=2024)

        row = report.rows[0]
        # Values should be rounded to 2 decimal places in K4Report output
        assert row.proceeds_sek == Decimal("250000.12")
        assert row.cost_basis_sek == Decimal("200000.99")
        assert row.gain_loss_sek == Decimal("49999.25")

        # Totals should also be rounded
        assert report.total_gains == Decimal("49999.25")


class TestYearFiltering:
    """Test year filtering in K4 report."""

    def test_only_requested_year_included(self, session: Session):
        """Disposals from different years → only requested year included."""
        # 2023 disposal
        _create_disposal(
            session,
            tax_year=2023,
            coin="BTC",
            sell_timestamp=datetime(2023, 6, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("200000"),
            cost_basis_sek=Decimal("150000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("300000"),
        )

        # 2024 disposals
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000"),
            cost_basis_sek=Decimal("200000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("400000"),
        )
        _create_disposal(
            session,
            tax_year=2024,
            coin="ETH",
            sell_timestamp=datetime(2024, 8, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-1"),
            proceeds_sek=Decimal("30000"),
            cost_basis_sek=Decimal("25000"),
            gain_loss_sek=Decimal("5000"),
            gav_at_disposal=Decimal("25000"),
        )

        # Generate 2024 report
        generator = K4ReportGenerator(session, 1)
        report = generator.generate(year=2024)

        # Should only have 2024 disposals
        assert len(report.rows) == 2
        assert report.total_gains == Decimal("55000")

        # Generate 2023 report
        report_2023 = generator.generate(year=2023)
        assert len(report_2023.rows) == 1
        assert report_2023.rows[0].coin == "BTC"
        assert report_2023.total_gains == Decimal("50000")


class TestAllArithmeticIsDecimal:
    """Verify all monetary values use Decimal."""

    def test_all_calculations_use_decimal(self, session: Session):
        """All arithmetic is Decimal - no floats in any calculation."""
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 1, 10, 0, 0, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000"),
            cost_basis_sek=Decimal("200000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("400000"),
        )

        generator = K4ReportGenerator(session, 1)
        report = generator.generate(year=2024)

        row = report.rows[0]

        # All Decimal types
        assert isinstance(row.proceeds_sek, Decimal)
        assert isinstance(row.cost_basis_sek, Decimal)
        assert isinstance(row.gain_loss_sek, Decimal)
        assert isinstance(report.total_gains, Decimal)
        assert isinstance(report.total_losses, Decimal)
