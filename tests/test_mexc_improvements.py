"""Tests for MEXC parser improvements: fee handling and missing column tolerance."""

from decimal import Decimal
from pathlib import Path

import pytest

from kryptoskatt.enums import EventType
from kryptoskatt.parsers.mexc import MexcParser


@pytest.fixture
def trade_tsv_with_fee(tmp_path: Path) -> Path:
    """Trade TSV that includes an Avgift (fee) column."""
    content = (
        "Tid\tKrypto\tTyp\tKvantitet\tAvgift\n"
        "2025-10-21 11:59:41\tBTC\tKöp\t0.001\t0.000001\n"
    )
    p = tmp_path / "trade_with_fee.tsv"
    p.write_text(content)
    return p


@pytest.fixture
def trade_tsv_without_fee(tmp_path: Path) -> Path:
    """Trade TSV that has no fee column at all."""
    content = (
        "Tid\tKrypto\tTyp\tKvantitet\n"
        "2025-10-21 11:59:41\tBTC\tKöp\t0.001\n"
    )
    p = tmp_path / "trade_no_fee.tsv"
    p.write_text(content)
    return p


@pytest.fixture
def trade_tsv_empty_fee(tmp_path: Path) -> Path:
    """Trade TSV where the fee column exists but value is empty."""
    content = (
        "Tid\tKrypto\tTyp\tKvantitet\tAvgift\n"
        "2025-10-21 11:59:41\tBTC\tKöp\t0.001\t\n"
    )
    p = tmp_path / "trade_empty_fee.tsv"
    p.write_text(content)
    return p


class TestMexcFeeHandling:
    def test_mexc_trade_creates_fee_transaction(self, trade_tsv_with_fee: Path) -> None:
        """Trade row with fee column → fee_amount and fee_coin are populated."""
        parser = MexcParser()
        transactions, errors = parser.parse(trade_tsv_with_fee)

        assert errors == []
        assert len(transactions) == 1
        tx = transactions[0]
        assert tx.event_type == EventType.BUY
        assert tx.fee_amount == Decimal("0.000001")
        assert tx.fee_coin == "BTC"

    def test_mexc_handles_missing_column_gracefully(self, trade_tsv_without_fee: Path) -> None:
        """Trade CSV without fee column parses without errors, fee_amount is None."""
        parser = MexcParser()
        transactions, errors = parser.parse(trade_tsv_without_fee)

        assert errors == []
        assert len(transactions) == 1
        tx = transactions[0]
        assert tx.fee_amount is None
        assert tx.fee_coin is None

    def test_mexc_empty_fee_value_yields_no_fee(self, trade_tsv_empty_fee: Path) -> None:
        """Trade row where fee column is blank → fee_amount stays None."""
        parser = MexcParser()
        transactions, errors = parser.parse(trade_tsv_empty_fee)

        assert errors == []
        assert len(transactions) == 1
        tx = transactions[0]
        assert tx.fee_amount is None

    def test_mexc_sell_with_fee(self, tmp_path: Path) -> None:
        """Sell trade row: amount is negative, fee is still positive."""
        content = (
            "Tid\tKrypto\tTyp\tKvantitet\tAvgift\n"
            "2025-10-22 09:30:00\tETH\tSälj\t0.5\t0.0005\n"
        )
        p = tmp_path / "sell_with_fee.tsv"
        p.write_text(content)

        parser = MexcParser()
        transactions, errors = parser.parse(p)

        assert errors == []
        assert len(transactions) == 1
        tx = transactions[0]
        assert tx.event_type == EventType.SELL
        assert tx.base_amount == Decimal("-0.5")
        assert tx.fee_amount == Decimal("0.0005")
        assert tx.fee_coin == "ETH"

    def test_mexc_trade_fixture_parses_correctly(self) -> None:
        """Trade fixture file (3 rows) parses without errors."""
        fixture = Path(__file__).parent / "fixtures" / "mexc_trade_sample.tsv"
        parser = MexcParser()
        transactions, errors = parser.parse(fixture)

        assert errors == []
        assert len(transactions) == 3
        # First row is a BUY
        assert transactions[0].event_type == EventType.BUY
        assert transactions[0].fee_amount == Decimal("0.000001")
        # Second row is a SELL with negative amount
        assert transactions[1].event_type == EventType.SELL
        assert transactions[1].base_amount < 0
