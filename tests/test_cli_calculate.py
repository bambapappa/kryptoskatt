"""Tests for CLI calculate and report commands."""

import json
import unittest.mock
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from kryptoskatt.cli import app
from kryptoskatt.models.base import Base
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.wallet import Wallet


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
    *,
    timestamp_utc: datetime,
    event_type: str,
    base_coin: str,
    base_amount: Decimal,
    price_sek: Decimal,
    source_platform: str = "COINBASE",
    tx_hash: str | None = None,
    to_address: str | None = None,
    from_address: str | None = None,
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
        price_sek=price_sek,
        tx_hash=tx_hash,
        to_address=to_address,
        from_address=from_address,
        is_duplicate=False,
    )
    session.add(tx)
    session.flush()
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


def _create_wallet(
    session: Session,
    address: str,
    chain: str,
    is_mine: bool = True,
    label: str | None = None,
    user_id: int = 1,
) -> Wallet:
    """Helper to create a Wallet in the test database."""
    wallet = Wallet(
        user_id=user_id,
        address=address,
        chain=chain,
        is_mine=is_mine,
        label=label,
    )
    session.add(wallet)
    session.commit()
    return wallet


class TestCalculateCommand:
    """Tests for the kryptoskatt calculate command."""

    def test_calculate_basic(self, session: Session):
        """Insert transactions, run calculate, verify success output contains Done!."""
        # Create a simple buy transaction
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 1, 15, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("1.0"),
            price_sek=Decimal("500000"),
        )

        # Mock get_session to return our test session
        with unittest.mock.patch("kryptoskatt.cli.calculate_cmd.get_session", return_value=session):
            from typer.testing import CliRunner

            runner = CliRunner()
            result = runner.invoke(app, ["calculate", "2024"])

            assert result.exit_code == 0
            assert "Done!" in result.stdout

    def test_calculate_shows_progress(self, session: Session):
        """Verify output contains step progress messages."""
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 1, 15, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("1.0"),
            price_sek=Decimal("500000"),
        )

        with unittest.mock.patch("kryptoskatt.cli.calculate_cmd.get_session", return_value=session):
            from typer.testing import CliRunner

            runner = CliRunner()
            result = runner.invoke(app, ["calculate", "2024"])

            assert result.exit_code == 0
            assert "Step 1/4" in result.stdout
            assert "Step 2/4" in result.stdout
            assert "Step 4/4" in result.stdout

    def test_calculate_shows_warnings(self, session: Session):
        """Insert transactions with missing price_sek (Decimal(0)), verify warnings shown."""
        # Create a sell transaction with missing price (price_sek = 0)
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 1, 15, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("1.0"),
            price_sek=Decimal("500000"),
        )
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 15, tzinfo=UTC),
            event_type="SELL",
            base_coin="BTC",
            base_amount=Decimal("0.5"),
            price_sek=Decimal("0"),  # Unknown price - should generate warning
        )

        with unittest.mock.patch("kryptoskatt.cli.calculate_cmd.get_session", return_value=session):
            from typer.testing import CliRunner

            runner = CliRunner()
            result = runner.invoke(app, ["calculate", "2024"])

            assert result.exit_code == 0
            assert "⚠" in result.stdout
            assert "Unknown price" in result.stdout


class TestReportCommand:
    """Tests for the kryptoskatt report command."""

    def test_report_csv_creates_file(self, session: Session):
        """Run calculate first, then report --format csv, verify CSV file created."""
        # Create transactions and disposals
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 1, 15, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("1.0"),
            price_sek=Decimal("500000"),
        )
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 15, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000"),
            cost_basis_sek=Decimal("200000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("400000"),
        )

        with TemporaryDirectory() as tmpdir, unittest.mock.patch(
            "kryptoskatt.cli.report_cmd.get_session", return_value=session
        ):
            from typer.testing import CliRunner

            runner = CliRunner()
            result = runner.invoke(
                app, ["report", "2024", "--format", "csv", "--output-dir", tmpdir]
            )

            assert result.exit_code == 0
            csv_path = Path(tmpdir) / "k4_2024.csv"
            assert csv_path.exists()
            content = csv_path.read_text(encoding="utf-8-sig")
            assert "BTC" in content
            assert "250000" in content

    def test_report_json_creates_file(self, session: Session):
        """Run report with --format json, verify JSON file created."""
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 15, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000"),
            cost_basis_sek=Decimal("200000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("400000"),
        )

        with TemporaryDirectory() as tmpdir, unittest.mock.patch(
            "kryptoskatt.cli.report_cmd.get_session", return_value=session
        ):
            from typer.testing import CliRunner

            runner = CliRunner()
            result = runner.invoke(
                app, ["report", "2024", "--format", "json", "--output-dir", tmpdir]
            )

            assert result.exit_code == 0
            json_path = Path(tmpdir) / "k4_2024.json"
            assert json_path.exists()
            data = json.loads(json_path.read_text(encoding="utf-8"))
            assert data["tax_year"] == 2024
            assert len(data["rows"]) == 1

    def test_report_full_creates_transaction_list(self, session: Session):
        """Run with --full, verify transactions CSV also created."""
        _create_disposal(
            session,
            tax_year=2024,
            coin="BTC",
            sell_timestamp=datetime(2024, 6, 15, tzinfo=UTC),
            sell_amount=Decimal("-0.5"),
            proceeds_sek=Decimal("250000"),
            cost_basis_sek=Decimal("200000"),
            gain_loss_sek=Decimal("50000"),
            gav_at_disposal=Decimal("400000"),
        )

        with TemporaryDirectory() as tmpdir, unittest.mock.patch(
            "kryptoskatt.cli.report_cmd.get_session", return_value=session
        ):
            from typer.testing import CliRunner

            runner = CliRunner()
            result = runner.invoke(
                app, ["report", "2024", "--format", "csv", "--full", "--output-dir", tmpdir]
            )

            assert result.exit_code == 0
            tx_path = Path(tmpdir) / "transactions_2024.csv"
            assert tx_path.exists()
            content = tx_path.read_text(encoding="utf-8-sig")
            assert "Datum" in content
            assert "BTC" in content

    def test_report_no_disposals_shows_warning(self, session: Session):
        """Call report for year with no disposals, verify warning message."""
        # No disposals in database

        with TemporaryDirectory() as tmpdir, unittest.mock.patch(
            "kryptoskatt.cli.report_cmd.get_session", return_value=session
        ):
            from typer.testing import CliRunner

            runner = CliRunner()
            result = runner.invoke(
                app, ["report", "2024", "--format", "csv", "--output-dir", tmpdir]
            )

            assert result.exit_code == 0
            assert "No disposals found" in result.stdout
            assert "Run 'kryptoskatt calculate" in result.stdout


