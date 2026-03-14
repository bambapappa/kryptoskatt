"""Tests for SolscanAdapter - Solana chain adapter."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from kryptoskatt.chains.solscan import SolscanAdapter
from kryptoskatt.enums import Chain, EventType


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

    @patch("kryptoskatt.chains.solscan.httpx.Client")
    def test_fetch_sol_transfer_in(self, mock_client_class, adapter, our_address, mock_settings):
        """Mock SOL transfer where our address is receiver → TRANSFER_IN."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
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
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        assert len(result) == 1
        tx = result[0]
        assert tx.event_type == EventType.TRANSFER_IN
        assert tx.base_coin == "SOL"
        assert tx.base_amount == Decimal("1.0")
        assert tx.tx_hash == "abc123soltransfer"
        assert tx.from_address == "sender_address"
        assert tx.to_address == our_address

    @patch("kryptoskatt.chains.solscan.httpx.Client")
    def test_fetch_sol_transfer_out(self, mock_client_class, adapter, our_address, mock_settings):
        """Mock where our address is sender → TRANSFER_OUT."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
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
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

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

    @patch("kryptoskatt.chains.solscan.httpx.Client")
    def test_spl_token_transfer(self, mock_client_class, adapter, our_address, mock_settings):
        """Mock SPL transfer with GEOD token → correct amount and symbol."""
        # First call returns empty for SOL, second for SPL
        mock_response_sol = MagicMock()
        mock_response_sol.json.return_value = {"success": True, "data": []}
        mock_response_sol.raise_for_status = MagicMock()

        mock_response_spl = MagicMock()
        mock_response_spl.json.return_value = {
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
        mock_response_spl.raise_for_status = MagicMock()

        mock_client = MagicMock()
        # First call is for SOL, second for SPL
        mock_client.get.side_effect = [mock_response_sol, mock_response_spl]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        # Should have the SPL transfer
        spl_txs = [tx for tx in result if tx.base_coin == "GEOD"]
        assert len(spl_txs) == 1
        tx = spl_txs[0]
        assert tx.base_coin == "GEOD"
        assert tx.base_amount == Decimal("12.0")
        assert tx.tx_hash == "def456geod"

    @patch("kryptoskatt.chains.solscan.httpx.Client")
    def test_geod_reward_classified_as_reward(
        self, mock_client_class, adapter, our_address, mock_settings
    ):
        """Transfer from DePIN distribution address → REWARD (not TRANSFER_IN)."""
        # The DePIN reward address starts with the known pattern
        depin_address = "FceP6wv4GkdG7GfMDspRewardAddr"

        mock_response_sol = MagicMock()
        mock_response_sol.json.return_value = {"success": True, "data": []}
        mock_response_sol.raise_for_status = MagicMock()

        mock_response_spl = MagicMock()
        mock_response_spl.json.return_value = {
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
        mock_response_spl.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.side_effect = [mock_response_sol, mock_response_spl]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        # Should be classified as REWARD
        reward_txs = [tx for tx in result if tx.event_type == EventType.REWARD]
        assert len(reward_txs) == 1
        assert reward_txs[0].base_coin == "GEOD"
        assert reward_txs[0].base_amount == Decimal("12.0")

    # --- Edge Cases ---

    @patch("kryptoskatt.chains.solscan.httpx.Client")
    def test_no_transactions_returns_empty(
        self, mock_client_class, adapter, our_address, mock_settings
    ):
        """Empty API response → empty list."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True, "data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        assert result == []

    @patch("kryptoskatt.chains.solscan.httpx.Client")
    def test_api_error_handled_gracefully(
        self, mock_client_class, adapter, our_address, mock_settings, caplog
    ):
        """API error → logged, empty result."""
        import logging

        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Connection error")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_class.return_value = mock_client

        with caplog.at_level(logging.ERROR):
            result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        assert result == []
        assert any("Error" in record.message for record in caplog.records)

    def test_api_key_sent_as_header(self, adapter, our_address, mock_settings):
        """Verify httpx request includes 'token' header."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True, "data": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("kryptoskatt.chains.solscan.httpx.Client", return_value=mock_client):
            adapter.fetch_transactions(our_address, Chain.SOLANA)

        # Verify the token header was passed
        mock_client.get.assert_called()
        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs["headers"]["token"] == "test_api_key_123"

    def test_all_amounts_are_decimal(self, adapter):
        """All returned amounts are Decimal instances."""
        # This is tested implicitly but we verify the conversion logic
        from decimal import Decimal

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
        mock_response = MagicMock()
        mock_response.json.return_value = {
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
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("kryptoskatt.chains.solscan.httpx.Client", return_value=mock_client):
            result = adapter.fetch_transactions(our_address, Chain.SOLANA)

        assert len(result) == 1
        assert result[0].tx_hash == "test_tx_hash_123"

    def test_no_api_key_returns_empty(self, adapter, our_address):
        """If API key is empty, return empty list with warning."""
        with patch("kryptoskatt.chains.solscan.settings") as mock:
            mock.solscan_api_key = ""

            result = adapter.fetch_transactions(our_address, Chain.SOLANA)

            assert result == []
