"""Bitcoin adapter using Blockstream.info API (no API key required)."""

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate

logger = logging.getLogger(__name__)

BASE_URL = "https://blockstream.info/api"
SATOSHI = Decimal("100000000")


class BitcoinAdapter(ChainAdapter):
    """Adapter for Bitcoin using the Blockstream.info REST API."""

    def supported_chains(self) -> list[Chain]:
        return [Chain.BITCOIN]

    def rate_limit_delay(self) -> float:
        return 0.5

    def fetch_transactions(self, address: str, chain: Chain) -> list[TransactionCreate]:
        results: list[TransactionCreate] = []
        last_seen_txid: str | None = None

        while True:
            url = f"{BASE_URL}/address/{address}/txs"
            if last_seen_txid:
                url += f"/chain/{last_seen_txid}"

            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    batch = resp.json()
            except Exception as e:
                logger.error("Bitcoin fetch error for %s: %s", address, e)
                break

            if not batch:
                break

            for tx in batch:
                parsed = self._parse_tx(tx, address)
                if parsed:
                    results.append(parsed)

            if len(batch) < 25:
                break

            last_seen_txid = batch[-1]["txid"]
            time.sleep(self.rate_limit_delay())

        return results

    def _parse_tx(self, tx: dict, address: str) -> TransactionCreate | None:
        txid = tx.get("txid", "")
        status = tx.get("status", {})
        block_time = status.get("block_time")
        if block_time:
            timestamp_utc = datetime.fromtimestamp(block_time, tz=UTC)
        else:
            timestamp_utc = datetime.now(tz=UTC)

        # Sum input and output values for this address
        value_in = Decimal(0)
        value_out = Decimal(0)
        fee_sats = Decimal(str(tx.get("fee", 0)))

        for vin in tx.get("vin", []):
            prevout = vin.get("prevout", {})
            if prevout.get("scriptpubkey_address") == address:
                value_out += Decimal(str(prevout.get("value", 0)))

        for vout in tx.get("vout", []):
            if vout.get("scriptpubkey_address") == address:
                value_in += Decimal(str(vout.get("value", 0)))

        net = value_in - value_out

        if net == 0:
            return None

        if net > 0:
            event_type = EventType.TRANSFER_IN
            amount = net / SATOSHI
            fee_amount = None
            fee_coin = None
        else:
            event_type = EventType.TRANSFER_OUT
            amount = (-net) / SATOSHI
            fee_amount = fee_sats / SATOSHI
            fee_coin = "BTC"

        return TransactionCreate(
            source_platform="BLOCKSTREAM",
            timestamp_utc=timestamp_utc,
            event_type=event_type.value,
            base_coin="BTC",
            base_amount=amount,
            fee_coin=fee_coin,
            fee_amount=fee_amount,
            tx_hash=txid,
            from_address=address if event_type == EventType.TRANSFER_OUT else None,
            to_address=address if event_type == EventType.TRANSFER_IN else None,
        )
