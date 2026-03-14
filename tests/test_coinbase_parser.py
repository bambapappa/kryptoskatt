"""Tests for Coinbase CSV parser."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from kryptoskatt.parsers.coinbase import CoinbaseParser, ParseResult
from kryptoskatt.schemas import TransactionCreate


class TestCoinbaseParser:
    """Test suite for CoinbaseParser."""

    def test_parse_returns_15_transactions_from_fixture(self, coinbase_csv):
        """Test that parsing the fixture file returns exactly 15 transactions."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        assert isinstance(result, ParseResult)
        assert len(result.transactions) == 15, (
            f"Expected 15 transactions, got {len(result.transactions)}"
        )
        assert len(result.errors) == 0, f"Expected no errors, got {result.errors}"

    def test_all_amounts_are_decimal(self, coinbase_csv):
        """Test that all amount fields are Decimal instances, never float."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        for tx in result.transactions:
            assert isinstance(tx.base_amount, Decimal), (
                f"base_amount should be Decimal, got {type(tx.base_amount)}"
            )
            if tx.quote_amount is not None:
                assert isinstance(tx.quote_amount, Decimal), (
                    f"quote_amount should be Decimal, got {type(tx.quote_amount)}"
                )
            if tx.fee_amount is not None:
                assert isinstance(tx.fee_amount, Decimal), (
                    f"fee_amount should be Decimal, got {type(tx.fee_amount)}"
                )
            if tx.price_sek is not None:
                assert isinstance(tx.price_sek, Decimal), (
                    f"price_sek should be Decimal, got {type(tx.price_sek)}"
                )

    def test_convert_rows_produce_swap_out_and_swap_in(self, coinbase_csv):
        """Test that Convert rows produce both SWAP_OUT and SWAP_IN transactions."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        convert_txs = [tx for tx in result.transactions if tx.event_type in ("SWAP_OUT", "SWAP_IN")]

        # There should be 4 Convert rows = 8 transactions (4 SWAP_OUT + 4 SWAP_IN)
        assert len(convert_txs) == 8, f"Expected 8 SWAP transactions, got {len(convert_txs)}"

        swap_out_count = sum(1 for tx in result.transactions if tx.event_type == "SWAP_OUT")
        swap_in_count = sum(1 for tx in result.transactions if tx.event_type == "SWAP_IN")

        assert swap_out_count == 4, f"Expected 4 SWAP_OUT, got {swap_out_count}"
        assert swap_in_count == 4, f"Expected 4 SWAP_IN, got {swap_in_count}"

    def test_convert_xrp_to_aloe(self, coinbase_csv):
        """Test the first Convert row: XRP to ALEO."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        # Find the XRP to ALEO swap
        swap_out_txs = [
            tx
            for tx in result.transactions
            if tx.event_type == "SWAP_OUT" and tx.base_coin == "XRP"
        ]
        swap_in_txs = [
            tx
            for tx in result.transactions
            if tx.event_type == "SWAP_IN" and tx.base_coin == "ALEO"
        ]

        assert len(swap_out_txs) == 1, "Should have one SWAP_OUT for XRP"
        assert len(swap_in_txs) == 1, "Should have one SWAP_IN for ALEO"

        swap_out = swap_out_txs[0]
        swap_in = swap_in_txs[0]

        # Verify amounts
        assert swap_out.base_amount == Decimal("-7.53325"), (
            f"Expected -7.53325, got {swap_out.base_amount}"
        )
        assert swap_in.base_amount == Decimal("91.799939"), (
            f"Expected 91.799939, got {swap_in.base_amount}"
        )

        # Both should share the same timestamp
        assert swap_out.timestamp_utc == swap_in.timestamp_utc

    def test_send_rows_are_transfer_out(self, coinbase_csv):
        """Test that Send rows produce TRANSFER_OUT transactions."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        transfer_outs = [tx for tx in result.transactions if tx.event_type == "TRANSFER_OUT"]

        # Should have 3: Send ALEO, Send SOL, Send VET
        assert len(transfer_outs) == 3, f"Expected 3 TRANSFER_OUT, got {len(transfer_outs)}"

        # Verify first Send (ALEO) has to_address
        aleo_send = next(tx for tx in transfer_outs if tx.base_coin == "ALEO")
        assert aleo_send.to_address is not None
        assert (
            "aleo1ml4jys95lhw35zj6fqfsp9e9ws54v2h2ke85fnnqmcqc0ndczy8svwk9eq"
            in aleo_send.to_address
        )

    def test_receive_rows_are_transfer_in(self, coinbase_csv):
        """Test that Receive rows produce TRANSFER_IN transactions."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        transfer_ins = [tx for tx in result.transactions if tx.event_type == "TRANSFER_IN"]

        # Should have 3: 2x Receive SOL, 1x Receive HNT
        assert len(transfer_ins) == 3, f"Expected 3 TRANSFER_IN, got {len(transfer_ins)}"

        # Verify first Receive (SOL) has from_address and to_address
        sol_receive = next(tx for tx in transfer_ins if tx.base_coin == "SOL")
        assert sol_receive.from_address is not None
        assert sol_receive.to_address is not None

    def test_buy_row_has_correct_fields(self, coinbase_csv):
        """Test Buy row has correct fields including price_sek and fee."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        buy_txs = [tx for tx in result.transactions if tx.event_type == "BUY"]

        assert len(buy_txs) == 1, f"Expected 1 BUY, got {len(buy_txs)}"

        buy_tx = buy_txs[0]
        assert buy_tx.base_coin == "SOL"
        assert buy_tx.base_amount == Decimal("0.095555476")
        assert buy_tx.quote_coin == "SEK"
        assert buy_tx.price_sek is not None
        assert buy_tx.fee_amount is not None
        # Price at Transaction: kr1580.28855229794772202483065
        assert buy_tx.price_sek == Decimal("1580.28855229794772202483065")

    def test_send_aleo_to_address_extraction(self, coinbase_csv):
        """Test address extraction from Send Notes."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        aleo_send = next(
            tx
            for tx in result.transactions
            if tx.base_coin == "ALEO" and tx.event_type == "TRANSFER_OUT"
        )

        # Notes: "Sent 91.799939 ALEO to aleo1ml4jys95lhw35zj6fqfsp9e9ws54v2h2ke85fnnqmcqc0ndczy8svwk9eq (to aleo1...wk9eq)"
        assert aleo_send.to_address is not None
        assert (
            "aleo1ml4jys95lhw35zj6fqfsp9e9ws54v2h2ke85fnnqmcqc0ndczy8svwk9eq"
            in aleo_send.to_address
        )

    def test_receive_sol_address_extraction(self, coinbase_csv):
        """Test address extraction from Receive Notes."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        # First SOL receive: "Received 0.04268882 SOL from an external account (from 5LWTG...eDgHg to 5FhSP...MAVXk)"
        sol_receive = next(
            tx
            for tx in result.transactions
            if tx.base_coin == "SOL" and tx.event_type == "TRANSFER_IN"
        )

        assert sol_receive.from_address is not None
        assert sol_receive.to_address is not None
        assert "5LWTG" in sol_receive.from_address
        assert "5FhSP" in sol_receive.to_address

    def test_raw_payload_populated(self, coinbase_csv):
        """Test that raw_payload is populated for each transaction."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        for tx in result.transactions:
            assert tx.raw_payload is not None, f"Transaction {tx} should have raw_payload"
            assert isinstance(tx.raw_payload, dict)
            # Verify it contains the original CSV data
            assert "ID" in tx.raw_payload
            assert "Transaction Type" in tx.raw_payload

    def test_source_platform_is_coinbase(self, coinbase_csv):
        """Test that source_platform is set to COINBASE."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        for tx in result.transactions:
            assert tx.source_platform == "COINBASE", f"Expected COINBASE, got {tx.source_platform}"

    def test_timestamp_parsing(self, coinbase_csv):
        """Test that timestamps are parsed correctly as UTC."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        # First row timestamp: "2025-09-08 10:46:38 UTC"
        aleo_send = next(tx for tx in result.transactions if tx.base_coin == "ALEO")

        assert aleo_send.timestamp_utc.year == 2025
        assert aleo_send.timestamp_utc.month == 9
        assert aleo_send.timestamp_utc.day == 8
        assert aleo_send.timestamp_utc.hour == 10
        assert aleo_send.timestamp_utc.minute == 46
        assert aleo_send.timestamp_utc.second == 38
        assert aleo_send.timestamp_utc.tzinfo is not None  # Should be UTC

    def test_fee_parsing(self, coinbase_csv):
        """Test that fees are parsed correctly, including negative fees."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        # Convert row has negative fee: "-kr2.04816798965982"
        convert_tx = next(
            tx
            for tx in result.transactions
            if tx.base_coin == "XRP" and tx.event_type == "SWAP_OUT"
        )

        assert convert_tx.fee_amount is not None
        assert convert_tx.fee_amount < 0, f"Fee should be negative, got {convert_tx.fee_amount}"

    def test_price_sek_parsing_strips_kr_prefix(self, coinbase_csv):
        """Test that price_sek correctly strips 'kr' prefix."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        # First row: "kr2.201200722149897974117269"
        aleo_send = next(tx for tx in result.transactions if tx.base_coin == "ALEO")

        assert aleo_send.price_sek is not None
        # Should strip 'kr' prefix
        price_sek_str = str(aleo_send.price_sek)
        assert price_sek_str.startswith("2.20") or price_sek_str.startswith("2.2")

    def test_error_handling_malformed_row(self):
        """Test that parser handles malformed rows without crashing."""
        # Create a temporary malformed CSV
        malformed_csv = """ID,Timestamp,Transaction Type,Asset,Quantity Transacted,Price Currency,Price at Transaction,Subtotal,Total (inclusive of fees and/or spread),Fees and/or Spread,Notes
