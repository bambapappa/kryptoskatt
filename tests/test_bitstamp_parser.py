"""Tests for the Bitstamp CSV parser."""

from decimal import Decimal
from pathlib import Path

import pytest

from kryptoskatt.parsers.bitstamp import BitstampParser

FIXTURE = Path(__file__).parent / "fixtures" / "bitstamp_sample.csv"


@pytest.fixture
def result():
    return BitstampParser().parse(FIXTURE)


def _by_type(result, event_type):
    return [t for t in result.transactions if t.event_type == event_type]


class TestBitstampParser:
    def test_no_errors(self, result):
        assert result.errors == []

    def test_buy(self, result):
        buys = _by_type(result, "BUY")
        assert len(buys) == 1
        buy = buys[0]
        assert buy.base_coin == "BTC"
        assert buy.base_amount == Decimal("0.05")
        assert buy.quote_coin == "EUR"
        assert buy.quote_amount == Decimal("2000.00")
        assert buy.fee_coin == "EUR"
        assert buy.fee_amount == Decimal("8.00")
        assert buy.timestamp_utc.year == 2024

    def test_sell(self, result):
        sells = _by_type(result, "SELL")
        assert len(sells) == 1
        sell = sells[0]
        assert sell.base_coin == "BTC"
        assert sell.base_amount == Decimal("0.02")
        assert sell.quote_coin == "EUR"
        assert sell.quote_amount == Decimal("900.00")

    def test_deposit_fiat_is_transfer_in(self, result):
        ins = _by_type(result, "TRANSFER_IN")
        assert len(ins) == 1
        assert ins[0].base_coin == "EUR"
        assert ins[0].base_amount == Decimal("5000.00")

    def test_withdrawal(self, result):
        outs = _by_type(result, "TRANSFER_OUT")
        assert len(outs) == 1
        assert outs[0].base_coin == "BTC"
        assert outs[0].base_amount == Decimal("-0.03")

    def test_staking_reward(self, result):
        rewards = _by_type(result, "REWARD")
        assert len(rewards) == 1
        assert rewards[0].base_coin == "ETH"
        assert rewards[0].base_amount == Decimal("0.15")

    def test_source_platform(self, result):
        assert all(t.source_platform == "BITSTAMP" for t in result.transactions)

    def test_v1_format_with_embedded_currency(self, tmp_path):
        csv_text = (
            "Type,Datetime,Account,Amount,Value,Rate,Fee,Sub Type\n"
            '"Market","Apr. 15, 2024, 10:30 AM","Main","0.05000000 BTC","2000.00 EUR","40000.00 EUR","8.00 EUR","Buy"\n'
        )
        f = tmp_path / "v1.csv"
        f.write_text(csv_text)
        result = BitstampParser().parse(f)
        assert result.errors == []
        assert len(result.transactions) == 1
        tx = result.transactions[0]
        assert tx.event_type == "BUY"
        assert tx.base_coin == "BTC"
        assert tx.base_amount == Decimal("0.05")
        assert tx.quote_coin == "EUR"
