"""Tests for MEXC TSV parser."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from kryptoskatt.enums import Chain, EventType


class TestMexcParser:
    """Test suite for MexcParser."""

    def test_parse_deposit_file_returns_3_transfer_in(self, mexc_deposit_tsv: Path) -> None:
        """Test that deposit file parses to 3 TRANSFER_IN transactions."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, errors = parser.parse(mexc_deposit_tsv)

        assert len(errors) == 0
        assert len(transactions) == 3
        for tx in transactions:
            assert tx.event_type == EventType.TRANSFER_IN

    def test_parse_withdrawal_file_returns_7_transfer_out(self, mexc_withdrawal_tsv: Path) -> None:
        """Test that withdrawal file parses to 7 TRANSFER_OUT transactions."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, errors = parser.parse(mexc_withdrawal_tsv)

        assert len(errors) == 0
        assert len(transactions) == 7
        for tx in transactions:
            assert tx.event_type == EventType.TRANSFER_OUT

    def test_deposit_auto_detection_from_headers(self, mexc_deposit_tsv: Path) -> None:
        """Test auto-detection of deposit file from headers."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_deposit_tsv)

        # Should detect deposit via Insättningsbelopp column
        assert all(tx.event_type == EventType.TRANSFER_IN for tx in transactions)

    def test_withdrawal_auto_detection_from_headers(self, mexc_withdrawal_tsv: Path) -> None:
        """Test auto-detection of withdrawal file from headers."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_withdrawal_tsv)

        # Should detect withdrawal via Uttagsadress column
        assert all(tx.event_type == EventType.TRANSFER_OUT for tx in transactions)

    def test_network_to_chain_mapping_eth(self, mexc_deposit_tsv: Path) -> None:
        """Test Ethereum(ERC20) maps to Chain.ETHEREUM."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_deposit_tsv)

        # First two rows are ETH on Ethereum(ERC20)
        for tx in transactions[:2]:
            assert tx.base_coin == "ETH"
            assert tx.raw_payload is not None
            assert tx.raw_payload.get("chain") == Chain.ETHEREUM

    def test_network_to_chain_mapping_solana(self, mexc_withdrawal_tsv: Path) -> None:
        """Test Solana(SOL) maps to Chain.SOLANA."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_withdrawal_tsv)

        # Find SOL transactions
        sol_txs = [tx for tx in transactions if tx.base_coin == "SOL"]
        assert len(sol_txs) == 2
        for tx in sol_txs:
            assert tx.raw_payload is not None
            assert tx.raw_payload.get("chain") == Chain.SOLANA

    def test_network_to_chain_mapping_polygon(self, mexc_withdrawal_tsv: Path) -> None:
        """Test Polygon(MATIC) maps to Chain.POLYGON."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_withdrawal_tsv)

        # Find POL transactions
        pol_txs = [tx for tx in transactions if tx.base_coin == "POL"]
        assert len(pol_txs) == 3
        for tx in pol_txs:
            assert tx.raw_payload is not None
            assert tx.raw_payload.get("chain") == Chain.POLYGON

    def test_network_to_chain_mapping_bnb(self, mexc_withdrawal_tsv: Path) -> None:
        """Test BNB Smart Chain(BEP20) maps to Chain.BNB."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_withdrawal_tsv)

        # Find BNB transaction
        bnb_tx = [tx for tx in transactions if tx.base_coin == "BNB"][0]
        assert bnb_tx.raw_payload is not None
        assert bnb_tx.raw_payload.get("chain") == Chain.BNB

    def test_network_to_chain_mapping_kda(self, mexc_deposit_tsv: Path) -> None:
        """Test KDA maps to Chain.KADENA."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_deposit_tsv)

        # Find KDA transaction
        kda_tx = [tx for tx in transactions if tx.base_coin == "KDA"][0]
        assert kda_tx.raw_payload is not None
        assert kda_tx.raw_payload.get("chain") == Chain.KADENA

    def test_network_to_chain_mapping_peaq(self, mexc_withdrawal_tsv: Path) -> None:
        """Test PEAQ maps to Chain.PEAQ."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_withdrawal_tsv)

        # Find PEAQ transaction
        peaq_tx = [tx for tx in transactions if tx.base_coin == "PEAQ"][0]
        assert peaq_tx.raw_payload is not None
        assert peaq_tx.raw_payload.get("chain") == Chain.PEAQ

    def test_txid_suffix_stripped(self, mexc_deposit_tsv: Path) -> None:
        """Test TxID suffix is stripped from tx_hash field."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_deposit_tsv)

        # KDA row has suffix :010
        kda_tx = [tx for tx in transactions if tx.base_coin == "KDA"][0]
        # tx_hash should NOT have suffix
        assert kda_tx.tx_hash == "O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM"
        # raw_payload should have original
        assert kda_tx.raw_payload is not None
        assert ":010" in kda_tx.raw_payload.get("TxID", "")

    def test_withdrawal_fee_extraction(self, mexc_withdrawal_tsv: Path) -> None:
        """Test withdrawal fee extraction from Handelsavgift column."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_withdrawal_tsv)

        # First withdrawal: POL, fee=0.3
        pol_tx = [tx for tx in transactions if tx.base_coin == "POL"][0]
        assert pol_tx.fee_amount == Decimal("0.3")
        assert pol_tx.fee_coin == "POL"

    def test_withdrawal_uses_settlement_amount(self, mexc_withdrawal_tsv: Path) -> None:
        """Test withdrawal uses Avräkningsbelopp (settlement) as base_amount."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_withdrawal_tsv)

        # First withdrawal: requested=216.13, settled=215.83
        pol_tx = [tx for tx in transactions if tx.base_coin == "POL"][0]
        # base_amount should be settlement amount (215.83), not requested (216.13)
        # Note: Negative because TRANSFER_OUT
        assert abs(pol_tx.base_amount) == Decimal("215.83")

    def test_withdrawal_negative_amount(self, mexc_withdrawal_tsv: Path) -> None:
        """Test withdrawal amount is negative."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_withdrawal_tsv)

        # All withdrawal amounts should be negative
        for tx in transactions:
            assert tx.base_amount < 0

    def test_withdrawal_to_address_extraction(self, mexc_withdrawal_tsv: Path) -> None:
        """Test withdrawal to_address extraction from Uttagsadress column."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_withdrawal_tsv)

        # First withdrawal has address
        pol_tx = [tx for tx in transactions if tx.base_coin == "POL"][0]
        assert pol_tx.to_address == "0x85fB22b3C15C7C2c93F26E83F446950D9408ba67"

    def test_all_amounts_are_decimal(self, mexc_deposit_tsv: Path) -> None:
        """Test all amounts are Decimal instances, never float."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_deposit_tsv)

        for tx in transactions:
            assert isinstance(tx.base_amount, Decimal)
            if tx.quote_amount is not None:
                assert isinstance(tx.quote_amount, Decimal)
            if tx.fee_amount is not None:
                assert isinstance(tx.fee_amount, Decimal)

    def test_raw_payload_includes_original_data(self, mexc_deposit_tsv: Path) -> None:
        """Test raw_payload includes original row data."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_deposit_tsv)

        for tx in transactions:
            assert tx.raw_payload is not None
            # Should include Swedish column names
            assert "Insättningsbelopp" in tx.raw_payload
            assert "TxID" in tx.raw_payload
            assert "Krypto" in tx.raw_payload
            assert "Nätverk" in tx.raw_payload

    def test_source_platform_is_mexc(self, mexc_deposit_tsv: Path) -> None:
        """Test source_platform is MEXC."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_deposit_tsv)

        for tx in transactions:
            assert tx.source_platform == "MEXC"

    def test_deposit_positive_amount(self, mexc_deposit_tsv: Path) -> None:
        """Test deposit amounts are positive."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_deposit_tsv)

        for tx in transactions:
            assert tx.base_amount > 0

    def test_timestamp_parsing(self, mexc_deposit_tsv: Path) -> None:
        """Test timestamp is parsed correctly as UTC."""
        from kryptoskatt.parsers.mexc import MexcParser

        parser = MexcParser()
        transactions, _ = parser.parse(mexc_deposit_tsv)

        # First row: 2025-10-21 11:59:41
        tx = transactions[0]
        assert tx.timestamp_utc == datetime(2025, 10, 21, 11, 59, 41, tzinfo=UTC)

    def test_error_handling_malformed_rows(self, tmp_path: Path) -> None:
        """Test error handling for malformed rows."""
        from kryptoskatt.parsers.mexc import MexcParser

        # Create a malformed TSV file with not enough columns
        malformed_content = (
            "UID\tStatus\tTid\tKrypto\tNätverk\tInsättningsbelopp\tTxID\tFramsteg\n"
            "48736451\tHar krediterats\t2025-10-21 11:59:41\tETH\tEthereum(ERC20)\t0.013\t0xabc\t(98/96)\n"
            "48736451\tHar krediterats\t2025-10-21 11:59:42\n"  # Not enough columns
            "48736451\tHar krediterats\t2025-10-21 10:35:29\tETH\tEthereum(ERC20)\t0.00030011\t0xdef\t(97/96)\n"
        )
        test_file = tmp_path / "malformed.tsv"
        test_file.write_text(malformed_content)

        parser = MexcParser()
        transactions, errors = parser.parse(test_file)

        # Should still get valid transactions
        assert len(transactions) == 2
        # Should collect error about columns
        assert len(errors) == 1
        assert "column" in errors[0].lower() or "row" in errors[0].lower()
