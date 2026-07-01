"""Tests for SolscanAdapter - Solana chain adapter."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from kryptoskatt.chains.solscan import SolscanAdapter
from kryptoskatt.enums import Chain, EventType


def _mock_response(data: dict) -> MagicMock:
    """Build a mock httpx.Response-like object."""
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status = MagicMock()
    return m


class TestSolscanAdapter:
    """Test suite for SolscanAdapter."""

    @pytest.fixture
    def adapter(self):
        """Create adapter instance."""
        return SolscanAdapter()

    @pytest.fixture
    def our_address(self):
        """Our test wallet address."""
        return "CAGfWWXbwW3NkbkHFxbhXn1RU7kywHTDaSipsRKeLhR8"

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with API key."""
        with patch("kryptoskatt.chains.solscan.settings") as mock:
            mock.solscan_api_key = "test_api_key_123"
            yield mock

    # --- Basic Tests ---

    def test_supported_chains(self, adapter):
        """Returns [Chain.SOLANA]."""
        result = adapter.supported_chains()
        assert result == [Chain.SOLANA]

    def test_rate_limit_delay(self, adapter):
        """Returns 0.5 seconds."""
        assert adapter.rate_limit_delay() == 0.5

    # --- SOL Transfer Tests ---

    def test_fetch_sol_transfer_in(self, adapter, our_address, mock_settings):
        """Mock SOL transfer where our address is receiver → TRANSFER_IN."""
        sol_data = {
            "success": True,
            "data": [
                {
                    "txHash": "abc123soltransfer",
                    "blockTime": 1704067200,  # 2024-01-01 00:00:00 UTC
                    "slot": 12345,
                    "fee": 5000,
                    "status": "Success",
                    "signer": ["sender_address"],
                    "parsedInstruction": [
                        {
                            "type": "sol-transfer",
                            "program": "system",
                            "programId": "11111111111111111111111111111111",
                            "params": {
                                "source": "sender_address",
                                "destination": our_address,
                                "amount": 1000000000,  # 1 SOL in lamports
                            },
                        }
                    ],
                }
            ],
        }
        empty = {"success": True, "data": []}

        with patch(
            "kryptoskatt.chains.solscan.get_with_retry",
            side_effect=[_mock_response(sol_data), _mock_response(empty)],
        ):
            result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        assert len(result) == 1
        tx = result[0]
        assert tx.event_type == EventType.TRANSFER_IN
        assert tx.base_coin == "SOL"
        assert tx.base_amount == Decimal("1.0")
        assert tx.tx_hash == "abc123soltransfer"
        assert tx.from_address == "sender_address"
        assert tx.to_address == our_address

    def test_fetch_sol_transfer_out(self, adapter, our_address, mock_settings):
        """Mock where our address is sender → TRANSFER_OUT."""
        sol_data = {
            "success": True,
            "data": [
                {
                    "txHash": "def456solout",
                    "blockTime": 1704153600,  # 2024-01-02
                    "slot": 12346,
                    "fee": 5000,
                    "status": "Success",
                    "signer": [our_address],
                    "parsedInstruction": [
                        {
                            "type": "sol-transfer",
                            "program": "system",
                            "programId": "11111111111111111111111111111111",
                            "params": {
                                "source": our_address,
                                "destination": "receiver_address",
                                "amount": 500000000,  # 0.5 SOL
                            },
                        }
                    ],
                }
            ],
        }
        empty = {"success": True, "data": []}

        with patch(
            "kryptoskatt.chains.solscan.get_with_retry",
            side_effect=[_mock_response(sol_data), _mock_response(empty)],
        ):
            result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        assert len(result) == 1
        tx = result[0]
        assert tx.event_type == EventType.TRANSFER_OUT
        assert tx.base_coin == "SOL"
        assert tx.base_amount == Decimal("0.5")

    def test_lamport_to_sol_conversion(self, adapter):
        """1000000000 lamports → Decimal('1.0') SOL."""
        lamports = 1000000000
        amount = Decimal(lamports) / Decimal(10**9)
        assert amount == Decimal("1.0")

    # --- SPL Token Transfer Tests ---

    def test_spl_token_transfer(self, adapter, our_address, mock_settings):
        """Mock SPL transfer with GEOD token → correct amount and symbol."""
        sol_empty = {"success": True, "data": []}
        spl_data = {
            "success": True,
            "data": [
                {
                    "txHash": "def456geod",
                    "blockTime": 1704067200,
                    "from": "sender_address",
                    "to": our_address,
                    "amount": 12000000,  # 12 GEOD with 6 decimals
                    "tokenAddress": "GEOD_TOKEN_MINT",
                    "tokenSymbol": "GEOD",
                    "tokenDecimals": 6,
                    "changeType": "inc",
                }
            ],
        }

        with patch(
            "kryptoskatt.chains.solscan.get_with_retry",
            side_effect=[_mock_response(sol_empty), _mock_response(spl_data)],
        ):
            result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        spl_txs = [tx for tx in result if tx.base_coin == "GEOD"]
        assert len(spl_txs) == 1
        tx = spl_txs[0]
        assert tx.base_coin == "GEOD"
        assert tx.base_amount == Decimal("12.0")
        assert tx.tx_hash == "def456geod"

    def test_geod_reward_classified_as_reward(self, adapter, our_address, mock_settings):
        """Transfer from DePIN distribution address → REWARD (not TRANSFER_IN)."""
        depin_address = "FceP6wv4GkdG7GfMDspRewardAddr"

        sol_empty = {"success": True, "data": []}
        spl_data = {
            "success": True,
            "data": [
                {
                    "txHash": "reward_tx_123",
                    "blockTime": 1704067200,
                    "from": depin_address,
                    "to": our_address,
                    "amount": 12000000,  # 12 GEOD
                    "tokenAddress": "GEOD_TOKEN_MINT",
                    "tokenSymbol": "GEOD",
                    "tokenDecimals": 6,
                    "changeType": "inc",
                }
            ],
        }

        with patch(
            "kryptoskatt.chains.solscan.get_with_retry",
            side_effect=[_mock_response(sol_empty), _mock_response(spl_data)],
        ):
            result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        reward_txs = [tx for tx in result if tx.event_type == EventType.REWARD]
        assert len(reward_txs) == 1
        assert reward_txs[0].base_coin == "GEOD"
        assert reward_txs[0].base_amount == Decimal("12.0")

    # --- Edge Cases ---

    def test_no_transactions_returns_empty(self, adapter, our_address, mock_settings):
        """Empty API response → empty list."""
        empty = {"success": True, "data": []}

        with patch(
            "kryptoskatt.chains.solscan.get_with_retry",
            return_value=_mock_response(empty),
        ):
            result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        assert result == []

    def test_api_error_handled_gracefully(self, adapter, our_address, mock_settings, caplog):
        """API error → logged, empty result."""
        import logging

        with patch(
            "kryptoskatt.chains.solscan.get_with_retry",
            side_effect=Exception("Connection error"),
        ):
            with caplog.at_level(logging.ERROR):
                result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        assert result == []
        assert any("Error" in record.message for record in caplog.records)

    def test_api_key_sent_as_header(self, adapter, our_address, mock_settings):
        """Verify get_with_retry is called with 'token' header."""
        empty = {"success": True, "data": []}

        with patch(
            "kryptoskatt.chains.solscan.get_with_retry",
            return_value=_mock_response(empty),
        ) as mock_get:
            adapter.fetch_transactions(our_address, Chain.SOLANA)

        mock_get.assert_called()
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["headers"]["token"] == "test_api_key_123"

    def test_all_amounts_are_decimal(self, adapter):
        """All returned amounts are Decimal instances."""
        # Test SOL conversion
        lamports = 1500000000
        amount = Decimal(lamports) / Decimal(10**9)
        assert isinstance(amount, Decimal)
        assert amount == Decimal("1.5")

        # Test SPL token conversion
        raw_amount = 25000000  # 25 GEOD
        decimals = 6
        amount = Decimal(raw_amount) / Decimal(10**decimals)
        assert isinstance(amount, Decimal)
        assert amount == Decimal("25.0")

    def test_tx_hash_populated(self, adapter, our_address, mock_settings):
        """Transaction hash populated from API response."""
        sol_data = {
            "success": True,
            "data": [
                {
                    "txHash": "test_tx_hash_123",
                    "blockTime": 1704067200,
                    "signer": ["sender"],
                    "parsedInstruction": [
                        {
                            "type": "sol-transfer",
                            "program": "system",
                            "programId": "11111111111111111111111111111111",
                            "params": {
                                "source": "sender",
                                "destination": our_address,
                                "amount": 1000000000,
                            },
                        }
                    ],
                }
            ],
        }
        empty = {"success": True, "data": []}

        with patch(
            "kryptoskatt.chains.solscan.get_with_retry",
            side_effect=[_mock_response(sol_data), _mock_response(empty)],
        ):
            result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        assert len(result) == 1
        assert result[0].tx_hash == "test_tx_hash_123"

    def test_no_api_key_returns_empty(self, adapter, our_address):
        """If API key is empty, return empty list with warning."""
        with patch("kryptoskatt.chains.solscan.settings") as mock:
            mock.solscan_api_key = ""

            result = adapter.fetch_transactions(our_address, Chain.SOLANA)

            assert result == []