class TestEndToEnd:
    """End-to-end tests for calculate and report."""

    def test_calculate_and_report_e2e(self, session: Session):
        """Full end-to-end: insert transactions -> calculate -> report, verify file contents."""
        # Insert transactions
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 1, 15, tzinfo=UTC),
            event_type="BUY",
            base_coin="BTC",
            base_amount=Decimal("1.0"),
            price_sek=Decimal("500000"),
        )
        _create_transaction(
            session,
            timestamp_utc=datetime(2024, 6, 15, tzinfo=UTC),
            event_type="SELL",
            base_coin="BTC",
            base_amount=Decimal("0.5"),
            price_sek=Decimal("600000"),
        )

        # Mock get_session for calculate
        with unittest.mock.patch("kryptoskatt.cli.calculate_cmd.get_session", return_value=session):
            from typer.testing import CliRunner

            runner = CliRunner()
            # Run calculate
            calc_result = runner.invoke(app, ["calculate", "2024"])
            assert calc_result.exit_code == 0

        # Verify disposal was created
        from kryptoskatt.models.disposal import Disposal

        disposals = session.query(Disposal).filter(Disposal.tax_year == 2024).all()
        assert len(disposals) == 1
        assert disposals[0].gain_loss_sek == Decimal("50000")  # (0.5 * 600000) - (0.5 * 500000)

        with TemporaryDirectory() as tmpdir:
            # Mock get_session for report
            with unittest.mock.patch(
                "kryptoskatt.cli.report_cmd.get_session", return_value=session
            ):
                # Run report
                report_result = runner.invoke(
                    app, ["report", "2024", "--format", "csv", "--output-dir", tmpdir]
                )
                assert report_result.exit_code == 0

                # Verify file
                csv_path = Path(tmpdir) / "k4_2024.csv"
                assert csv_path.exists()
                content = csv_path.read_text(encoding="utf-8-sig")
                assert "BTC" in content
                assert "50000" in content  # gain


class TestReportSruCommand:
    """Tests for the kryptoskatt report --format sru command."""

    def _seed_disposal(self, session):
        from kryptoskatt.models.disposal import Disposal

        session.add(Disposal(
            user_id=1, tax_year=2024, coin="BTC",
            sell_amount=Decimal("-0.1"),
            proceeds_sek=Decimal("30000"), cost_basis_sek=Decimal("20000"),
            gain_loss_sek=Decimal("10000"),
            sell_timestamp=datetime(2024, 6, 1, tzinfo=UTC),
            gav_at_disposal=Decimal("0"),
        ))
        session.commit()

    def test_report_sru_writes_files(self, session: Session):
        self._seed_disposal(session)
        from typer.testing import CliRunner

        runner = CliRunner()
        with TemporaryDirectory() as tmpdir:
            with unittest.mock.patch(
                "kryptoskatt.cli.report_cmd.get_session", return_value=session
            ):
                result = runner.invoke(app, [
                    "report", "2024", "--format", "sru", "--output-dir", tmpdir,
                    "--personnummer", "199001011234", "--namn", "Test Testsson",
                ])
            assert result.exit_code == 0, result.stdout
            info = Path(tmpdir) / "INFO.SRU"
            blank = Path(tmpdir) / "BLANKETTER.SRU"
            assert info.exists() and blank.exists()
            content = blank.read_text(encoding="iso-8859-1")
            assert "#BLANKETT K4-2024P4" in content
            assert "#UPPGIFT 3411 BTC" in content

    def test_report_sru_requires_identity(self, session: Session):
        self._seed_disposal(session)
        from typer.testing import CliRunner

        runner = CliRunner()
        with TemporaryDirectory() as tmpdir:
            with unittest.mock.patch(
                "kryptoskatt.cli.report_cmd.get_session", return_value=session
            ):
                result = runner.invoke(app, [
                    "report", "2024", "--format", "sru", "--output-dir", tmpdir,
                ])
            assert result.exit_code == 1
