"""Tests for manual DEX swap CSV parser."""

from decimal import Decimal
from pathlib import Path

from kryptoskatt.enums import EventType
from kryptoskatt.parsers.manual_swap import ManualSwapParser

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "manual_swap_sample.csv"


def _parse():
    return ManualSwapParser().parse(SAMPLE)


def test_generates_swap_out():
    result = _parse()
    assert result.errors == []
    swap_outs = [t for t in result.transactions if t.event_type == EventType.SWAP_OUT.value]
    assert len(swap_outs) == 2  # one per row

    eth_out = next(t for t in swap_outs if t.base_coin == "ETH")
    assert eth_out.base_amount == Decimal("1.0")
    assert eth_out.source_platform == "MANUAL_SWAP"


def test_generates_swap_in():
    result = _parse()
    swap_ins = [t for t in result.transactions if t.event_type == EventType.SWAP_IN.value]
    assert len(swap_ins) == 2

    usdc_in = next(t for t in swap_ins if t.base_coin == "USDC")
    assert usdc_in.base_amount == Decimal("2500.00")


def test_generates_fee():
    result = _parse()
    fees = [t for t in result.transactions if t.event_type == EventType.FEE.value]
    # Only row 1 has a fee; row 2 has empty fee fields
    assert len(fees) == 1
    assert fees[0].base_coin == "ETH"
    assert fees[0].base_amount == Decimal("0.003")


def test_no_fee_when_zero():
    result = _parse()
    # Row 2 has empty fee_amount — no FEE for that row
    fees = [t for t in result.transactions if t.event_type == EventType.FEE.value]
    dai_fees = [f for f in fees if f.base_coin == "DAI"]
    assert dai_fees == []


def test_same_timestamp_all_transactions_from_row():
    result = _parse()
    # All transactions from the first row share the same timestamp
    row1_txs = [t for t in result.transactions if t.tx_hash == "0xabc123def456"]
    timestamps = {t.timestamp_utc for t in row1_txs}
    assert len(timestamps) == 1


def test_tx_hash_propagated():
    result = _parse()
    row1_txs = [t for t in result.transactions if t.tx_hash == "0xabc123def456"]
    # SWAP_OUT + SWAP_IN + FEE = 3 transactions share the hash
    assert len(row1_txs) == 3
    for tx in row1_txs:
        assert tx.tx_hash == "0xabc123def456"
