"""XRP Ledger adapter using the public XRPL JSON-RPC API.

No API key required. Uses the community cluster: https://xrplcluster.com
Docs: https://xrpl.org/docs/references/http-websocket-apis/
"""

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate

logger = logging.getLogger(__name__)

RPC_URL = "https://xrplcluster.com"
DROPS = Decimal("1000000")  # 1 XRP = 1,000,000 drops
# XRPL epoch starts 2000-01-01 00:00:00 UTC
RIPPLE_EPOCH = 946684800
PAGE_SIZE = 200


class XrplAdapter(ChainAdapter):
    """Adapter for XRP Ledger — no API key required."""

    def supported_chains(self) -> list[Chain]:
        return [Chain.RIPPLE]

    def rate_limit_delay(self) -> float:
        return 0.25

    def fetch_transactions(self, address: str, chain: Chain) -> list[TransactionCreate]:
        results: list[TransactionCreate] = []
        marker = None

        while True:
            payload: dict = {
                "method": "account_tx",
                "params": [{
                    "account": address,
                    "limit": PAGE_SIZE,
                    "forward": True,
                }],
            }
            if marker:
                payload["params"][0]["marker"] = marker

            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(RPC_URL, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
            except Exception as e:
                logger.error("XRPL fetch error for %s: %s", address, e)
                break

            result = data.get("result", {})
            if result.get("error"):
                logger.warning("XRPL API error: %s", result.get("error_message", result["error"]))
                break

            for entry in result.get("transactions", []):
                if not entry.get("validated"):
                    continue
                tx = self._parse_tx(entry, address)
                if tx:
                    results.append(tx)

            marker = result.get("marker")
            if not marker:
                break

            time.sleep(self.rate_limit_delay())

        return results

    def _parse_tx(self, entry: dict, address: str) -> TransactionCreate | None:
        tx = entry.get("tx") or entry.get("tx_json", {})
        meta = entry.get("meta", {})

        # Only process successful transactions
        if meta.get("TransactionResult") != "tesSUCCESS":
            return None

        tx_type = tx.get("TransactionType", "")

        # Fee in drops (paid by the tx sender)
        try:
            fee_xrp = Decimal(str(tx.get("Fee", 0))) / DROPS
        except Exception:
            fee_xrp = Decimal("0")

        # Timestamp: XRPL date is seconds since Ripple epoch
        ripple_date = tx.get("date") or tx.get("close_time_iso")
        if isinstance(ripple_date, int):
            timestamp_utc = datetime.fromtimestamp(ripple_date + RIPPLE_EPOCH, tz=timezone.utc)
        else:
            timestamp_utc = datetime.now(tz=timezone.utc)

        tx_hash = tx.get("hash", "")

        if tx_type == "Payment":
            return self._parse_payment(tx, meta, address, fee_xrp, timestamp_utc, tx_hash)

        # Other tx types where we paid the fee (e.g. OfferCreate, TrustSet)
        sender = tx.get("Account", "")
        if sender == address and fee_xrp > 0:
            return TransactionCreate(
                source_platform="XRPL",
                timestamp_utc=timestamp_utc,
                event_type=EventType.FEE.value,
                base_coin="XRP",
                base_amount=fee_xrp,
                fee_coin=None,
                fee_amount=None,
                tx_hash=tx_hash,
                from_address=sender,
                to_address=None,
            )

        return None

    def _parse_payment(
        self,
        tx: dict,
        meta: dict,
        address: str,
        fee_xrp: Decimal,
        timestamp_utc: datetime,
        tx_hash: str,
    ) -> TransactionCreate | None:
        sender = tx.get("Account", "")
        recipient = tx.get("Destination", "")
        amount_raw = tx.get("Amount")

        if sender == address:
            event_type = EventType.TRANSFER_OUT
        elif recipient == address:
            event_type = EventType.TRANSFER_IN
        else:
            return None

        # XRP payment: Amount is a string of drops
        if isinstance(amount_raw, str):
            try:
                # Use delivered_amount from meta if available (more accurate for partial payments)
                delivered = meta.get("delivered_amount") or amount_raw
                amount = Decimal(str(delivered)) / DROPS
            except Exception:
                return None
            coin = "XRP"

        # IOU/token payment: Amount is {"currency": ..., "value": ..., "issuer": ...}
        elif isinstance(amount_raw, dict):
            try:
                delivered = meta.get("delivered_amount") or amount_raw
                if isinstance(delivered, dict):
                    amount = Decimal(str(delivered.get("value", "0")))
                    raw_currency = delivered.get("currency", "UNKNOWN")
                else:
                    amount = Decimal(str(amount_raw.get("value", "0")))
                    raw_currency = amount_raw.get("currency", "UNKNOWN")
            except Exception:
                return None

            # Hex currency codes are non-standard tokens — use hex[:6] as symbol
            if len(raw_currency) == 40:
                coin = raw_currency[:6]
            else:
                coin = raw_currency[:100]
        else:
            return None

        if amount <= 0:
            return None

        return TransactionCreate(
            source_platform="XRPL",
            timestamp_utc=timestamp_utc,
            event_type=event_type.value,
            base_coin=coin,
            base_amount=amount,
            fee_coin="XRP" if event_type == EventType.TRANSFER_OUT else None,
            fee_amount=fee_xrp if event_type == EventType.TRANSFER_OUT else None,
            tx_hash=tx_hash,
            from_address=sender or None,
            to_address=recipient or None,
        )
