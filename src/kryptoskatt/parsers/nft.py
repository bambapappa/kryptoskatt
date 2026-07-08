"""NFT ledger CSV parser.

NFTs cannot be priced automatically (no fungible market price), so acquisition
cost and sale proceeds are supplied by the user in SEK. Each NFT is a unique
asset, which the average-cost (GAV) engine handles naturally: a synthetic
``base_coin`` symbol of the form ``NFT:<collection>#<token_id>`` gives every
token its own cost-basis ledger, and disposals flow straight into K4/SRU
(Skatteverket treats NFTs as other assets, reported in the same section D as
other crypto).

Expected CSV header (case-insensitive, order-independent):
    date,action,collection,token_id,chain,amount_sek,fee_sek,tx_hash,notes

``action`` is one of:
    BUY / MINT          acquisition at ``amount_sek`` (total price paid)
    SELL                disposal at ``amount_sek`` (total proceeds)
    TRANSFER_IN         received into an own wallet (non-taxable if linked)
    TRANSFER_OUT        sent from an own wallet (non-taxable if linked)

``amount_sek`` is the total SEK value of the single NFT (base_amount is always
1); ``fee_sek`` is an optional gas/marketplace fee in SEK that is added to the
cost basis on a buy and subtracted from the proceeds on a sale.
"""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from kryptoskatt.enums import EventType
from kryptoskatt.schemas import TransactionCreate

PLATFORM_NAME = "nft"

# base_coin is String(100); keep the synthetic symbol within that budget.
_MAX_SYMBOL_LEN = 100

_ACTION_EVENT_MAP = {
    "BUY": EventType.BUY,
    "MINT": EventType.BUY,
    "PURCHASE": EventType.BUY,
    "SELL": EventType.SELL,
    "SALE": EventType.SELL,
    "TRANSFER_IN": EventType.TRANSFER_IN,
    "IN": EventType.TRANSFER_IN,
    "TRANSFER_OUT": EventType.TRANSFER_OUT,
    "OUT": EventType.TRANSFER_OUT,
}


def nft_symbol(collection: str, token_id: str) -> str:
    """Build the synthetic per-NFT asset symbol ``NFT:<collection>#<token_id>``.

    The token id is always preserved (it is what makes the asset unique); the
    collection name is truncated if the combined symbol would exceed the
    ``base_coin`` column width.
    """
    collection = collection.strip() or "Unknown"
    token_id = token_id.strip()
    suffix = f"#{token_id}" if token_id else ""
    prefix = "NFT:"
    room = _MAX_SYMBOL_LEN - len(prefix) - len(suffix)
    if room < 1:
        # Pathologically long token id — keep it, drop the collection name.
        return f"{prefix}{suffix}"[:_MAX_SYMBOL_LEN]
    if len(collection) > room:
        collection = collection[:room]
    return f"{prefix}{collection}{suffix}"


@dataclass
class ParseResult:
    """Result of parsing an NFT CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _parse_timestamp(value: str) -> datetime:
    """Parse an ISO date or datetime (with optional Z) to a UTC datetime."""
    value = value.strip()
    if not value:
        raise ValueError("missing date")
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_decimal(value: str | None) -> Decimal:
    value = (value or "").strip()
    if not value:
        return Decimal("0")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: '{value}'") from exc


class NftParser:
    """Parser for a manual/marketplace NFT ledger CSV."""

    def parse(self, file_path: Path) -> ParseResult:
        transactions: list[TransactionCreate] = []
        errors: list[str] = []

        try:
            with open(file_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                # Normalise header keys to lowercase for case-insensitive access
                for row_num, raw in enumerate(reader, start=2):
                    row = {(k or "").strip().lower(): v for k, v in raw.items()}
                    try:
                        tx = self._parse_row(row)
                        if tx is not None:
                            transactions.append(tx)
                    except Exception as e:
                        errors.append(f"Row {row_num}: {e}")
        except Exception as e:
            errors.append(f"Failed to read file: {e}")

        return ParseResult(transactions=transactions, errors=errors)

    def _parse_row(self, row: dict[str, str]) -> TransactionCreate | None:
        action = (row.get("action") or "").strip().upper()
        if not action:
            return None  # blank line
        event_type = _ACTION_EVENT_MAP.get(action)
        if event_type is None:
            raise ValueError(f"unknown action '{action}'")

        collection = (row.get("collection") or "").strip()
        token_id = (row.get("token_id") or row.get("tokenid") or "").strip()
        if not collection and not token_id:
            raise ValueError("row needs a collection or token_id")

        timestamp = _parse_timestamp(row.get("date") or row.get("timestamp") or "")
        amount_sek = _parse_decimal(row.get("amount_sek"))
        fee_sek = _parse_decimal(row.get("fee_sek"))
        tx_hash = (row.get("tx_hash") or "").strip() or None

        raw_payload: dict[str, Any] = {k: v for k, v in row.items() if v not in (None, "")}
        raw_payload["nft_collection"] = collection
        raw_payload["nft_token_id"] = token_id
        raw_payload["is_nft"] = True

        # base_amount is always a single token; amount_sek is the per-unit price.
        return TransactionCreate(
            source_platform=PLATFORM_NAME.upper(),
            timestamp_utc=timestamp,
            event_type=event_type.value,
            base_coin=nft_symbol(collection, token_id),
            base_amount=Decimal("1"),
            # Fee is expressed in SEK so the GAV engine folds it into the cost
            # basis (buy) or nets it off the proceeds (sale).
            fee_coin="SEK" if fee_sek > 0 else None,
            fee_amount=fee_sek if fee_sek > 0 else None,
            tx_hash=tx_hash,
            price_sek=amount_sek if amount_sek > 0 else None,
            raw_payload=raw_payload,
        )
