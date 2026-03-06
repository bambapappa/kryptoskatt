"""Etherscan v2 API adapter for ETH and EVM chain transactions."""

import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.config import settings
from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate

logger = logging.getLogger(__name__)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class EtherscanAdapter(ChainAdapter):
    """Adapter for Etherscan v2 API — supports ETH and EVM-compatible chains."""

    CHAIN_IDS: dict[Chain, int] = {
        Chain.ETHEREUM: 1,
        Chain.POLYGON: 137,
        Chain.BNB: 56,
    }

    BASE_URL = "https://api.etherscan.io/v2/api"

    def supported_chains(self) -> list[Chain]:
        """Return list of chains this adapter handles."""
        return [Chain.ETHEREUM, Chain.POLYGON, Chain.BNB]

    def rate_limit_delay(self) -> float:
        """Seconds to wait between API calls. Free tier is 5 calls/sec."""
        return 0.25

    def fetch_transactions(self, address: str, chain: Chain) -> list[TransactionCreate]:
        """Fetch all transactions for an address on the given chain.

        Makes 3 API calls:
        - Normal transactions (txlist)
        - ERC-20 token transfers (tokentx)
        - Internal transactions (txlistinternal)
        """
        if not settings.etherscan_api_key:
            logger.warning("Etherscan API key not configured, returning empty list")
            return []

        chain_id = self.CHAIN_IDS.get(chain)
        if chain_id is None:
            logger.warning("Unsupported chain: %s", chain)
            return []

        results: list[TransactionCreate] = []

        # Fetch normal transactions
        normal_txs = self._fetch_normal_transactions(address, chain_id)
        results.extend(normal_txs)

        time.sleep(self.rate_limit_delay())

        # Fetch ERC-20 token transfers
        erc20_txs = self._fetch_erc20_transfers(address, chain_id)
        results.extend(erc20_txs)

        time.sleep(self.rate_limit_delay())

        # Fetch internal transactions
        internal_txs = self._fetch_internal_transactions(address, chain_id)
        results.extend(internal_txs)

        return results

    def _fetch_normal_transactions(self, address: str, chain_id: int) -> list[TransactionCreate]:
        """Fetch normal ETH/EVM transactions."""
        return self._fetch_with_pagination(
            address=address,
            chain_id=chain_id,
            action="txlist",
            is_erc20=False,
            our_address=address,
        )

    def _fetch_erc20_transfers(self, address: str, chain_id: int) -> list[TransactionCreate]:
        """Fetch ERC-20 token transfers."""
        return self._fetch_with_pagination(
            address=address,
            chain_id=chain_id,
            action="tokentx",
            is_erc20=True,
            our_address=address,
        )

    def _fetch_internal_transactions(self, address: str, chain_id: int) -> list[TransactionCreate]:
        """Fetch internal transactions."""
        return self._fetch_with_pagination(
            address=address,
            chain_id=chain_id,
            action="txlistinternal",
            is_erc20=False,
            our_address=address,
        )

    def _fetch_with_pagination(
        self,
        address: str,
        chain_id: int,
        action: str,
        is_erc20: bool,
        our_address: str,
        start_block: int = 0,
    ) -> list[TransactionCreate]:
        """Fetch transactions with pagination support.

        Etherscan returns max 10000 results. If we hit the limit,
        fetch more with pagination.
        """
        results: list[TransactionCreate] = []
        current_start_block = start_block

        while True:
            raw_txs = self._fetch_single_page(
                address=address,
                chain_id=chain_id,
                action=action,
                is_erc20=is_erc20,
                our_address=our_address,
                start_block=current_start_block,
            )

            if not raw_txs:
                break

            # Convert raw dicts to TransactionCreate objects
            for raw_tx in raw_txs:
                tx = self._convert_to_transaction(raw_tx, our_address, is_erc20)
                results.append(tx)

            # Check if we hit the limit and need pagination
            if len(raw_txs) < 10000:
                break

            # Get last block number and continue from next block
            last_block = int(raw_txs[-1].get("blockNumber", "0"))
            current_start_block = last_block + 1

        return results

    def _fetch_single_page(
        self,
        address: str,
        chain_id: int,
        action: str,
        is_erc20: bool,
        our_address: str,
        start_block: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch a single page of transactions."""
        params = {
            "chainid": chain_id,
            "module": "account",
            "action": action,
            "address": address,
            "startblock": start_block,
            "endblock": 99999999,
            "sort": "asc",
            "apikey": settings.etherscan_api_key,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as e:
            logger.error("HTTP error fetching %s: %s", action, e)
            return []
        except Exception as e:
            logger.error("Error fetching %s: %s", action, e)
            return []

        # Check for API-level errors
        status = data.get("status")
        message = data.get("message", "")

        if status == "0":
            if "No transactions found" in message:
                return []
            logger.warning("Etherscan API error for %s: %s", action, message)
            return []

        result = data.get("result")
        if not isinstance(result, list):
            return []

        return result

    def _classify_transaction(
        self, tx: dict[str, Any], our_address: str
    ) -> tuple[EventType, str, Decimal]:
        """Classify transaction and return event_type, base_coin, base_amount."""
        from_address = tx.get("from", "").lower()
        to_address = tx.get("to", "").lower()
        our_address_lower = our_address.lower()

        # Check if it's a reward (from zero address)
        if from_address == ZERO_ADDRESS:
            return EventType.REWARD, "ETH", self._parse_eth_value(tx.get("value", "0"))

        # Check if it's a transfer in or out
        if to_address == our_address_lower:
            event_type = EventType.TRANSFER_IN
        else:
            event_type = EventType.TRANSFER_OUT

        return event_type, "ETH", self._parse_eth_value(tx.get("value", "0"))

    def _classify_erc20_transaction(
        self, tx: dict[str, Any], our_address: str
    ) -> tuple[EventType, str, Decimal]:
        """Classify ERC-20 transaction and return event_type, base_coin, base_amount."""
        from_address = tx.get("from", "").lower()
        to_address = tx.get("to", "").lower()
        our_address_lower = our_address.lower()

        # Check if it's a reward (from zero address)
        if from_address == ZERO_ADDRESS:
            token_symbol = tx.get("tokenSymbol", "UNKNOWN")
            return (
                EventType.REWARD,
                token_symbol,
                self._parse_erc20_value(tx.get("value", "0"), tx.get("tokenDecimal", "18")),
            )

        # Check if it's a transfer in or out
        if to_address == our_address_lower:
            event_type = EventType.TRANSFER_IN
        else:
            event_type = EventType.TRANSFER_OUT

        token_symbol = tx.get("tokenSymbol", "UNKNOWN")
        return (
            event_type,
            token_symbol,
            self._parse_erc20_value(tx.get("value", "0"), tx.get("tokenDecimal", "18")),
        )

    def _parse_eth_value(self, raw_value: str) -> Decimal:
        """Parse ETH value from Wei to Decimal."""
        try:
            return Decimal(raw_value) / Decimal(10**18)
        except Exception:
            return Decimal("0")

    def _parse_erc20_value(self, raw_value: str, token_decimal: str) -> Decimal:
        """Parse ERC-20 token value using token decimals."""
        try:
            decimals = int(token_decimal) if token_decimal else 18
            return Decimal(raw_value) / Decimal(10**decimals)
        except Exception:
            return Decimal("0")

    def _convert_to_transaction(
        self,
        tx: dict[str, Any],
        our_address: str,
        is_erc20: bool = False,
    ) -> TransactionCreate:
        """Convert Etherscan transaction to TransactionCreate schema."""
        if is_erc20:
            event_type, base_coin, base_amount = self._classify_erc20_transaction(tx, our_address)
        else:
            event_type, base_coin, base_amount = self._classify_transaction(tx, our_address)

        # Parse timestamp
        timestamp_str = tx.get("timeStamp", "")
        try:
            timestamp_utc = datetime.fromtimestamp(int(timestamp_str))
        except Exception:
            timestamp_utc = datetime.now()

        # Parse gas fees
        gas_used = tx.get("gasUsed", "0")
        gas_price = tx.get("gasPrice", "0")
        try:
            fee_wei = Decimal(gas_used) * Decimal(gas_price)
            fee_amount = fee_wei / Decimal(10**18)
        except Exception:
            fee_amount = Decimal("0")

        return TransactionCreate(
            source_platform="ETHERSCAN",
            timestamp_utc=timestamp_utc,
            event_type=event_type.value,
            base_coin=base_coin,
            base_amount=base_amount,
            fee_coin="ETH" if not is_erc20 else tx.get("tokenSymbol", "UNKNOWN"),
            fee_amount=fee_amount if not is_erc20 else None,
            tx_hash=tx.get("hash"),
            from_address=tx.get("from"),
            to_address=tx.get("to"),
        )
