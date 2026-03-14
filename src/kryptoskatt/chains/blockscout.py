"""Blockscout adapter for chains with a Blockscout-based explorer.

Blockscout exposes an Etherscan-compatible API (same module/action format)
but chain-specific base URL and no chainid parameter.
No API key required for public instances.

Docs: https://docs.blockscout.com/devs/apis/rpc/eth-rpc
"""

import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate

logger = logging.getLogger(__name__)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# chain → (explorer_base_url, native_coin)
CHAIN_CONFIG: dict[Chain, tuple[str, str]] = {
    Chain.MXC_ZKEVM: ("https://explorer.moonchain.com/api", "MXC"),
    Chain.ALEO: ("https://aleo.blockscout.com/api", "ALEO"),
}


class BlockscoutAdapter(ChainAdapter):
    """Adapter for Blockscout-based chain explorers."""

    def supported_chains(self) -> list[Chain]:
        return list(CHAIN_CONFIG.keys())

    def rate_limit_delay(self) -> float:
        return 0.25

    def fetch_transactions(self, address: str, chain: Chain) -> list[TransactionCreate]:
        base_url, native_coin = CHAIN_CONFIG[chain]
        results: list[TransactionCreate] = []

        results.extend(self._fetch(base_url, address, "txlist", False, native_coin))
        time.sleep(self.rate_limit_delay())
        results.extend(self._fetch(base_url, address, "tokentx", True, native_coin))

        return results

    def _fetch(
        self,
        base_url: str,
        address: str,
        action: str,
        is_token: bool,
        native_coin: str,
        start_block: int = 0,
    ) -> list[TransactionCreate]:
        results: list[TransactionCreate] = []
        current_block = start_block

        while True:
            params = {
                "module": "account",
                "action": action,
                "address": address,
                "startblock": current_block,
                "endblock": 99999999,
                "sort": "asc",
            }
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(base_url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
            except Exception as e:
                logger.error("Blockscout fetch error (%s %s): %s", action, address, e)
                break

            if data.get("status") == "0":
                msg = data.get("message", "")
                if "No transactions" not in msg:
                    logger.warning("Blockscout %s: %s", action, msg)
                break

            batch = data.get("result", [])
            if not isinstance(batch, list) or not batch:
                break

            for raw in batch:
                tx = self._convert(raw, address, is_token, native_coin)
                if tx:
                    results.append(tx)

            if len(batch) < 10000:
                break

            current_block = int(batch[-1].get("blockNumber", 0)) + 1
            time.sleep(self.rate_limit_delay())

        return results

    def _convert(
        self,
        tx: dict[str, Any],
        address: str,
        is_token: bool,
        native_coin: str,
    ) -> TransactionCreate | None:
        from_addr = tx.get("from", "").lower()
        to_addr = tx.get("to", "").lower()
        our = address.lower()

        if is_token:
            token_symbol = (tx.get("tokenSymbol") or "UNKNOWN")[:100]
            try:
                decimals = int(tx.get("tokenDecimal", 18))
                amount = Decimal(tx.get("value", "0")) / Decimal(10**decimals)
            except Exception:
                return None

            if from_addr == ZERO_ADDRESS:
                event_type = EventType.REWARD
            elif to_addr == our:
                event_type = EventType.TRANSFER_IN
            elif from_addr == our:
                event_type = EventType.TRANSFER_OUT
            else:
                return None

            coin = token_symbol
            fee_coin = None
            fee_amount = None
        else:
            try:
                amount = Decimal(tx.get("value", "0")) / Decimal(10**18)
            except Exception:
                return None

            if from_addr == ZERO_ADDRESS:
                event_type = EventType.REWARD
            elif to_addr == our:
                event_type = EventType.TRANSFER_IN
            elif from_addr == our:
                event_type = EventType.TRANSFER_OUT
            else:
                return None

            coin = native_coin
            try:
                gas_used = Decimal(tx.get("gasUsed", "0"))
                gas_price = Decimal(tx.get("gasPrice", "0"))
                fee_amount = gas_used * gas_price / Decimal(10**18)
                fee_coin = native_coin if event_type == EventType.TRANSFER_OUT else None
            except Exception:
                fee_amount = None
                fee_coin = None

        try:
            timestamp_utc = datetime.fromtimestamp(int(tx.get("timeStamp", 0)))
        except Exception:
            timestamp_utc = datetime.now()

        return TransactionCreate(
            source_platform="BLOCKSCOUT",
            timestamp_utc=timestamp_utc,
            event_type=event_type.value,
            base_coin=coin,
            base_amount=amount,
            fee_coin=fee_coin,
            fee_amount=fee_amount,
            tx_hash=tx.get("hash"),
            from_address=tx.get("from") or None,
            to_address=tx.get("to") or None,
        )


class DynamicBlockscoutAdapter(BlockscoutAdapter):
    """Blockscout adapter for a single user-configured chain."""

    def __init__(self, chain_name: str, base_url: str, native_coin: str) -> None:
        self._chain_name = chain_name.upper()
        self._base_url = base_url
        self._native_coin = native_coin

    def supported_chains(self) -> list[str]:
        return [self._chain_name]

    def fetch_transactions(self, address: str, chain: str) -> list[TransactionCreate]:
        results: list[TransactionCreate] = []
        results.extend(self._fetch(self._base_url, address, "txlist", False, self._native_coin))
        time.sleep(self.rate_limit_delay())
        results.extend(self._fetch(self._base_url, address, "tokentx", True, self._native_coin))
        return results
