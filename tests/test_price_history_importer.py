"""Tests for PriceHistoryImporter — edge cases not covered by test_price_service.py."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kryptoskatt.models.base import Base
from kryptoskatt.models.price_cache import PriceCache
from kryptoskatt.services.price_history_importer import PriceHistoryImporter

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_VALID_USD_SEK_RATES = {
    date(2024, 1, 1): Decimal("10.5"),
    date(2024, 1, 2): Decimal("10.6"),
    date(2024, 1, 3): Decimal("10.4"),
}


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _write_temp_csv(directory: Path, filename: str, content: str) -> Path:
    p = directory / filename
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    session = _make_session()
    yield session
    session.close()


@pytest.fixture
def importer(db_session):
    return PriceHistoryImporter(db_session)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParseCsv:
    """Unit tests for the _parse_csv helper."""

    def test_empty_file_returns_no_rows(self, importer, tmp_path):
        """An empty CSV file should produce an empty dict (0 rows)."""
        csv_path = tmp_path / "sol-usd-max.csv"
        csv_path.write_text("", encoding="utf-8")

        rows = importer._parse_csv(csv_path)

        assert rows == {}

    def test_header_only_returns_no_rows(self, importer, tmp_path):
        """A CSV with only a header and no data rows should produce 0 rows."""
        csv_path = tmp_path / "sol-usd-max.csv"
        csv_path.write_text("snapped_at,price,market_cap,total_volume\n", encoding="utf-8")

        rows = importer._parse_csv(csv_path)

        assert rows == {}

    def test_valid_coingecko_csv_parsed_correctly(self, importer, tmp_path):
        """A minimal CoinGecko-style CSV is parsed to a {date: Decimal} dict."""
        content = (
            "snapped_at,price,market_cap,total_volume\n"
            "2024-01-01 00:00:00 UTC,100.50,1000000,50000\n"
            "2024-01-02 00:00:00 UTC,102.75,1100000,60000\n"
        )
        csv_path = tmp_path / "sol-usd-max.csv"
        csv_path.write_text(content, encoding="utf-8")

        rows = importer._parse_csv(csv_path)

        assert len(rows) == 2
        assert rows[date(2024, 1, 1)] == Decimal("100.50")
        assert rows[date(2024, 1, 2)] == Decimal("102.75")

    def test_malformed_price_rows_are_skipped(self, importer, tmp_path):
        """Rows with non-numeric price values are silently skipped."""
        content = (
            "snapped_at,price,market_cap,total_volume\n"
            "2024-01-01 00:00:00 UTC,not_a_number,1000000,50000\n"
            "2024-01-02 00:00:00 UTC,102.75,1100000,60000\n"
        )
        csv_path = tmp_path / "sol-usd-max.csv"
        csv_path.write_text(content, encoding="utf-8")

        rows = importer._parse_csv(csv_path)

        # Only the valid row is returned
        assert len(rows) == 1
        assert date(2024, 1, 2) in rows

    def test_zero_and_negative_prices_excluded(self, importer, tmp_path):
        """Rows with zero or negative USD price are excluded (not meaningful)."""
        content = (
            "snapped_at,price,market_cap,total_volume\n"
            "2024-01-01 00:00:00 UTC,0,1000000,50000\n"
            "2024-01-02 00:00:00 UTC,-5.0,1000000,50000\n"
            "2024-01-03 00:00:00 UTC,99.0,1000000,50000\n"
        )
        csv_path = tmp_path / "sol-usd-max.csv"
        csv_path.write_text(content, encoding="utf-8")

        rows = importer._parse_csv(csv_path)

        assert len(rows) == 1
        assert date(2024, 1, 3) in rows


class TestImportDirectory:
    """Integration tests for import_directory."""

    @patch("kryptoskatt.services.price_history_importer.PriceHistoryImporter._fetch_usd_sek_rates")
    def test_empty_directory_returns_error(self, mock_fetch, importer, tmp_path):
        """A directory with no CSV files reports an error and imports nothing."""
        result = importer.import_directory(tmp_path)

        assert result.rows_inserted == 0
        assert len(result.errors) > 0
        # The fetch should never be called when there are no files
        mock_fetch.assert_not_called()

    @patch("kryptoskatt.services.price_history_importer.PriceHistoryImporter._fetch_usd_sek_rates")
    def test_unknown_filename_skipped(self, mock_fetch, importer, tmp_path):
        """A CSV whose filename has no mapping is silently skipped."""
        mock_fetch.return_value = _VALID_USD_SEK_RATES

        content = (
            "snapped_at,price\n"
            "2024-01-01 00:00:00 UTC,100.0\n"
        )
        _write_temp_csv(tmp_path, "completely-unknown-coin-usd-max.csv", content)

        result = importer.import_directory(tmp_path)

        assert result.files_processed == 0
        assert result.rows_inserted == 0

    @patch("kryptoskatt.services.price_history_importer.PriceHistoryImporter._fetch_usd_sek_rates")
    def test_known_coin_inserted(self, mock_fetch, db_session, tmp_path):
        """A recognised CSV file is imported and price rows land in price_cache."""
        mock_fetch.return_value = {date(2024, 1, 1): Decimal("10.5")}

        content = (
            "snapped_at,price,market_cap,total_volume\n"
            "2024-01-01 00:00:00 UTC,100.0,1000000,50000\n"
        )
        _write_temp_csv(tmp_path, "sol-usd-max.csv", content)

        importer = PriceHistoryImporter(db_session)
        result = importer.import_directory(tmp_path)

        assert result.rows_inserted == 1
        assert result.files_processed == 1

        cached = db_session.query(PriceCache).filter_by(coin_id="solana", date=date(2024, 1, 1)).first()
        assert cached is not None
        assert cached.price_sek == Decimal("100.0") * Decimal("10.5")

    @patch("kryptoskatt.services.price_history_importer.PriceHistoryImporter._fetch_usd_sek_rates")
    def test_duplicate_rows_skipped(self, mock_fetch, db_session, tmp_path):
        """Rows already present in price_cache are not inserted again."""
        mock_fetch.return_value = {date(2024, 1, 1): Decimal("10.5")}

        # Pre-populate the cache with the same coin+date
        db_session.add(
            PriceCache(
                coin_id="solana",
                date=date(2024, 1, 1),
                price_sek=Decimal("999.0"),  # different price — still a duplicate key
                source="COINGECKO",
            )
        )
        db_session.commit()

        content = (
            "snapped_at,price,market_cap,total_volume\n"
            "2024-01-01 00:00:00 UTC,100.0,1000000,50000\n"
        )
        _write_temp_csv(tmp_path, "sol-usd-max.csv", content)

        importer = PriceHistoryImporter(db_session)
        result = importer.import_directory(tmp_path)

        assert result.rows_inserted == 0
        assert result.rows_skipped == 1

    @patch("kryptoskatt.services.price_history_importer.PriceHistoryImporter._fetch_usd_sek_rates")
    def test_no_usd_sek_rates_blocks_import(self, mock_fetch, db_session, tmp_path):
        """When Riksbanken returns no rates, nothing is imported and an error is recorded."""
        mock_fetch.return_value = {}  # empty → can't convert

        content = (
            "snapped_at,price,market_cap,total_volume\n"
            "2024-01-01 00:00:00 UTC,100.0,1000000,50000\n"
        )
        _write_temp_csv(tmp_path, "sol-usd-max.csv", content)

        importer = PriceHistoryImporter(db_session)
        result = importer.import_directory(tmp_path)

        assert result.rows_inserted == 0
        assert len(result.errors) > 0
