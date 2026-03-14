"""Tests for KuCoin CSV parser."""

from decimal import Decimal
from pathlib import Path

from kryptoskatt.cli.import_cmd import detect_platform
from kryptoskatt.enums import EventType
from kryptoskatt.parsers.kucoin import KuCoinParser

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "kucoin_sample.csv"


def test_buy_row_produces_buy_transaction():
    parser = KuCoinParser()
    result = parser.parse(SAMPLE)

    assert result.errors == []
    buys = [t for t in result.transactions if t.event_type == EventType.BUY.value]
    assert len(buys) >= 1

    btc_buy = next(t for t in buys if t.base_coin == "BTC")
    assert btc_buy.base_amount == Decimal("0.001")
    assert btc_buy.quote_coin == "USDT"
    assert btc_buy.source_platform == "KUCOIN"


def test_sell_row_produces_sell_transaction():
    parser = KuCoinParser()
    result = parser.parse(SAMPLE)

    sells = [t for t in result.transactions if t.event_type == EventType.SELL.value]
    assert len(sells) == 1

    sell = sells[0]
    assert sell.base_coin == "ETH"
    assert sell.quote_coin == "USDT"
    assert sell.source_platform == "KUCOIN"


def test_fee_transaction_emitted_when_fee_nonzero():
    parser = KuCoinParser()
    result = parser.parse(SAMPLE)

    fees = [t for t in result.transactions if t.event_type == EventType.FEE.value]
    # All three rows have fee > 0, so we expect 3 FEE transactions
    assert len(fees) == 3


def test_symbol_parsing_splits_base_and_quote():
    parser = KuCoinParser()
    result = parser.parse(SAMPLE)

    # SOL-BTC row: base=SOL, quote=BTC
    sol_buy = next(
        t for t in result.transactions
        if t.event_type == EventType.BUY.value and t.base_coin == "SOL"
    )
    assert sol_buy.base_coin == "SOL"
    assert sol_buy.quote_coin == "BTC"


def test_auto_detect_kucoin():
    lines = [
        "tradeId,symbol,side,price,size,funds,fee,feeRate,feeCurrency,fixFee,context,orderId,orderPlacedAt,orderType,orderSide\n"
    ]
    platform = detect_platform(SAMPLE, lines)
    assert platform == "kucoin"
