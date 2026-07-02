"""Tests for the Gate.io CSV parser."""

from decimal import Decimal
from pathlib import Path

import pytest

from kryptoskatt.parsers.gateio import GateIoParser

FIXTURE = Path(__file__).parent / "fixtures" / "gateio_sample.csv"


@pytest.fixture
def result():
    return GateIoParser().parse(FIXTURE)


def _by_type(result, event_type):
    return [t for t in result.transactions if t.event_type == event_type]


class TestGateIoParser:
    def test_no_errors(self, result):
        assert result.errors == []

    def test_buy_pairs_placed_and_filled(self, result):
        buys = _by_type(result, "BUY")
        assert len(buys) == 2

        btc_buy = next(t for t in buys if t.base_coin == "BTC")
        assert btc_buy.base_amount == Decimal("0.035")
        assert btc_buy.quote_coin == "USDT"
        assert btc_buy.quote_amount == Decimal("1500")

        # Second order: sold BTC for USDT → received USDT, spent BTC
        usdt_buy = next(t for t in buys if t.base_coin == "USDT")
        assert usdt_buy.base_amount == Decimal("450")
        assert usdt_buy.quote_coin == "BTC"
        assert usdt_buy.quote_amount == Decimal("0.01")

    def test_trading_fee(self, result):
        fees = _by_type(result, "FEE")
        assert len(fees) == 1
        assert fees[0].base_coin == "BTC"
        assert fees[0].base_amount == Decimal("-0.00007")

    def test_deposit(self, result):
        ins = _by_type(result, "TRANSFER_IN")
        assert len(ins) == 1
        assert ins[0].base_coin == "USDT"
        assert ins[0].base_amount == Decimal("3000")

    def test_withdrawal(self, result):
        outs = _by_type(result, "TRANSFER_OUT")
        assert len(outs) == 1
        assert outs[0].base_coin == "BTC"
        assert outs[0].base_amount == Decimal("-0.01")

    def test_airdrop_is_reward(self, result):
        rewards = _by_type(result, "REWARD")
        assert len(rewards) == 1
        assert rewards[0].base_coin == "GT"
        assert rewards[0].base_amount == Decimal("2.5")

    def test_source_platform(self, result):
        assert all(t.source_platform == "GATEIO" for t in result.transactions)
