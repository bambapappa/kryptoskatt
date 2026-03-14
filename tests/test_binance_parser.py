"""Tests for Binance CSV parser."""

from pathlib import Path

import pytest

from kryptoskatt.cli.import_cmd import detect_platform
from kryptoskatt.parsers.binance import BinanceParser

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_csv() -> Path:
    return FIXTURES_DIR / "binance_sample.csv"


class TestBinanceParser:
    """Test suite for BinanceParser."""

    def test_parse_buy(self, sample_csv: Path) -> None:
        """Buy row paired with Transaction Related produces a BUY transaction."""
        parser = BinanceParser()
        result = parser.parse(sample_csv)

        buy_txs = [tx for tx in result.transactions if tx.event_type == "BUY"]
        assert len(buy_txs) == 1

        buy = buy_txs[0]
        assert buy.base_coin == "BTC"
        assert buy.base_amount > 0
        assert buy.quote_coin == "USDT"
        assert buy.quote_amount > 0

    def test_parse_deposit(self, sample_csv: Path) -> None:
        """Deposit row produces a TRANSFER_IN transaction."""
        parser = BinanceParser()
        result = parser.parse(sample_csv)

        deposits = [tx for tx in result.transactions if tx.event_type == "TRANSFER_IN"]
        assert len(deposits) == 1

        deposit = deposits[0]
        assert deposit.base_coin == "ETH"
        assert deposit.base_amount > 0

    def test_parse_reward(self, sample_csv: Path) -> None:
        """POS savings interest row produces a REWARD transaction."""
        parser = BinanceParser()
        result = parser.parse(sample_csv)

        rewards = [tx for tx in result.transactions if tx.event_type == "REWARD"]
        assert len(rewards) == 1

        reward = rewards[0]
        assert reward.base_coin == "BTC"
        assert reward.base_amount > 0

    def test_auto_detect(self, sample_csv: Path) -> None:
        """detect_platform returns 'binance' for the fixture file."""
        with open(sample_csv, encoding="utf-8") as f:
            lines = [f.readline() for _ in range(10)]
        platform = detect_platform(sample_csv, lines)
        assert platform == "binance"

    def test_timestamps_are_utc(self, sample_csv: Path) -> None:
        """All timestamps have UTC timezone info."""
        from datetime import UTC

        parser = BinanceParser()
        result = parser.parse(sample_csv)

        for tx in result.transactions:
            assert tx.timestamp_utc.tzinfo == UTC

    def test_amounts_are_decimal(self, sample_csv: Path) -> None:
        """All amounts are Decimal, never float."""
        from decimal import Decimal

        parser = BinanceParser()
        result = parser.parse(sample_csv)

        for tx in result.transactions:
            assert isinstance(tx.base_amount, Decimal)
