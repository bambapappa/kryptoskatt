"""Tests for the OKX CSV parser (trading statement + funding bill)."""

from decimal import Decimal
from pathlib import Path

import pytest

from kryptoskatt.parsers.okx import OkxParser

TRADES = Path(__file__).parent / "fixtures" / "okx_trades_sample.csv"
FUNDING = Path(__file__).parent / "fixtures" / "okx_funding_sample.csv"


class TestOkxTrades:
    @pytest.fixture
    def result(self):
        return OkxParser().parse(TRADES)

    def test_no_errors(self, result):
        assert result.errors == []

    def test_buy_sell_legs_paired_into_buys(self, result):
        buys = [t for t in result.transactions if t.event_type == "BUY"]
        assert len(buys) == 2

        btc = next(t for t in buys if t.base_coin == "BTC")
        assert btc.base_amount == Decimal("0.05")
        assert btc.quote_coin == "USDT"
        assert btc.quote_amount == Decimal("2100")

        eth = next(t for t in buys if t.base_coin == "ETH")
        assert eth.base_amount == Decimal("1.5")
        assert eth.quote_coin == "USDT"
        assert eth.quote_amount == Decimal("4500")

    def test_fees_extracted(self, result):
        fees = [t for t in result.transactions if t.event_type == "FEE"]
        assert len(fees) == 2
        assert all(t.base_coin == "USDT" and t.base_amount < 0 for t in fees)

    def test_source_platform(self, result):
        assert all(t.source_platform == "OKX" for t in result.transactions)


class TestOkxFunding:
    @pytest.fixture
    def result(self):
        return OkxParser().parse(FUNDING)

    def test_no_errors(self, result):
        assert result.errors == []

    def test_deposit(self, result):
        ins = [t for t in result.transactions if t.event_type == "TRANSFER_IN"]
        assert len(ins) == 1
        assert ins[0].base_coin == "BTC"
        assert ins[0].base_amount == Decimal("0.5")

    def test_withdrawal_with_fee(self, result):
        outs = [t for t in result.transactions if t.event_type == "TRANSFER_OUT"]
        assert len(outs) == 1
        assert outs[0].base_amount == Decimal("-0.2")
        fees = [t for t in result.transactions if t.event_type == "FEE"]
        assert len(fees) == 1
        assert fees[0].base_amount == Decimal("-0.0002")

    def test_staking_yield_is_reward(self, result):
        rewards = [t for t in result.transactions if t.event_type == "REWARD"]
        assert len(rewards) == 1
        assert rewards[0].base_coin == "ETH"
        assert rewards[0].base_amount == Decimal("0.01")


class TestOkxUnrecognized:
    def test_unknown_header_reports_error(self, tmp_path):
        f = tmp_path / "x.csv"
        f.write_text("foo,bar\n1,2\n")
        result = OkxParser().parse(f)
        assert result.transactions == []
        assert result.errors
