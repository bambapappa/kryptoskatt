"""Edge-case tests for Coinbase and Crypto.com parsers."""

from decimal import Decimal
from pathlib import Path

from kryptoskatt.parsers.coinbase import CoinbaseParser
from kryptoskatt.parsers.crypto_com import CryptoComParser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_temp(content: str, suffix: str = ".csv") -> Path:
    """Write content to a NamedTemporaryFile and return its Path."""
    import tempfile as _tmp

    with _tmp.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as f:
        f.write(content)
        return Path(f.name)


# ---------------------------------------------------------------------------
# CoinbaseParser edge cases
# ---------------------------------------------------------------------------

class TestCoinbaseParserEdgeCases:
    """Edge cases not covered by the main test_coinbase_parser.py suite."""

    def test_unknown_transaction_type_produces_unknown_event_type(self):
        """A CSV row with an unrecognised Transaction Type maps to UNKNOWN."""
        csv_content = (
            "ID,Timestamp,Transaction Type,Asset,Quantity Transacted,"
            "Price Currency,Price at Transaction,Subtotal,"
            "Total (inclusive of fees and/or spread),Fees and/or Spread,Notes\n"
            "abc123,2025-01-15 10:00:00 UTC,Airdrop,SOL,1.5,"
            "SEK,kr100,150,155,kr5,Some airdrop note\n"
        )
        csv_path = _write_temp(csv_content)
        try:
            parser = CoinbaseParser()
            result = parser.parse(csv_path)

            assert len(result.transactions) == 1
            assert result.transactions[0].event_type == "UNKNOWN"
            assert result.transactions[0].base_coin == "SOL"
            assert result.transactions[0].base_amount == Decimal("1.5")
        finally:
            csv_path.unlink(missing_ok=True)

    def test_reward_transaction_type_produces_reward_event(self):
        """A 'Reward' row is mapped to the REWARD event type."""
        csv_content = (
            "ID,Timestamp,Transaction Type,Asset,Quantity Transacted,"
            "Price Currency,Price at Transaction,Subtotal,"
            "Total (inclusive of fees and/or spread),Fees and/or Spread,Notes\n"
            "rwd001,2025-03-01 08:00:00 UTC,Reward,ETH,0.001,"
            "SEK,kr25000,,,,Staking reward\n"
        )
        csv_path = _write_temp(csv_content)
        try:
            parser = CoinbaseParser()
            result = parser.parse(csv_path)

            assert len(result.transactions) == 1
            assert result.transactions[0].event_type == "REWARD"
            assert result.transactions[0].base_coin == "ETH"
        finally:
            csv_path.unlink(missing_ok=True)

    def test_convert_with_malformed_notes_falls_back_to_unknown(self):
        """A Convert row whose Notes don't match the expected pattern falls back to UNKNOWN."""
        csv_content = (
            "ID,Timestamp,Transaction Type,Asset,Quantity Transacted,"
            "Price Currency,Price at Transaction,Subtotal,"
            "Total (inclusive of fees and/or spread),Fees and/or Spread,Notes\n"
            "conv1,2025-04-01 12:00:00 UTC,Convert,BTC,0.01,"
            "SEK,kr450000,4500,4500,kr0,Something completely different\n"
        )
        csv_path = _write_temp(csv_content)
        try:
            parser = CoinbaseParser()
            result = parser.parse(csv_path)

            # When Convert notes can't be parsed the parser falls back to a
            # single UNKNOWN transaction rather than crashing.
            assert len(result.transactions) == 1
            assert result.transactions[0].event_type == "UNKNOWN"
        finally:
            csv_path.unlink(missing_ok=True)

    def test_sell_row_creates_sell_event(self):
        """A 'Sell' CSV row is mapped to a SELL event."""
        csv_content = (
            "ID,Timestamp,Transaction Type,Asset,Quantity Transacted,"
            "Price Currency,Price at Transaction,Subtotal,"
            "Total (inclusive of fees and/or spread),Fees and/or Spread,Notes\n"
            "sell1,2025-05-10 14:00:00 UTC,Sell,BTC,-0.005,"
            "SEK,kr450000,-2250,-2300,kr-50,Sold some BTC\n"
        )
        csv_path = _write_temp(csv_content)
        try:
            parser = CoinbaseParser()
            result = parser.parse(csv_path)

            assert len(result.transactions) == 1
            tx = result.transactions[0]
            assert tx.event_type == "SELL"
            assert tx.base_coin == "BTC"
            assert tx.quote_coin == "SEK"
        finally:
            csv_path.unlink(missing_ok=True)

    def test_malformed_row_collected_as_error_not_crash(self):
        """Rows where quantity is not a number produce an error entry, not a crash."""
        csv_content = (
            "ID,Timestamp,Transaction Type,Asset,Quantity Transacted,"
            "Price Currency,Price at Transaction,Subtotal,"
            "Total (inclusive of fees and/or spread),Fees and/or Spread,Notes\n"
            "bad1,2025-01-01 00:00:00 UTC,Buy,BTC,NOT_A_NUMBER,"
            "SEK,kr450000,4500,4500,kr0,\n"
        )
        csv_path = _write_temp(csv_content)
        try:
            parser = CoinbaseParser()
            result = parser.parse(csv_path)

            # Should not crash; the error is captured
            assert len(result.errors) >= 1
            assert isinstance(result.transactions, list)
        finally:
            csv_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# CryptoComParser edge cases
