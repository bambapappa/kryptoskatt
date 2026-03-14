"""Bybit order history CSV parser.

Bybit exports trade history in a CSV with columns:
  Date(UTC), Filled Price, Order Type, Side, Order Qty, Filled Qty, Fee, Fee Symbol,
  Order Status, Order ID

The trading symbol (e.g. BTCUSDT) is either:
1. Present as a "Symbol" column in the CSV (newer exports)
2. Encoded in the filename (e.g. BTCUSDT_orders.csv)

If the symbol cannot be determined, rows are emitted as UNKNOWN with the best
available information so the user can inspect and correct them manually.
"""

import csv
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from kryptoskatt.schemas import TransactionCreate

PLATFORM_NAME = "bybit"

# Common quote currencies — used to split a raw symbol like "BTCUSDT" into
# base="BTC" and quote="USDT".
_KNOWN_QUOTES = [
    "USDT", "USDC", "BTC", "ETH", "BUSD", "DAI", "EUR", "USD",
]


def _split_symbol(symbol: str) -> tuple[str, str]:
    """Split a Bybit trading pair symbol into (base, quote).

    E.g. "BTCUSDT" → ("BTC", "USDT")
         "ETHBTC"  → ("ETH", "BTC")

    Falls back to (symbol, "") when no known quote is matched.
    """
    upper = symbol.upper()
    for quote in _KNOWN_QUOTES:
        if upper.endswith(quote) and len(upper) > len(quote):
            base = upper[: -len(quote)]
            return base, quote
    return upper, ""


def _detect_symbol_from_filename(file_path: Path) -> str | None:
    """Try to extract a trading pair symbol from the filename.

    Expects patterns like "BTCUSDT_orders.csv" or "BTCUSDT.csv".
    """
    stem = file_path.stem  # e.g. "BTCUSDT_orders"
    # Strip common suffixes
    cleaned = re.sub(r"[_-](orders|trades|history|export).*", "", stem, flags=re.IGNORECASE)
    # Validate: at least 5 chars, only uppercase letters
    cleaned = cleaned.upper()
    if re.match(r"^[A-Z]{4,20}$", cleaned):
        return cleaned
    return None


def _parse_decimal(value: str) -> Decimal | None:
    stripped = value.strip()
    if not stripped or stripped == "-":
        return None
    # Strip trailing % if present (some Bybit fields use percentages)
    stripped = stripped.rstrip("%")
    try:
        return Decimal(stripped)
    except InvalidOperation:
        return None


def _parse_timestamp(value: str) -> datetime:
    """Parse Bybit timestamp: '2024-01-15 10:30:00' (UTC)."""
    stripped = value.strip()
    dt = datetime.strptime(stripped, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=UTC)


@dataclass
class ParseResult:
    """Result of parsing a Bybit CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BybitParser:
    """Parser for Bybit order history CSV exports."""

    def parse(self, file_path: Path) -> ParseResult:
        """Parse a Bybit order history CSV export."""
        transactions: list[TransactionCreate] = []
        errors: list[str] = []

        # Try to detect symbol from filename upfront
        filename_symbol = _detect_symbol_from_filename(file_path)

        try:
            with open(file_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception as e:
            return ParseResult(errors=[f"Failed to read file: {e}"])

        for row_num, row in enumerate(rows, start=2):
            # Skip rows where order was not filled
            status = row.get("Order Status", "").strip()
            if status and status.lower() not in ("filled", ""):
                continue

            try:
                txs = self._parse_row(row, row_num, filename_symbol)
                transactions.extend(txs)
            except Exception as e:
                errors.append(f"Row {row_num}: {e}")

        return ParseResult(transactions=transactions, errors=errors)

    def _parse_row(
        self, row: dict, row_num: int, filename_symbol: str | None
    ) -> list[TransactionCreate]:
        """Parse a single order row."""
        # Determine symbol
        symbol_raw = row.get("Symbol", "").strip() or filename_symbol or ""
        base_coin, quote_coin = _split_symbol(symbol_raw) if symbol_raw else ("", "")

        side = row.get("Side", "").strip()
        timestamp_str = row.get("Date(UTC)", "").strip()
        filled_qty_str = row.get("Filled Qty", "").strip()
        filled_price_str = row.get("Filled Price", "").strip()
        fee_str = row.get("Fee", "").strip()
        fee_symbol = row.get("Fee Symbol", "").strip()
        order_id = row.get("Order ID", "").strip() or None
        raw_payload = dict(row)

        timestamp = _parse_timestamp(timestamp_str)
        filled_qty = _parse_decimal(filled_qty_str)
        filled_price = _parse_decimal(filled_price_str)
        fee = _parse_decimal(fee_str)

        if filled_qty is None or filled_qty <= 0:
            # Nothing filled — skip
            return []

        if side.lower() == "buy":
            event_type = "BUY"
        elif side.lower() == "sell":
            event_type = "SELL"
        else:
            event_type = "UNKNOWN"

        quote_amount = None
        if filled_price and filled_qty:
            quote_amount = (filled_price * filled_qty).quantize(Decimal("0.00000001"))

        txs: list[TransactionCreate] = [
            TransactionCreate(
                source_platform="BYBIT",
                timestamp_utc=timestamp,
                event_type=event_type,
                base_coin=base_coin or "UNKNOWN",
                base_amount=filled_qty,
                quote_coin=quote_coin or None,
                quote_amount=quote_amount,
                tx_hash=order_id,
                raw_payload=raw_payload,
            )
        ]

        # Separate FEE transaction
        if fee and abs(fee) > 0 and fee_symbol:
            txs.append(TransactionCreate(
                source_platform="BYBIT",
                timestamp_utc=timestamp,
                event_type="FEE",
                base_coin=fee_symbol,
                base_amount=-abs(fee),
                raw_payload=raw_payload,
            ))

        return txs
