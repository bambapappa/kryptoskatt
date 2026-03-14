"""Tests for Crypto.com CSV parser."""

from datetime import datetime
from decimal import Decimal


class TestCryptoComParser:
    """Test suite for CryptoComParser."""

    def test_parse_full_fixture_returns_11_transactions(self, crypto_com_csv):
        """Test that parsing the full fixture returns exactly 11 transactions."""
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        assert len(result.transactions) == 11
        assert len(result.errors) == 0

    def test_crypto_exchange_produces_swap_out_and_swap_in(self, crypto_com_csv):
        """Test that crypto_exchange rows produce SWAP_OUT + SWAP_IN pairs."""
        from kryptoskatt.enums import EventType
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        # Find crypto_exchange transactions by checking raw_payload
        # (there should be 3 pairs = 6 transactions)
        exchange_txns = [
            t
            for t in result.transactions
            if t.raw_payload and t.raw_payload.get("Transaction Kind") == "crypto_exchange"
        ]

        # Should have 6 transactions from 3 exchange pairs
        assert len(exchange_txns) == 6

        # Check specific exchange: USDC > KDA (row 4)
        # Should have SWAP_OUT for USDC and SWAP_IN for KDA
        usdc_swap_out = next(
            (
                t
                for t in result.transactions
                if t.base_coin == "USDC" and t.event_type == EventType.SWAP_OUT
            ),
            None,
        )
        usdc_swap_in = next(
            (
                t
                for t in result.transactions
                if t.base_coin == "KDA" and t.event_type == EventType.SWAP_IN
            ),
            None,
        )

        assert usdc_swap_out is not None
        assert usdc_swap_in is not None
        assert usdc_swap_out.base_amount == Decimal("-15.846464")
        assert usdc_swap_in.base_amount == Decimal("62.2")

    def test_crypto_wallet_swap_credited_maps_to_swap_in(self, crypto_com_csv):
        """Test that crypto_wallet_swap_credited maps to SWAP_IN."""
        from kryptoskatt.enums import EventType
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        # Find the USDC credit (row 1)
        usdc_credit = next(
            (
                t
                for t in result.transactions
                if t.base_coin == "USDC" and t.event_type == EventType.SWAP_IN
            ),
            None,
        )

        assert usdc_credit is not None
        assert usdc_credit.base_amount == Decimal("0.0005754816")

    def test_crypto_wallet_swap_debited_maps_to_swap_out(self, crypto_com_csv):
        """Test that crypto_wallet_swap_debited maps to SWAP_OUT."""
        from kryptoskatt.enums import EventType
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        # Find the MXC debit (row 2)
        mxc_debit = next(
            (
                t
                for t in result.transactions
                if t.base_coin == "MXC" and t.event_type == EventType.SWAP_OUT
            ),
            None,
        )

        assert mxc_debit is not None
        assert mxc_debit.base_amount == Decimal("-4.0")

    def test_crypto_withdrawal_has_correct_tx_hash(self, crypto_com_csv):
        """Test that crypto_withdrawal rows have tx_hash populated."""
        from kryptoskatt.enums import EventType
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        # Find withdrawal transactions
        withdrawals = [t for t in result.transactions if t.event_type == EventType.TRANSFER_OUT]

        assert len(withdrawals) == 2

        # Check first withdrawal has correct tx_hash
        kda_withdrawal_1 = next(
            (t for t in withdrawals if t.tx_hash == "O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM"),
            None,
        )
        assert kda_withdrawal_1 is not None
        assert kda_withdrawal_1.base_coin == "KDA"
        assert kda_withdrawal_1.base_amount == Decimal("-62.2")

        # Check second withdrawal has correct tx_hash
        kda_withdrawal_2 = next(
            (t for t in withdrawals if t.tx_hash == "vqEqHZ9w_OqbBi0nkB4btwBjcIDok5C4H_qobE1LD84"),
            None,
        )
        assert kda_withdrawal_2 is not None
        assert kda_withdrawal_2.base_coin == "KDA"
        assert kda_withdrawal_2.base_amount == Decimal("-22.0")

    def test_all_amounts_are_decimal(self, crypto_com_csv):
        """Test that all amount fields are Decimal instances, never float."""
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        for txn in result.transactions:
            assert isinstance(txn.base_amount, Decimal), f"base_amount is {type(txn.base_amount)}"
            if txn.quote_amount is not None:
                assert isinstance(txn.quote_amount, Decimal), (
                    f"quote_amount is {type(txn.quote_amount)}"
                )
            if txn.fee_amount is not None:
                assert isinstance(txn.fee_amount, Decimal), f"fee_amount is {type(txn.fee_amount)}"
            if txn.price_sek is not None:
                assert isinstance(txn.price_sek, Decimal), f"price_sek is {type(txn.price_sek)}"

    def test_price_sek_is_per_unit_not_total(self, crypto_com_csv):
        """Test that price_sek is price per unit (native_amount / quantity), not total."""
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        # USDC > KDA exchange: native_amount=148.770511..., amount=-15.846464 USDC
        # Expected per-unit price = 148.770511... / 15.846464 ≈ 9.388 SEK/USDC
        usdc_swap_out = next(
            (
                t
                for t in result.transactions
                if t.base_coin == "USDC" and t.base_amount == Decimal("-15.846464")
            ),
            None,
        )
        assert usdc_swap_out is not None
        assert usdc_swap_out.price_sek is not None
        expected = Decimal("148.770511729359486628798839193") / Decimal("15.846464")
        assert abs(usdc_swap_out.price_sek - expected) < Decimal("0.0001")

    def test_fiat_purchase_apple_pay_maps_to_buy(self, crypto_com_csv):
        """Test that trading.crypto_purchase.apple_pay maps to BUY with per-unit price_sek."""
        from kryptoskatt.enums import EventType
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        mxc_buy = next(
            (t for t in result.transactions if t.base_coin == "MXC" and t.event_type == EventType.BUY),
            None,
        )

        assert mxc_buy is not None
        assert mxc_buy.base_amount == Decimal("1000.0")
        # price_sek = 500.00 / 1000.0 = 0.50 SEK/MXC
        assert mxc_buy.price_sek is not None
        assert abs(mxc_buy.price_sek - Decimal("0.50")) < Decimal("0.001")

    def test_raw_payload_populated(self, crypto_com_csv):
        """Test that raw_payload contains the original CSV row data."""
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        # Find a transaction and check raw_payload
        usdc_credit = next((t for t in result.transactions if t.base_coin == "USDC"), None)

        assert usdc_credit is not None
        assert usdc_credit.raw_payload is not None
        assert "Timestamp (UTC)" in usdc_credit.raw_payload
        assert "Currency" in usdc_credit.raw_payload
        assert "Amount" in usdc_credit.raw_payload

    def test_error_handling_malformed_row(self, tmp_path):
        """Test that malformed rows don't crash the parser and errors are collected."""
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        # Create a CSV with a malformed row (missing Amount)
        csv_content = """Timestamp (UTC),Transaction Description,Currency,Amount,To Currency,To Amount,Native Currency,Native Amount,Native Amount (in USD),Transaction Kind,Transaction Hash
2025-10-15 17:49:39,Withdraw KDA,KDA,,,SEK,141.5,15.35,crypto_withdrawal,O02IiV-dui-5rX45DexI_OSQFYJum0UgVD0YPPMVKuM
2025-10-15 17:48:05,USDC > KDA,USDC,-15.846464,KDA,62.2,SEK,148.77,16.14,crypto_exchange,"""

        csv_file = tmp_path / "malformed.csv"
        csv_file.write_text(csv_content)

        parser = CryptoComParser()
        result = parser.parse(csv_file)

        # Should have 1 valid transaction from the second row
        assert len(result.transactions) == 2  # SWAP_OUT + SWAP_IN from exchange
        # Should have 1 error from the malformed first row
        assert len(result.errors) >= 1

    def test_source_platform_is_crypto_com(self, crypto_com_csv):
        """Test that source_platform is set to CRYPTO_COM."""
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        for txn in result.transactions:
            assert txn.source_platform == "CRYPTO_COM"

    def test_timestamp_utc_is_datetime(self, crypto_com_csv):
        """Test that timestamp_utc is a datetime object with UTC timezone."""
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        for txn in result.transactions:
            assert isinstance(txn.timestamp_utc, datetime)
            assert txn.timestamp_utc.tzinfo is not None

    def test_exchange_quote_cross_reference(self, crypto_com_csv):
        """Test that crypto_exchange has correct quote_coin/quote_amount cross-references."""
        from kryptoskatt.enums import EventType
        from kryptoskatt.parsers.crypto_com import CryptoComParser

        parser = CryptoComParser()
        result = parser.parse(crypto_com_csv)

        # Find USDC > KDA exchange
        usdc_swap_out = next(
            (
                t
                for t in result.transactions
                if t.base_coin == "USDC" and t.event_type == EventType.SWAP_OUT
            ),
            None,
        )

        assert usdc_swap_out is not None
        # SWAP_OUT should have KDA as quote_coin with the amount received
        assert usdc_swap_out.quote_coin == "KDA"
        assert usdc_swap_out.quote_amount == Decimal("62.2")

        # Find KDA SWAP_IN (from the same exchange)
        kda_swap_in = next(
            (
                t
                for t in result.transactions
                if t.base_coin == "KDA" and t.event_type == EventType.SWAP_IN
            ),
            None,
        )

        assert kda_swap_in is not None
        # SWAP_IN should have USDC as quote_coin with the amount sent
        assert kda_swap_in.quote_coin == "USDC"
        assert kda_swap_in.quote_amount == Decimal("15.846464")
