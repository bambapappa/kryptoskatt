"""Subscan API adapter for Substrate-based chains (PEAQ etc.).

Docs: https://support.subscan.io/#api-endpoints
Rate limit: 5 req/s, 100k req/day per API key.
"""

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.utils.http import post_with_retry
from kryptoskatt.config import settings
from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate

logger = logging.getLogger(__name__)

PAGE_SIZE = 100

# Network slug and native token per chain
CHAIN_CONFIG: dict[Chain, tuple[str, str, int]] = {
    # chain → (subscan_network, native_coin, decimals)
    Chain.PEAQ: ("peaq", "PEAQ", 18),
}


class SubscanAdapter(ChainAdapter):
    """Adapter for Substrate-based chains via the Subscan API."""

    def supported_chains(self) -> list[Chain]:
        return list(CHAIN_CONFIG.keys())

    def rate_limit_delay(self) -> float:
        # 5 req/s max — stay safely under
        return 0.25

    def fetch_transactions(self, address: str, chain: Chain) -> list[TransactionCreate]:
        if not settings.subscan_api_key:
            logger.warning("Subscan API key not configured")
            return []

        network, native_coin, decimals = CHAIN_CONFIG[chain]
        results: list[TransactionCreate] = []
        page = 0

        while True:
            batch = self._fetch_transfers_page(network, address, page)
            if batch is None:
                break

            for transfer in batch:
                tx = self._parse_transfer(transfer, address, native_coin, decimals)
                if tx:
                    results.append(tx)

            if len(batch) < PAGE_SIZE:
                break

            page += 1
            time.sleep(self.rate_limit_delay())

        return results

    def _fetch_transfers_page(
        self, network: str, address: str, page: int
    ) -> list[dict] | None:
        url = f"https://{network}.api.subscan.io/api/v2/scan/transfers"
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": settings.subscan_api_key,
        }
        payload = {
            "address": address,
            "row": PAGE_SIZE,
            "page": page,
            "direction": "all",
        }

        try:
            resp = post_with_retry(url, json=payload, headers=headers, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Subscan fetch error (%s page %d): %s", network, page, e)
            return None

        if data.get("code") != 0:
            logger.warning("Subscan API error: %s", data.get("message", "unknown"))
            return None

        return data.get("data", {}).get("transfers") or []

    def _parse_transfer(
        self,
        transfer: dict,
        address: str,
        native_coin: str,
        decimals: int,
    ) -> TransactionCreate | None:
        if not transfer.get("success"):
            return None

        from_addr = transfer.get("from", "")
        to_addr = transfer.get("to", "")

        if from_addr == address:
            event_type = EventType.TRANSFER_OUT
        elif to_addr == address:
            event_type = EventType.TRANSFER_IN
        else:
            return None

        # amount is a human-readable string like "1.5" from Subscan
        try:
            amount = Decimal(str(transfer.get("amount", "0")))
        except Exception:
            amount = Decimal("0")

        try:
            fee = Decimal(str(transfer.get("fee", "0")))
        except Exception:
            fee = Decimal("0")

        # Subscan returns the token symbol; fall back to native coin
        coin = transfer.get("asset_symbol") or transfer.get("token") or native_coin

        ts = transfer.get("block_timestamp")
        if ts:
            timestamp_utc = datetime.fromtimestamp(int(ts), tz=UTC)
        else:
            timestamp_utc = datetime.now(tz=UTC)

        return TransactionCreate(
            source_platform="SUBSCAN",
            timestamp_utc=timestamp_utc,
            event_type=event_type.value,
            base_coin=coin[:100],
            base_amount=amount,
            fee_coin=native_coin if event_type == EventType.TRANSFER_OUT else None,
            fee_amount=fee if event_type == EventType.TRANSFER_OUT else None,
            tx_hash=transfer.get("hash"),
            from_address=from_addr or None,
            to_address=to_addr or None,
        )
