"""Tests for Ledger Live CSV parser."""

import textwrap
from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pytest

from kryptoskatt.enums import Chain, EventType
from kryptoskatt.parsers.ledger import LedgerParser, _detect_chain


@pytest.fixture
def tmp_csv(tmp_path):
    """Helper: write CSV content to a temp file and return the path."""
    def _write(content: str) -> Path:
        p = tmp_path / "ledger.csv"
        p.write_text(textwrap.dedent(content).strip())
        return p
    return _write


HEADER = "Operation Date,Status,Currency Ticker,Operation Type,Operation Amount,Operation Fees,Operation Hash,Account Name,Account xpub,Countervalue Ticker,Countervalue at Operation Date,Countervalue at CSV Export\n"


class TestChainDetection:
    def test_bnb_chain_from_account_name(self):
        assert _detect_chain("BNB Chain - Nubila drop", "0xABC") == Chain.BNB

    def test_xrp_ledger_from_account_name(self):
        assert _detect_chain("XRP Ledger 1", "rXXX") == Chain.RIPPLE

    def test_ethereum_from_account_name(self):
        assert _detect_chain("Ethereum Main", "0xABC") == Chain.ETHEREUM

    def test_bitcoin_from_xpub_prefix(self):
        assert _detect_chain("My Wallet", "xpubDEF") == Chain.BITCOIN

    def test_evm_address_fallback(self):
        assert _detect_chain("Unknown Account", "0xABC") == Chain.ETHEREUM

    def test_unknown_fallback(self):
        assert _detect_chain("Some Wallet", "abc123") == Chain.UNKNOWN


class TestLedgerParser:
    def test_parse_transfer_in(self, tmp_csv):
        csv = HEADER + "2025-11-11T20:22:07.000Z,Confirmed,BNB,IN,0.00509,0.000042,0xHASH,BNB Chain,0xADDR,EUR,4.29,2.96\n"
        txs, errors = LedgerParser().parse(tmp_csv(csv))
        assert errors == []
        assert len(txs) == 1
        tx = txs[0]
        assert tx.event_type == EventType.TRANSFER_IN
        assert tx.base_coin == "BNB"
        assert tx.base_amount == Decimal("0.00509")
        assert tx.to_address == "0xADDR"
        assert tx.from_address is None

    def test_transfer_in_amount_is_positive(self, tmp_csv):
        csv = HEADER + "2025-11-11T20:22:07.000Z,Confirmed,BNB,IN,0.00509,0.000042,0xHASH,BNB Chain,0xADDR,EUR,4.29,2.96\n"
        txs, _ = LedgerParser().parse(tmp_csv(csv))
        assert txs[0].base_amount > 0

    def test_parse_transfer_out(self, tmp_csv):
        csv = HEADER + "2025-11-11T20:28:56.000Z,Confirmed,NB,OUT,78.37,,0xHASH2,BNB Chain,0xADDR,EUR,7.13,0.04\n"
        txs, errors = LedgerParser().parse(tmp_csv(csv))
        assert errors == []
        assert len(txs) == 1
        tx = txs[0]
        assert tx.event_type == EventType.TRANSFER_OUT
        assert tx.base_amount == Decimal("-78.37")
        assert tx.from_address == "0xADDR"
        assert tx.to_address is None

    def test_parse_fee(self, tmp_csv):
        csv = HEADER + "2025-11-11T20:28:56.000Z,Confirmed,BNB,FEES,0.00016677,0.00016677,0xHASH,BNB Chain,0xADDR,EUR,0.14,0.09\n"
        txs, errors = LedgerParser().parse(tmp_csv(csv))
        assert errors == []
        assert len(txs) == 1
        tx = txs[0]
        assert tx.event_type == EventType.FEE
        assert tx.base_amount == Decimal("-0.00016677")

    def test_skip_non_confirmed(self, tmp_csv):
        csv = HEADER + "2025-11-11T20:28:56.000Z,Pending,BNB,IN,1.0,,0xHASH,BNB Chain,0xADDR,EUR,0,0\n"
        txs, errors = LedgerParser().parse(tmp_csv(csv))
        assert txs == []
        assert errors == []

    def test_xrp_chain_detected(self, tmp_csv):
        csv = HEADER + "2018-10-25T14:58:01.000Z,Confirmed,XRP,IN,54.673,0.2,0xHASH,XRP Ledger 1,rXPRADDR,EUR,22.18,68.23\n"
        txs, _ = LedgerParser().parse(tmp_csv(csv))
        assert txs[0].raw_payload["chain"] == Chain.RIPPLE.value

    def test_empty_fee_column(self, tmp_csv):
        csv = HEADER + "2025-11-11T20:28:56.000Z,Confirmed,NB,OUT,78.37,,0xHASH,BNB Chain,0xADDR,EUR,7.13,0.04\n"
        txs, errors = LedgerParser().parse(tmp_csv(csv))
        assert errors == []
        assert txs[0].fee_amount is None

    def test_timestamp_parsed_as_utc(self, tmp_csv):
        csv = HEADER + "2025-07-13T08:03:50.000Z,Confirmed,XRP,IN,0.000001,0.000011,0xHASH,XRP Ledger 1,rXXX,EUR,0.00,0.00\n"
        txs, _ = LedgerParser().parse(tmp_csv(csv))
        assert txs[0].timestamp_utc.tzinfo == UTC

    def test_source_platform(self, tmp_csv):
        csv = HEADER + "2025-11-11T20:22:07.000Z,Confirmed,BNB,IN,0.00509,0.000042,0xHASH,BNB Chain,0xADDR,EUR,4.29,2.96\n"
        txs, _ = LedgerParser().parse(tmp_csv(csv))
        assert txs[0].source_platform == "LEDGER"

    def test_multiple_rows(self, tmp_csv):
        csv = (
            HEADER
            + "2025-11-11T20:28:56.000Z,Confirmed,BNB,FEES,0.00016677,0.00016677,0xH1,BNB Chain,0xADDR,EUR,0.14,0.09\n"
            + "2025-11-11T20:22:07.000Z,Confirmed,BNB,IN,0.00509,0.000042,0xH2,BNB Chain,0xADDR,EUR,4.29,2.96\n"
            + "2025-11-11T20:28:56.000Z,Confirmed,NB,OUT,78.37,,0xH3,BNB Chain,0xADDR,EUR,7.13,0.04\n"
        )
        txs, errors = LedgerParser().parse(tmp_csv(csv))
        assert errors == []
        assert len(txs) == 3

    def test_auto_detect_platform(self, tmp_csv, tmp_path):
        """import_cmd.detect_platform should recognise Ledger files."""
        from kryptoskatt.cli.import_cmd import detect_platform
        csv_path = tmp_path / "ledger_export.csv"
        content = HEADER + "2025-11-11T20:22:07.000Z,Confirmed,BNB,IN,0.00509,0.000042,0xH,BNB Chain,0xADDR,EUR,4.29,2.96\n"
        csv_path.write_text(content)
        lines = content.splitlines()[:10]
        assert detect_platform(csv_path, lines) == "ledger"
