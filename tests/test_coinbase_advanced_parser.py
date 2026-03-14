"""Tests for Coinbase Advanced Trade CSV parser."""

from pathlib import Path

import pytest

from kryptoskatt.cli.import_cmd import detect_platform
from kryptoskatt.parsers.coinbase_advanced import CoinbaseAdvancedParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_csv() -> Path:
    return FIXTURES_DIR / "coinbase_advanced_sample.csv"


class TestCoinbaseAdvancedParser:
    """Test suite for CoinbaseAdvancedParser."""

    def test_parse_buy(self, sample_csv: Path) -> None:
        """BUY row produces a BUY transaction for the correct coin."""
        parser = CoinbaseAdvancedParser()
        result = parser.parse(sample_csv)

        buy_txs = [tx for tx in result.transactions if tx.event_type == "BUY"]
        assert len(buy_txs) >= 1

        buy = buy_txs[0]
        assert buy.base_coin == "BTC"
        assert buy.event_type == "BUY"
        assert buy.base_amount > 0

    def test_parse_sell(self, sample_csv: Path) -> None:
        """SELL row produces a SELL transaction."""
        parser = CoinbaseAdvancedParser()
        result = parser.parse(sample_csv)

        sell_txs = [tx for tx in result.transactions if tx.event_type == "SELL"]
        assert len(sell_txs) >= 1

        sell = sell_txs[0]
        assert sell.event_type == "SELL"
        assert sell.base_amount > 0

    def test_fee_creates_separate_transaction(self, sample_csv: Path) -> None:
        """Non-zero fee produces a separate FEE transaction."""
        parser = CoinbaseAdvancedParser()
        result = parser.parse(sample_csv)

        fee_txs = [tx for tx in result.transactions if tx.event_type == "FEE"]
        # Both rows in the fixture have non-zero fees
        assert len(fee_txs) == 2

        for fee_tx in fee_txs:
            assert fee_tx.base_amount > 0

    def test_product_parsing(self, sample_csv: Path) -> None:
        """Product 'BTC-SEK' is parsed into base_coin='BTC', quote_coin='SEK'."""
        parser = CoinbaseAdvancedParser()
        result = parser.parse(sample_csv)

        buy_txs = [tx for tx in result.transactions if tx.event_type == "BUY"]
        assert buy_txs[0].base_coin == "BTC"
        assert buy_txs[0].quote_coin == "SEK"

    def test_auto_detect(self, sample_csv: Path) -> None:
        """detect_platform returns 'coinbase_advanced' for the fixture file."""
        with open(sample_csv, encoding="utf-8") as f:
            lines = [f.readline() for _ in range(10)]
        platform = detect_platform(sample_csv, lines)
        assert platform == "coinbase_advanced"

    def test_timestamps_are_utc(self, sample_csv: Path) -> None:
        """All timestamps have UTC timezone info."""
        from datetime import UTC

        parser = CoinbaseAdvancedParser()
        result = parser.parse(sample_csv)

        for tx in result.transactions:
            assert tx.timestamp_utc.tzinfo == UTC

    def test_amounts_are_decimal(self, sample_csv: Path) -> None:
        """All amounts are Decimal, never float."""
        from decimal import Decimal

        parser = CoinbaseAdvancedParser()
        result = parser.parse(sample_csv)

        for tx in result.transactions:
            assert isinstance(tx.base_amount, Decimal)
