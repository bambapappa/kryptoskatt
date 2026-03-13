"""Tests for EtherscanAdapter."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from kryptoskatt.chains.etherscan import EtherscanAdapter
from kryptoskatt.enums import Chain, EventType


class TestEtherscanAdapter:
    """Tests for EtherscanAdapter class."""

    @pytest.fixture
    def adapter(self):
        """Create adapter instance."""
        return EtherscanAdapter()

    def test_supported_chains(self, adapter):
        """Returns ETHEREUM, POLYGON, BNB, BASE, ARBITRUM."""
        chains = adapter.supported_chains()
        assert Chain.ETHEREUM in chains
        assert Chain.POLYGON in chains
        assert Chain.BNB in chains
        assert Chain.BASE in chains
        assert Chain.ARBITRUM in chains

    def test_chain_id_mapping(self, adapter):
        """ETHEREUM→1, POLYGON→137, BNB→56."""
        assert adapter.CHAIN_IDS[Chain.ETHEREUM] == 1
        assert adapter.CHAIN_IDS[Chain.POLYGON] == 137
        assert adapter.CHAIN_IDS[Chain.BNB] == 56

    def test_rate_limit_delay(self, adapter):
        """Returns 0.25."""
        assert adapter.rate_limit_delay() == 0.25

    @patch("kryptoskatt.chains.etherscan.settings")
    def test_fetch_normal_eth_transfer_in(self, mock_settings, adapter):
        """Mock API response with a normal tx where to_address matches → TRANSFER_IN."""
        mock_settings.etherscan_api_key = "test_api_key"

        our_address = "0x1234567890123456789012345678901234567890"

        normal_tx_response = {
            "status": "1",
            "message": "OK",
            "result": [
                {
                    "blockNumber": "12345",
                    "timeStamp": "1704067200",
                    "hash": "0xabc123def456",
                    "from": "0xsender1234567890123456789012345678901234",
                    "to": our_address,
                    "value": "1000000000000000000",
                    "gas": "21000",
                    "gasUsed": "21000",
                    "gasPrice": "20000000000",
                    "isError": "0",
                    "contractAddress": "",
                    "functionName": "",
                }
            ],
        }

        empty_response = {"status": "1", "message": "OK", "result": []}

        with patch("kryptoskatt.chains.etherscan.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = [
                MagicMock(json=lambda: normal_tx_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
            ]
            mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

            result = adapter.fetch_transactions(our_address, Chain.ETHEREUM)

        assert len(result) == 1
        tx = result[0]
        assert tx.event_type == EventType.TRANSFER_IN.value
        assert tx.base_coin == "ETH"
        assert tx.base_amount == Decimal("1.0")
        assert tx.tx_hash == "0xabc123def456"

    @patch("kryptoskatt.chains.etherscan.settings")
    def test_fetch_normal_eth_transfer_out(self, mock_settings, adapter):
        """Mock API response where from_address matches → TRANSFER_OUT."""
        mock_settings.etherscan_api_key = "test_api_key"

        our_address = "0x1234567890123456789012345678901234567890"

        normal_tx_response = {
            "status": "1",
            "message": "OK",
            "result": [
                {
                    "blockNumber": "12345",
                    "timeStamp": "1704067200",
                    "hash": "0xabc123def456",
                    "from": our_address,
                    "to": "0xreceiver1234567890123456789012345678901234",
                    "value": "500000000000000000",
                    "gas": "21000",
                    "gasUsed": "21000",
                    "gasPrice": "20000000000",
                    "isError": "0",
                    "contractAddress": "",
                    "functionName": "",
                }
            ],
        }

        empty_response = {"status": "1", "message": "OK", "result": []}

        with patch("kryptoskatt.chains.etherscan.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = [
                MagicMock(json=lambda: normal_tx_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
            ]
            mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

            result = adapter.fetch_transactions(our_address, Chain.ETHEREUM)

        assert len(result) == 1
        tx = result[0]
        assert tx.event_type == EventType.TRANSFER_OUT.value

    def test_wei_to_eth_conversion(self, adapter):
        """1000000000000000000 Wei → Decimal('1.0') ETH."""
        result = adapter._parse_eth_value("1000000000000000000")
        assert result == Decimal("1.0")

    @patch("kryptoskatt.chains.etherscan.settings")
    def test_erc20_token_transfer(self, mock_settings, adapter):
        """Mock ERC-20 transfer with tokenSymbol='USDC', tokenDecimal='6' → correct amount."""
        mock_settings.etherscan_api_key = "test_api_key"

        our_address = "0x1234567890123456789012345678901234567890"

        empty_response = {"status": "1", "message": "OK", "result": []}
        erc20_response = {
            "status": "1",
            "message": "OK",
            "result": [
                {
                    "blockNumber": "12345",
                    "timeStamp": "1704067200",
                    "hash": "0xabc123def456",
                    "from": "0xsender1234567890123456789012345678901234",
                    "to": our_address,
                    "value": "1000000",
                    "tokenName": "USD Coin",
                    "tokenSymbol": "USDC",
                    "tokenDecimal": "6",
                    "gas": "21000",
                    "gasUsed": "21000",
                    "gasPrice": "20000000000",
                    "isError": "0",
                    "contractAddress": "0xtoken123",
                }
            ],
        }

        with patch("kryptoskatt.chains.etherscan.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = [
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: erc20_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
            ]
            mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

            result = adapter.fetch_transactions(our_address, Chain.ETHEREUM)

        assert len(result) == 1
        tx = result[0]
        assert tx.base_coin == "USDC"
        assert tx.base_amount == Decimal("1.0")

    @patch("kryptoskatt.chains.etherscan.settings")
    def test_from_zero_address_is_reward(self, mock_settings, adapter):
        """tx from 0x0000...0000 → event_type REWARD."""
        mock_settings.etherscan_api_key = "test_api_key"

        our_address = "0x1234567890123456789012345678901234567890"

        normal_tx_response = {
            "status": "1",
            "message": "OK",
            "result": [
                {
                    "blockNumber": "12345",
                    "timeStamp": "1704067200",
                    "hash": "0xreward123",
                    "from": "0x0000000000000000000000000000000000000000",
                    "to": our_address,
                    "value": "500000000000000000",
                    "gas": "21000",
                    "gasUsed": "21000",
                    "gasPrice": "0",
                    "isError": "0",
                    "contractAddress": "",
                    "functionName": "",
                }
            ],
        }

        empty_response = {"status": "1", "message": "OK", "result": []}

        with patch("kryptoskatt.chains.etherscan.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = [
                MagicMock(json=lambda: normal_tx_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
            ]
            mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

            result = adapter.fetch_transactions(our_address, Chain.ETHEREUM)

        assert len(result) == 1
        tx = result[0]
        assert tx.event_type == EventType.REWARD.value

    @patch("kryptoskatt.chains.etherscan.settings")
    def test_no_transactions_returns_empty(self, mock_settings, adapter):
        """API returns status '0' with 'No transactions found' → empty list."""
        mock_settings.etherscan_api_key = "test_api_key"

        our_address = "0x1234567890123456789012345678901234567890"

        mock_response = {
            "status": "0",
            "message": "No transactions found",
            "result": [],
        }

        with patch("kryptoskatt.chains.etherscan.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response_obj
            mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

            result = adapter.fetch_transactions(our_address, Chain.ETHEREUM)

        assert result == []

    @patch("kryptoskatt.chains.etherscan.settings")
    def test_api_error_handled_gracefully(self, mock_settings, adapter, caplog):
        """API returns error → logged, empty result."""
        import logging

        mock_settings.etherscan_api_key = "test_api_key"

        our_address = "0x1234567890123456789012345678901234567890"

        mock_response = {
            "status": "0",
            "message": "Error: Invalid API key",
            "result": [],
        }

        with patch("kryptoskatt.chains.etherscan.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_response_obj = MagicMock()
            mock_response_obj.json.return_value = mock_response
            mock_response_obj.raise_for_status = MagicMock()
            mock_client.get.return_value = mock_response_obj
            mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

            with caplog.at_level(logging.WARNING):
                result = adapter.fetch_transactions(our_address, Chain.ETHEREUM)

        assert result == []
        assert any("API error" in record.message for record in caplog.records)

    @patch("kryptoskatt.chains.etherscan.settings")
    def test_all_amounts_are_decimal(self, mock_settings, adapter):
        """All returned amounts are Decimal instances."""
        mock_settings.etherscan_api_key = "test_api_key"

        our_address = "0x1234567890123456789012345678901234567890"

        normal_tx_response = {
            "status": "1",
            "message": "OK",
            "result": [
                {
                    "blockNumber": "12345",
                    "timeStamp": "1704067200",
                    "hash": "0xabc123def456",
                    "from": "0xsender1234567890123456789012345678901234",
                    "to": our_address,
                    "value": "1000000000000000000",
                    "gas": "21000",
                    "gasUsed": "21000",
                    "gasPrice": "20000000000",
                    "isError": "0",
                    "contractAddress": "",
                    "functionName": "",
                }
            ],
        }

        empty_response = {"status": "1", "message": "OK", "result": []}

        with patch("kryptoskatt.chains.etherscan.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = [
                MagicMock(json=lambda: normal_tx_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
            ]
            mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

            result = adapter.fetch_transactions(our_address, Chain.ETHEREUM)

        assert len(result) == 1
        tx = result[0]
        assert isinstance(tx.base_amount, Decimal)

    @patch("kryptoskatt.chains.etherscan.settings")
    def test_tx_hash_populated(self, mock_settings, adapter):
        """Transaction hash populated from API response."""
        mock_settings.etherscan_api_key = "test_api_key"

        our_address = "0x1234567890123456789012345678901234567890"
        tx_hash = "0xabc123def456789"

        normal_tx_response = {
            "status": "1",
            "message": "OK",
            "result": [
                {
                    "blockNumber": "12345",
                    "timeStamp": "1704067200",
                    "hash": tx_hash,
                    "from": "0xsender1234567890123456789012345678901234",
                    "to": our_address,
                    "value": "1000000000000000000",
                    "gas": "21000",
                    "gasUsed": "21000",
                    "gasPrice": "20000000000",
                    "isError": "0",
                    "contractAddress": "",
                    "functionName": "",
                }
            ],
        }

        empty_response = {"status": "1", "message": "OK", "result": []}

        with patch("kryptoskatt.chains.etherscan.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.get.side_effect = [
                MagicMock(json=lambda: normal_tx_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
                MagicMock(json=lambda: empty_response, raise_for_status=MagicMock()),
            ]
            mock_client_class.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_class.return_value.__exit__ = MagicMock(return_value=False)

            result = adapter.fetch_transactions(our_address, Chain.ETHEREUM)

        assert len(result) == 1
        assert result[0].tx_hash == tx_hash
