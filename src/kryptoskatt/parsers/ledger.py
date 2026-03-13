"""Ledger Live CSV parser for hardware wallet exports."""

import csv
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate

# Account name keyword → Chain (first match wins, order matters)
_ACCOUNT_NAME_CHAIN_MAP: list[tuple[str, Chain]] = [
    ("binance smart chain", Chain.BNB),
    ("bnb chain", Chain.BNB),
    ("bsc", Chain.BNB),
    ("bnb", Chain.BNB),
    ("xrp ledger", Chain.RIPPLE),
    ("ripple", Chain.RIPPLE),
    ("xrp", Chain.RIPPLE),
    ("arbitrum", Chain.ARBITRUM),
    ("polygon", Chain.POLYGON),
    ("matic", Chain.POLYGON),
    ("solana", Chain.SOLANA),
    ("bitcoin", Chain.BITCOIN),
    ("btc", Chain.BITCOIN),
    ("base", Chain.BASE),
    ("tron", Chain.TRON),
    ("trx", Chain.TRON),
    ("vechain", Chain.VECHAIN),
    ("vet", Chain.VECHAIN),
    ("ethereum", Chain.ETHEREUM),
    ("eth", Chain.ETHEREUM),
    ("peaq", Chain.PEAQ),
    ("aleo", Chain.ALEO),
]

# xpub/address prefix → Chain fallback (used when account name gives no match)
_XPUB_PREFIX_MAP: list[tuple[str, Chain]] = [
    ("xpub", Chain.BITCOIN),
    ("zpub", Chain.BITCOIN),
    ("ypub", Chain.BITCOIN),
    ("ltub", Chain.UNKNOWN),  # Litecoin — not yet in enum
]

_OPERATION_TYPE_MAP: dict[str, EventType] = {
    "IN": EventType.TRANSFER_IN,
    "OUT": EventType.TRANSFER_OUT,
    "FEES": EventType.FEE,
}


def _detect_chain(account_name: str, xpub: str) -> Chain:
    """Detect chain from account name, falling back to xpub/address format."""
    name_lower = account_name.lower()
    for keyword, chain in _ACCOUNT_NAME_CHAIN_MAP:
        if keyword in name_lower:
            return chain

    # Fallback: xpub prefix heuristics
    for prefix, chain in _XPUB_PREFIX_MAP:
        if xpub.startswith(prefix):
            return chain

    # EVM 0x address without a matching account name keyword
    if xpub.startswith("0x"):
        return Chain.ETHEREUM  # best guess

    return Chain.UNKNOWN


def _parse_decimal(value: str) -> Decimal | None:
    """Return Decimal or None if value is empty/invalid."""
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return Decimal(stripped)
    except InvalidOperation:
        return None


def _parse_timestamp(value: str) -> datetime:
    """Parse ISO 8601 timestamp with Z suffix."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=UTC)


class LedgerParser:
    """Parser for Ledger Live CSV exports."""

    HEADER_MARKER = "Operation Date"

    def parse(self, file_path: Path) -> tuple[list[TransactionCreate], list[str]]:
        transactions: list[TransactionCreate] = []
        errors: list[str] = []

        with open(file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row_num, row in enumerate(reader, start=2):
                try:
                    tx = self._parse_row(row)
                    if tx is not None:
                        transactions.append(tx)
                except Exception as e:
                    errors.append(f"Row {row_num}: {e}")

        return transactions, errors

    def _parse_row(self, row: dict[str, str]) -> TransactionCreate | None:
        # Skip non-confirmed rows
        if row.get("Status", "").strip().lower() != "confirmed":
            return None

        op_type_raw = row.get("Operation Type", "").strip().upper()
        event_type = _OPERATION_TYPE_MAP.get(op_type_raw)
        if event_type is None:
            return None  # Unknown operation type — skip silently

        timestamp = _parse_timestamp(row["Operation Date"].strip())
        coin = row["Currency Ticker"].strip()
        account_name = row.get("Account Name", "").strip()
        xpub = row.get("Account xpub", "").strip()
        tx_hash = row.get("Operation Hash", "").strip() or None

        amount = _parse_decimal(row.get("Operation Amount", ""))
        if amount is None:
            amount = Decimal("0")

        fee_raw = _parse_decimal(row.get("Operation Fees", ""))

        chain = _detect_chain(account_name, xpub)

        # Sign amounts: OUT and FEE reduce holdings
        if event_type in (EventType.TRANSFER_OUT, EventType.FEE):
            amount = -amount

        # For FEE rows the fee IS the amount — no separate fee field needed.
        # For OUT rows, attach gas fee if present (but it's a separate FEES row in Ledger Live).
        fee_coin = None
        fee_amount = None
        if event_type == EventType.TRANSFER_OUT and fee_raw:
            fee_coin = coin
            fee_amount = fee_raw

        # Address: xpub field holds the wallet address for this account
        from_addr = xpub if event_type in (EventType.TRANSFER_OUT, EventType.FEE) else None
        to_addr = xpub if event_type == EventType.TRANSFER_IN else None

        raw_payload = dict(row)
        raw_payload["chain"] = chain.value

        return TransactionCreate(
            source_platform="LEDGER",
            timestamp_utc=timestamp,
            event_type=event_type,
            base_coin=coin,
            base_amount=amount,
            fee_coin=fee_coin,
            fee_amount=fee_amount,
            tx_hash=tx_hash,
            from_address=from_addr,
            to_address=to_addr,
            raw_payload=raw_payload,
        )
