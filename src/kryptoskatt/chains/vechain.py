"""VeChain Stats adapter for VeChain network transactions.

Docs: https://docs.vechainstats.com/
Rate limit: depends on tier (Business: 120/min, 7500/day).
Auth: X-API-Key header.
"""

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.config import settings
from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate
from kryptoskatt.utils.http import get_with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://api.vechainstats.com/v2"
PAGE_SIZE = 200


class VeChainAdapter(ChainAdapter):
    """Adapter for VeChain using the VeChain Stats API."""

    def __init__(self, api_key: str | None = None) -> None:
        # Optional per-account key; falls back to the instance key from settings.
        self._api_key = api_key

    @property
    def _key(self) -> str:
        return self._api_key or settings.vechainstats_api_key

    def supported_chains(self) -> list[Chain]:
        return [Chain.VECHAIN]

    def rate_limit_delay(self) -> float:
        return 0.5  # conservative — stays well under 120/min

    def fetch_transactions(self, address: str, chain: Chain) -> list[TransactionCreate]:
        if not self._key:
            logger.warning("VeChain Stats API key not configured")
            return []

        results: list[TransactionCreate] = []

        # VET native transfers
        results.extend(self._fetch_token_transfers(address, "vet", "VET", 18))
        time.sleep(self.rate_limit_delay())

        # VTHO energy transfers
        results.extend(self._fetch_token_transfers(address, "vtho", "VTHO", 18))
        time.sleep(self.rate_limit_delay())

        # VIP180 token transfers
        results.extend(self._fetch_token_transfers(address, "vip180", None, None))

        return results

    def _headers(self) -> dict:
        return {"X-API-Key": self._key}

    def _fetch_token_transfers(
        self,
        address: str,
        token_type: str,
        fixed_symbol: str | None,
        fixed_decimals: int | None,
    ) -> list[TransactionCreate]:
        results: list[TransactionCreate] = []
        page = 1

        while True:
            params = {
                "token_type": token_type,
                "address": address,
                "page": page,
                "sort": "asc",
            }
            try:
                resp = get_with_retry(
                    f"{BASE_URL}/account/token-transfers",
                    params=params,
                    headers=self._headers(),
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error("VeChain Stats fetch error (%s): %s", token_type, e)
                break

            if not data.get("status", {}).get("success"):
                logger.warning("VeChain Stats error: %s", data.get("status", {}).get("message"))
                break

            batch = data.get("data", [])
            for transfer in batch:
                tx = self._parse_transfer(
                    transfer, address, fixed_symbol, fixed_decimals
                )
                if tx:
                    results.append(tx)

            meta = data.get("meta", {})
            if page >= meta.get("pages", 1):
                break

            page += 1
            time.sleep(self.rate_limit_delay())

        return results

    def _parse_transfer(
        self,
        transfer: dict,
        address: str,
        fixed_symbol: str | None,
        fixed_decimals: int | None,
    ) -> TransactionCreate | None:
        sender = transfer.get("sender", "").lower()
        receiver = transfer.get("receiver", "").lower()
        our = address.lower()

        if sender == our:
            event_type = EventType.TRANSFER_OUT
        elif receiver == our:
            event_type = EventType.TRANSFER_IN
        else:
            return None

        symbol = fixed_symbol or (transfer.get("token_symbol") or "UNKNOWN")[:100]
        decimals = fixed_decimals if fixed_decimals is not None else int(transfer.get("token_decimals", 18))

        try:
            amount = Decimal(str(transfer.get("amount", "0"))) / Decimal(10**decimals)
        except Exception:
            return None

        if amount <= 0:
            return None

        ts = transfer.get("block_timestamp")
        timestamp_utc = (
            datetime.fromtimestamp(int(ts), tz=UTC)
            if ts else datetime.now(tz=UTC)
        )

        return TransactionCreate(
            source_platform="VECHAINSTATS",
            timestamp_utc=timestamp_utc,
            event_type=event_type.value,
            base_coin=symbol,
            base_amount=amount,
            fee_coin=None,
            fee_amount=None,
            tx_hash=transfer.get("txid"),
            from_address=transfer.get("sender") or None,
            to_address=transfer.get("receiver") or None,
        )
