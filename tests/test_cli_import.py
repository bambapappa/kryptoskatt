"""Tests for CLI import and fetch commands."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from kryptoskatt.cli import app
from kryptoskatt.schemas import TransactionCreate


@pytest.fixture
def runner():
    """Create a Typer CLI runner."""
    return CliRunner()


class TestImportCommand:
    """Tests for the import command."""

    def test_import_coinbase_file(self, runner, coinbase_csv, tmp_path):
        """Test importing a Coinbase CSV file."""
        # Patch get_session to use in-memory SQLite
        with patch("kryptoskatt.cli.import_cmd.get_session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db

            result = runner.invoke(
                app,
                ["import", "--file", str(coinbase_csv), "--platform", "coinbase"],
            )

            # Should succeed
            assert result.exit_code == 0
            assert "Imported" in result.stdout or "transactions" in result.stdout.lower()

    def test_import_dry_run(self, runner, coinbase_csv):
        """Test import with dry-run flag shows preview but doesn't save."""
        with patch("kryptoskatt.cli.import_cmd.get_session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db

            result = runner.invoke(
                app,
                [
                    "import",
                    "--file",
                    str(coinbase_csv),
                    "--platform",
                    "coinbase",
                    "--dry-run",
                ],
            )

            # Should show preview
            assert result.exit_code == 0
            assert "dry-run" in result.stdout.lower() or "preview" in result.stdout.lower()
            # Should NOT have called commit
            mock_db.commit.assert_not_called()

    def test_import_auto_detect_coinbase(self, runner, coinbase_csv):
        """Test auto-detection of Coinbase platform from file content."""
        with patch("kryptoskatt.cli.import_cmd.get_session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db

            # Don't specify --platform, should auto-detect
            result = runner.invoke(app, ["import", "--file", str(coinbase_csv)])

            # Should succeed and auto-detect
            assert result.exit_code == 0
            # Auto-detection should work without explicit platform

    def test_import_crypto_com(self, runner, crypto_com_csv):
        """Test importing a Crypto.com CSV file."""
        with patch("kryptoskatt.cli.import_cmd.get_session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db

            result = runner.invoke(
                app,
                ["import", "--file", str(crypto_com_csv), "--platform", "crypto_com"],
            )

            assert result.exit_code == 0

    def test_import_mexc(self, runner, mexc_deposit_tsv):
        """Test importing a MEXC TSV file."""
        with patch("kryptoskatt.cli.import_cmd.get_session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value = mock_db

            result = runner.invoke(
                app,
                ["import", "--file", str(mexc_deposit_tsv), "--platform", "mexc"],
            )

            assert result.exit_code == 0

    def test_import_file_not_found(self, runner):
        """Test import with non-existent file."""
        result = runner.invoke(
            app,
            ["import", "--file", "/nonexistent/file.csv", "--platform", "coinbase"],
        )

        assert result.exit_code != 0

    def test_import_invalid_platform(self, runner, coinbase_csv):
        """Test import with invalid platform."""
        result = runner.invoke(
            app,
            ["import", "--file", str(coinbase_csv), "--platform", "invalid_platform"],
        )

        assert result.exit_code != 0


class TestFetchCommand:
    """Tests for the fetch command."""

    def test_fetch_single_address(self, runner):
        """Test fetching transactions for a single address."""
        with (
            patch("kryptoskatt.cli.fetch_cmd.get_registry_for_user") as mock_get_registry,
            patch("kryptoskatt.cli.fetch_cmd.get_session") as mock_session,
            patch("kryptoskatt.cli.fetch_cmd.get_legacy_user_id") as mock_uid,
        ):
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_uid.return_value = 1
            mock_registry = MagicMock()
            mock_adapter = MagicMock()
            mock_adapter.fetch_transactions.return_value = [
                TransactionCreate(
                    source_platform="ON_CHAIN",
                    timestamp_utc=datetime(2024, 1, 1, tzinfo=UTC),
                    event_type="TRANSFER_IN",
                    base_coin="ETH",
                    base_amount=Decimal("1.0"),
                    tx_hash="0xabc123",
                )
            ]
            mock_registry.get_adapter.return_value = mock_adapter
            mock_get_registry.return_value = mock_registry

            result = runner.invoke(
                app,
                ["fetch", "--address", "0x1234", "--chain", "ethereum"],
            )

            assert result.exit_code == 0

    def test_fetch_uses_user_registry(self, runner):
        """Verify that fetch --address uses get_registry_for_user, not get_registry."""
        with (
            patch("kryptoskatt.cli.fetch_cmd.get_registry_for_user") as mock_get_registry,
            patch("kryptoskatt.cli.fetch_cmd.get_session") as mock_session,
            patch("kryptoskatt.cli.fetch_cmd.get_legacy_user_id") as mock_uid,
        ):
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_uid.return_value = 42
            mock_registry = MagicMock()
            mock_registry.get_adapter.return_value = None  # no adapter → early return
            mock_get_registry.return_value = mock_registry

            runner.invoke(app, ["fetch", "--address", "0xABCD", "--chain", "ethereum"])

            # Must have been called with (session, user_id)
            mock_get_registry.assert_called_once_with(mock_db, 42)

    def test_fetch_all_wallets(self, runner, sample_eth_wallet):
        """Test fetching transactions for all registered wallets."""
        with (
            patch("kryptoskatt.cli.fetch_cmd.get_registry_for_user") as mock_get_registry,
            patch("kryptoskatt.cli.fetch_cmd.get_session") as mock_session,
            patch("kryptoskatt.cli.fetch_cmd.WalletService") as mock_wallet_service,
            patch("kryptoskatt.cli.fetch_cmd.get_legacy_user_id") as mock_uid,
        ):
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_uid.return_value = 1
            mock_registry = MagicMock()
            mock_adapter = MagicMock()
            mock_adapter.fetch_transactions.return_value = []
            mock_registry.get_adapter.return_value = mock_adapter
            mock_get_registry.return_value = mock_registry

            # Mock wallet service to return wallets
            mock_service = MagicMock()
            mock_service.list_wallets.return_value = [sample_eth_wallet]
            mock_wallet_service.return_value = mock_service

            result = runner.invoke(app, ["fetch", "--all"])

            # Should either succeed or warn about no wallets
            assert result.exit_code == 0

    def test_fetch_unsupported_chain(self, runner):
        """Test fetch with unsupported chain shows warning."""
        with (
            patch("kryptoskatt.cli.fetch_cmd.get_registry_for_user") as mock_get_registry,
            patch("kryptoskatt.cli.fetch_cmd.get_session") as mock_session,
            patch("kryptoskatt.cli.fetch_cmd.get_legacy_user_id") as mock_uid,
        ):
            mock_db = MagicMock()
            mock_session.return_value = mock_db
            mock_uid.return_value = 1
            mock_registry = MagicMock()
            mock_registry.get_adapter.return_value = None  # No adapter for this chain
            mock_get_registry.return_value = mock_registry

            result = runner.invoke(
                app,
                ["fetch", "--address", "0x1234", "--chain", "ethereum"],
            )

            # fetch_cmd writes "Warning: No adapter available for chain ethereum. Skipping." to stderr
            # result.output includes both stdout and stderr
            assert result.exit_code == 0
            assert "warning" in result.output.lower() or "no adapter" in result.output.lower()


class TestAutoDetection:
    """Tests for platform auto-detection."""

    def test_detect_coinbase_from_content(self, coinbase_csv):
        """Test Coinbase detection from file content."""
        from kryptoskatt.cli.import_cmd import detect_platform

        # Read first few lines of file
        with open(coinbase_csv) as f:
            lines = [f.readline() for _ in range(5)]

        platform = detect_platform(coinbase_csv, lines)
        assert platform == "coinbase"

    def test_detect_crypto_com_from_content(self, crypto_com_csv):
        """Test Crypto.com detection from file content."""
        from kryptoskatt.cli.import_cmd import detect_platform

        with open(crypto_com_csv) as f:
            lines = [f.readline() for _ in range(5)]

        platform = detect_platform(crypto_com_csv, lines)
        assert platform == "crypto_com"

    def test_detect_mexc_from_content(self, mexc_deposit_tsv):
        """Test MEXC detection from file content."""
        from kryptoskatt.cli.import_cmd import detect_platform

        with open(mexc_deposit_tsv) as f:
            lines = [f.readline() for _ in range(5)]

        platform = detect_platform(mexc_deposit_tsv, lines)
        assert platform == "mexc"


class TestReimportProtection:
    """Re-uploading the same file must not create duplicate rows."""

    @pytest.fixture
    def db_session(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from kryptoskatt.models.base import Base

        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            yield session
        finally:
            session.close()
            Base.metadata.drop_all(engine)

    def test_reimport_same_file_skips_all_rows(self, db_session, coinbase_csv):
        from kryptoskatt.cli.import_cmd import create_import_batch, parse_file, save_transactions
        from kryptoskatt.models.transaction import Transaction
        from tests.conftest import make_test_account

        uid = make_test_account(db_session)
        txs, errors = parse_file(coinbase_csv, "coinbase")
        assert not errors

        batch1 = create_import_batch(db_session, "coinbase", "a.csv", len(txs), 0, user_id=uid)
        saved1 = save_transactions(db_session, txs, batch1, user_id=uid)
        assert saved1 == len(txs)
        assert batch1.duplicate_count == 0

        txs2, _ = parse_file(coinbase_csv, "coinbase")
        batch2 = create_import_batch(db_session, "coinbase", "a.csv", len(txs2), 0, user_id=uid)
        saved2 = save_transactions(db_session, txs2, batch2, user_id=uid)
        assert saved2 == 0
        assert batch2.duplicate_count == len(txs2)

        total = db_session.query(Transaction).filter(Transaction.user_id == uid).count()
        assert total == len(txs)

    def test_identical_rows_within_one_file_are_kept(self, db_session):
        """Two identical fills in the same export are legitimate — both saved."""
        from datetime import UTC, datetime
        from decimal import Decimal

        from kryptoskatt.cli.import_cmd import create_import_batch, save_transactions
        from kryptoskatt.models.transaction import Transaction
        from kryptoskatt.schemas import TransactionCreate
        from tests.conftest import make_test_account

        uid = make_test_account(db_session)
        fill = {
            "source_platform": "binance",
            "timestamp_utc": datetime(2024, 5, 1, 12, 0, 0, tzinfo=UTC),
            "event_type": "BUY",
            "base_coin": "ETH",
            "base_amount": Decimal("0.1"),
            "quote_coin": "SEK",
            "quote_amount": Decimal("3000"),
        }
        txs = [TransactionCreate(**fill), TransactionCreate(**fill)]
        batch = create_import_batch(db_session, "binance", "b.csv", 2, 0, user_id=uid)
        saved = save_transactions(db_session, txs, batch, user_id=uid)
        assert saved == 2
        assert db_session.query(Transaction).filter(Transaction.user_id == uid).count() == 2
