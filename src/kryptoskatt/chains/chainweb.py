"""Chainweb Data API adapter for Kadena (KDA).

Public API, no key required.
Docs: https://estats.chainweb.com
"""

import logging
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.utils.http import get_with_retry
from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate

logger = logging.getLogger(__name__)


class ChainwebAdapter(ChainAdapter):
    """Adapter for Kadena via the Chainweb Data API (estats.chainweb.com)."""

    BASE_URL = "https://estats.chainweb.com"
    PAGE_SIZE = 100

    def supported_chains(self) -> list[str]:
        return [Chain.KADENA]

    def rate_limit_delay(self) -> float:
        return 0.25

    def fetch_transactions(self, address: str, chain: str) -> list[TransactionCreate]:
        results: list[TransactionCreate] = []
        offset = 0

        while True:
            params = {
                "limit": self.PAGE_SIZE,
                "offset": offset,
            }
            url = f"{self.BASE_URL}/txs/account/{address}"
            try:
                resp = get_with_retry(url, params=params, timeout=30.0)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error("Chainweb fetch error (address=%s offset=%d): %s", address, offset, e)
                break

            items = data if isinstance(data, list) else data.get("items", [])
            if not items:
                break

            for raw in items:
                tx = self._convert(raw, address)
                if tx is not None:
                    results.append(tx)

            if len(items) < self.PAGE_SIZE:
                break

            offset += self.PAGE_SIZE
            time.sleep(self.rate_limit_delay())

        return results

    def _convert(self, raw: dict[str, Any], address: str) -> TransactionCreate | None:
        from_account = raw.get("fromAccount", "")
        to_account = raw.get("toAccount", "")

        if from_account == address:
            event_type = EventType.TRANSFER_OUT
        elif to_account == address:
            event_type = EventType.TRANSFER_IN
        else:
            return None

        token = raw.get("token") or "coin"
        # Normalize Kadena's native coin identifier to ticker symbol
        if token == "coin":
            coin = "KDA"
        else:
            # Token contracts look like "free.xyz" — use the part after the last dot
            coin = token.split(".")[-1].upper() if "." in token else token.upper()

        try:
            amount = Decimal(str(raw.get("amount", "0")))
        except InvalidOperation:
            logger.warning("Chainweb: invalid amount %r in tx %s", raw.get("amount"), raw.get("requestKey"))
            return None

        block_time = raw.get("blockTime")
        try:
            if block_time:
                # ISO8601 string, e.g. "2024-01-01T12:00:00.000Z"
                timestamp_utc = datetime.fromisoformat(block_time.replace("Z", "+00:00"))
            else:
                timestamp_utc = datetime.utcnow()
        except Exception:
            timestamp_utc = datetime.utcnow()

        return TransactionCreate(
            source_platform="CHAINWEB",
            timestamp_utc=timestamp_utc,
            event_type=event_type.value,
            base_coin=coin,
            base_amount=amount,
            tx_hash=raw.get("requestKey"),
            from_address=from_account or None,
            to_address=to_account or None,
        )
