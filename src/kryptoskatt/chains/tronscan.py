"""Tronscan API adapter for TRON network transactions.

Docs: https://docs.tronscan.org/
Rate limit: 5 req/s, 100k req/day per API key.
"""

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.utils.http import get_with_retry
from kryptoskatt.config import settings
from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate

logger = logging.getLogger(__name__)

BASE_URL = "https://apilist.tronscanapi.com/api"
PAGE_SIZE = 50
SUN = Decimal("1000000")  # 1 TRX = 1,000,000 SUN


class TronscanAdapter(ChainAdapter):
    """Adapter for TRON using the Tronscan REST API."""

    def supported_chains(self) -> list[Chain]:
        return [Chain.TRON]

    def rate_limit_delay(self) -> float:
        return 0.25

    def fetch_transactions(self, address: str, chain: Chain) -> list[TransactionCreate]:
        if not settings.tronscan_api_key:
            logger.warning("Tronscan API key not configured")
            return []

        results: list[TransactionCreate] = []
        results.extend(self._fetch_trx_transfers(address))
        time.sleep(self.rate_limit_delay())
        results.extend(self._fetch_trc20_transfers(address))
        return results

    def _headers(self) -> dict:
        return {"TRON-PRO-API-KEY": settings.tronscan_api_key}

    def _fetch_trx_transfers(self, address: str) -> list[TransactionCreate]:
        """Fetch native TRX transfers."""
        results: list[TransactionCreate] = []
        start = 0

        while True:
            params = {
                "address": address,
                "limit": PAGE_SIZE,
                "start": start,
                "sort": "-timestamp",
                "count": "true",
                # Only confirmed TRX transfers (contract type 1)
                "filterTokenValue": 1,
            }
            try:
                resp = get_with_retry(
                    f"{BASE_URL}/new/transaction",
                    params=params,
                    headers=self._headers(),
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error("Tronscan TRX fetch error: %s", e)
                break

            batch = data.get("data", [])
            for tx in batch:
                parsed = self._parse_trx(tx, address)
                if parsed:
                    results.append(parsed)

            if len(batch) < PAGE_SIZE:
                break

            start += PAGE_SIZE
            time.sleep(self.rate_limit_delay())

        return results

    def _fetch_trc20_transfers(self, address: str) -> list[TransactionCreate]:
        """Fetch TRC20 token transfers."""
        results: list[TransactionCreate] = []
        start = 0

        while True:
            params = {
                "relatedAddress": address,
                "limit": PAGE_SIZE,
                "start": start,
                "count": "true",
            }
            try:
                resp = get_with_retry(
                    f"{BASE_URL}/token_trc20/transfers",
                    params=params,
                    headers=self._headers(),
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error("Tronscan TRC20 fetch error: %s", e)
                break

            batch = data.get("token_transfers", [])
            for tx in batch:
                parsed = self._parse_trc20(tx, address)
                if parsed:
                    results.append(parsed)

            if len(batch) < PAGE_SIZE:
                break

            start += PAGE_SIZE
            time.sleep(self.rate_limit_delay())

        return results

    def _parse_trx(self, tx: dict, address: str) -> TransactionCreate | None:
        # Only process successful TRX transfers
        if not tx.get("confirmed"):
            return None

        from_addr = tx.get("ownerAddress", "")
        to_addr = tx.get("toAddress", "")

        if from_addr == address:
            event_type = EventType.TRANSFER_OUT
        elif to_addr == address:
            event_type = EventType.TRANSFER_IN
        else:
            return None

        try:
            amount = Decimal(str(tx.get("amount", 0))) / SUN
        except Exception:
            return None

        if amount <= 0:
            return None

        # Fee in SUN
        try:
            fee = Decimal(str(tx.get("fee", 0))) / SUN
        except Exception:
            fee = Decimal("0")

        ts = tx.get("timestamp")
        timestamp_utc = (
            datetime.fromtimestamp(int(ts) / 1000, tz=UTC)
            if ts else datetime.now(tz=UTC)
        )

        return TransactionCreate(
            source_platform="TRONSCAN",
            timestamp_utc=timestamp_utc,
            event_type=event_type.value,
            base_coin="TRX",
            base_amount=amount,
            fee_coin="TRX" if event_type == EventType.TRANSFER_OUT else None,
            fee_amount=fee if event_type == EventType.TRANSFER_OUT else None,
            tx_hash=tx.get("hash"),
            from_address=from_addr or None,
            to_address=to_addr or None,
        )

    def _parse_trc20(self, tx: dict, address: str) -> TransactionCreate | None:
        from_addr = tx.get("from_address", "")
        to_addr = tx.get("to_address", "")

        if from_addr == address:
            event_type = EventType.TRANSFER_OUT
        elif to_addr == address:
            event_type = EventType.TRANSFER_IN
        else:
            return None

        token_info = tx.get("tokenInfo", {})
        symbol = (token_info.get("tokenAbbr") or token_info.get("tokenName") or "UNKNOWN")[:100]
        try:
            decimals = int(token_info.get("tokenDecimal", 6))
            amount = Decimal(str(tx.get("quant", 0))) / Decimal(10**decimals)
        except Exception:
            return None

        if amount <= 0:
            return None

        ts = tx.get("block_ts")
        timestamp_utc = (
            datetime.fromtimestamp(int(ts) / 1000, tz=UTC)
            if ts else datetime.now(tz=UTC)
        )

        return TransactionCreate(
            source_platform="TRONSCAN",
            timestamp_utc=timestamp_utc,
            event_type=event_type.value,
            base_coin=symbol,
            base_amount=amount,
            fee_coin=None,
            fee_amount=None,
            tx_hash=tx.get("transaction_id"),
            from_address=from_addr or None,
            to_address=to_addr or None,
        )