malformed_row,2025-01-01 12:00:00 UTC,Buy,BTC,not_a_number,SEK,kr100,100,100,kr1,Test"""

        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(malformed_csv)
            temp_path = Path(f.name)

        try:
            parser = CoinbaseParser()
            result = parser.parse(temp_path)

            # Parser should not crash, should collect errors
            assert len(result.errors) > 0, "Should have collected errors for malformed row"
            # Should still return empty or partial results
            assert isinstance(result.transactions, list)
        finally:
            temp_path.unlink()

    def test_transaction_type_mapping(self, coinbase_csv):
        """Test that all transaction types are correctly mapped."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        event_types = {tx.event_type for tx in result.transactions}

        # Should have: BUY, SWAP_OUT, SWAP_IN, TRANSFER_IN, TRANSFER_OUT
        assert "BUY" in event_types
        assert "SWAP_OUT" in event_types
        assert "SWAP_IN" in event_types
        assert "TRANSFER_IN" in event_types
        assert "TRANSFER_OUT" in event_types

        # Should NOT have: SELL, REWARD (unless in fixture)
        assert "SELL" not in event_types
        assert "REWARD" not in event_types

    def test_convert_swap_out_and_in_share_metadata(self, coinbase_csv):
        """Test that SWAP_OUT and SWAP_IN from same Convert share timestamp and metadata."""
        parser = CoinbaseParser()
        result = parser.parse(coinbase_csv)

        # Group by timestamp to find matching pairs
        timestamp_groups = {}
        for tx in result.transactions:
            if tx.event_type in ("SWAP_OUT", "SWAP_IN"):
                key = tx.timestamp_utc
                if key not in timestamp_groups:
                    timestamp_groups[key] = []
                timestamp_groups[key].append(tx)

        # Each Convert should have 2 transactions (SWAP_OUT + SWAP_IN)
        for txs in timestamp_groups.values():
            if len(txs) == 2:
                swap_out = next(tx for tx in txs if tx.event_type == "SWAP_OUT")
                swap_in = next(tx for tx in txs if tx.event_type == "SWAP_IN")

                assert swap_out.timestamp_utc == swap_in.timestamp_utc
                assert swap_out.source_platform == swap_in.source_platform


class TestParseResult:
    """Tests for ParseResult dataclass."""

    def test_parse_result_has_transactions_and_errors(self):
        """Test that ParseResult contains transactions and errors."""

        result = ParseResult(
            transactions=[
                TransactionCreate(
                    source_platform="COINBASE",
                    timestamp_utc=datetime(2025, 1, 1, tzinfo=UTC),
                    event_type="BUY",
                    base_coin="BTC",
                    base_amount=Decimal("1"),
                )
            ],
            errors=["Some error"],
        )

        assert len(result.transactions) == 1
        assert len(result.errors) == 1
