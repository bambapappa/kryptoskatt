"""Tests for the Kraken CSV parser."""

from decimal import Decimal
from pathlib import Path

import pytest

from kryptoskatt.parsers.kraken import KrakenParser, _normalize_asset

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def parser() -> KrakenParser:
    return KrakenParser()


@pytest.fixture
def sample_file() -> Path:
    return FIXTURES / "kraken_sample.csv"


class TestParseTradeBuy:
    """Trade pair where positive amount is BTC (bought with SEK) → BUY."""

    def test_parse_trade_buy(self, parser: KrakenParser, sample_file: Path):
        result = parser.parse(sample_file)
        # Find the BUY transaction
        buys = [t for t in result.transactions if t.event_type == "BUY"]
        assert len(buys) == 1

        tx = buys[0]
        assert tx.base_coin == "BTC"
        assert tx.base_amount == Decimal("0.001")
        assert tx.quote_coin == "SEK"
        assert tx.quote_amount == Decimal("500.00")
        assert tx.source_platform == "KRAKEN"

    def test_parse_trade_produces_fee_transaction(self, parser: KrakenParser, sample_file: Path):
        """Fee > 0 on a trade row → separate FEE transaction."""
        result = parser.parse(sample_file)
        fees = [t for t in result.transactions if t.event_type == "FEE"]
        # Fee is on the BTC row (0.0000002)
        assert any(t.base_coin == "BTC" for t in fees), (
            f"Expected a FEE for BTC, got: {fees}"
        )


class TestParseDeposit:
    def test_parse_deposit(self, parser: KrakenParser, sample_file: Path):
        result = parser.parse(sample_file)
        deposits = [t for t in result.transactions if t.event_type == "TRANSFER_IN"]
        assert len(deposits) == 1
        tx = deposits[0]
        assert tx.base_coin == "ETH"
        assert tx.base_amount == Decimal("1.0")
        assert tx.source_platform == "KRAKEN"


class TestParseStaking:
    def test_parse_staking(self, parser: KrakenParser, sample_file: Path):
        result = parser.parse(sample_file)
        rewards = [t for t in result.transactions if t.event_type == "REWARD"]
        assert len(rewards) == 1
        tx = rewards[0]
        assert tx.base_coin == "BTC"
        assert tx.base_amount == Decimal("0.00001")


class TestAssetNormalization:
    @pytest.mark.parametrize("raw,expected", [
        ("XXBT", "BTC"),
        ("XETH", "ETH"),
        ("ZSEK", "SEK"),
        ("ZEUR", "EUR"),
        ("ZUSD", "USD"),
        ("SOL", "SOL"),   # passthrough for assets without prefix
    ])
    def test_asset_normalization(self, raw: str, expected: str):
        assert _normalize_asset(raw) == expected


class TestFeeCreatesTransaction:
    def test_fee_creates_fee_transaction(self, parser: KrakenParser):
        """Explicitly test that a non-zero fee on a non-trade row creates a FEE tx."""
        import tempfile
        from pathlib import Path

        csv_content = (
            "txid,refid,time,type,subtype,aclass,asset,amount,fee,balance\n"
            "L999,,2024-06-01 12:00:00,deposit,,currency,XETH,2.0,0.001,2.0\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(csv_content)
            tmp_path = Path(f.name)

        try:
            result = parser.parse(tmp_path)
            fee_txs = [t for t in result.transactions if t.event_type == "FEE"]
            assert len(fee_txs) == 1
            assert fee_txs[0].base_coin == "ETH"
            assert fee_txs[0].base_amount == Decimal("-0.001")
        finally:
            tmp_path.unlink(missing_ok=True)


class TestWithdrawal:
    def test_parse_withdrawal(self, parser: KrakenParser):
        import tempfile
        from pathlib import Path

        csv_content = (
            "txid,refid,time,type,subtype,aclass,asset,amount,fee,balance\n"
            "L888,,2024-05-01 09:00:00,withdrawal,,currency,XXBT,-0.05,0.0002,0.05\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(csv_content)
            tmp_path = Path(f.name)

        try:
            result = parser.parse(tmp_path)
            outs = [t for t in result.transactions if t.event_type == "TRANSFER_OUT"]
            assert len(outs) == 1
            assert outs[0].base_coin == "BTC"
            assert outs[0].base_amount < 0
        finally:
            tmp_path.unlink(missing_ok=True)