# ---------------------------------------------------------------------------

class TestCryptoComParserEdgeCases:
    """Edge cases not covered by the main test_crypto_com_parser.py suite."""

    def test_unknown_transaction_kind_is_skipped_silently(self):
        """An unrecognised Transaction Kind produces no transactions and no errors."""
        csv_content = (
            "Timestamp (UTC),Transaction Kind,Currency,Amount,"
            "To Currency,To Amount,Native Amount,Transaction Hash\n"
            "2025-01-15 10:00:00,referral_bonus,BTC,0.001,,,,\n"
        )
        csv_path = _write_temp(csv_content)
        try:
            parser = CryptoComParser()
            result = parser.parse(csv_path)

            # Unknown kinds are silently skipped
            assert len(result.transactions) == 0
            assert len(result.errors) == 0
        finally:
            csv_path.unlink(missing_ok=True)

    def test_crypto_deposit_produces_transfer_in(self):
        """A 'crypto_deposit' row is mapped to a TRANSFER_IN event."""
        csv_content = (
            "Timestamp (UTC),Transaction Kind,Currency,Amount,"
            "To Currency,To Amount,Native Amount,Transaction Hash\n"
            "2025-02-20 08:30:00,crypto_deposit,ETH,0.5,,,"
            "12500.00,0xabc123\n"
        )
        csv_path = _write_temp(csv_content)
        try:
            parser = CryptoComParser()
            result = parser.parse(csv_path)

            assert len(result.transactions) == 1
            tx = result.transactions[0]
            assert tx.event_type == "TRANSFER_IN"
            assert tx.base_coin == "ETH"
            assert tx.base_amount == Decimal("0.5")
        finally:
            csv_path.unlink(missing_ok=True)

    def test_crypto_withdrawal_produces_transfer_out(self):
        """A 'crypto_withdrawal' row is mapped to a TRANSFER_OUT event."""
        csv_content = (
            "Timestamp (UTC),Transaction Kind,Currency,Amount,"
            "To Currency,To Amount,Native Amount,Transaction Hash\n"
            "2025-03-10 15:00:00,crypto_withdrawal,SOL,-10.0,,,"
            "-2200.00,solhash001\n"
        )
        csv_path = _write_temp(csv_content)
        try:
            parser = CryptoComParser()
            result = parser.parse(csv_path)

            assert len(result.transactions) == 1
            tx = result.transactions[0]
            assert tx.event_type == "TRANSFER_OUT"
            assert tx.base_coin == "SOL"
        finally:
            csv_path.unlink(missing_ok=True)

    def test_malformed_timestamp_is_collected_as_error(self):
        """A row with an unparseable timestamp is captured as an error, not a crash."""
        csv_content = (
            "Timestamp (UTC),Transaction Kind,Currency,Amount,"
            "To Currency,To Amount,Native Amount,Transaction Hash\n"
            "NOT-A-DATE,crypto_deposit,BTC,0.001,,,,\n"
        )
        csv_path = _write_temp(csv_content)
        try:
            parser = CryptoComParser()
            result = parser.parse(csv_path)

            # Row-level exception must be caught and stored in errors
            assert len(result.errors) >= 1
            assert len(result.transactions) == 0
        finally:
            csv_path.unlink(missing_ok=True)
