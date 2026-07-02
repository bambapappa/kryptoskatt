"""Bitstamp CSV parser.

Bitstamp "Transactions" export (v2, 2023+) has columns:
ID, Account, Type, Subtype, Datetime, Amount, Amount currency,
Value, Value currency, Rate, Rate currency, Fee, Fee currency, Order ID

Type values: Market (Subtype Buy/Sell), Deposit, Withdrawal, Staking reward.
The older v1 format (Type, Datetime, Account, Amount, Value, Rate, Fee,
Sub Type) with amounts like "0.5 BTC" is also supported.
"""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from kryptoskatt.schemas import TransactionCreate

PLATFORM_NAME = "bitstamp"


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    stripped = value.strip().replace(",", "")
    if not stripped:
        return None
    try:
        return Decimal(stripped)
    except InvalidOperation:
        return None


def _split_amount_currency(value: str) -> tuple[Decimal | None, str | None]:
    """Split a v1-style '0.50000000 BTC' cell into (amount, currency)."""
    parts = value.strip().split()
    if len(parts) == 2:
        return _parse_decimal(parts[0]), parts[1].upper()
    return _parse_decimal(value), None


def _parse_timestamp(value: str) -> datetime:
    """Parse Bitstamp timestamps.

    v2 uses ISO 8601 UTC ('2023-04-01T09:00:00Z' or with offset);
    v1 uses e.g. 'Apr. 01, 2023, 09:00 AM'.
    """
    stripped = value.strip()
    iso = stripped.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        pass
    for fmt in ("%b. %d, %Y, %I:%M %p", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(stripped, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized Bitstamp timestamp: {value!r}")


@dataclass
class ParseResult:
    """Result of parsing a Bitstamp CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BitstampParser:
    """Parser for Bitstamp transactions CSV exports (v1 and v2)."""

    def parse(self, file_path: Path) -> ParseResult:
        transactions: list[TransactionCreate] = []
        errors: list[str] = []

        try:
            with open(file_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception as e:
            return ParseResult(errors=[f"Failed to read file: {e}"])

        for row_num, row in enumerate(rows, start=2):
            try:
                txs = self._parse_row(row)
                transactions.extend(txs)
            except Exception as e:
                errors.append(f"Row {row_num}: {e}")

        return ParseResult(transactions=transactions, errors=errors)

    def _parse_row(self, row: dict) -> list[TransactionCreate]:
        tx_type = (row.get("Type") or "").strip().lower()
        subtype = (row.get("Subtype") or row.get("Sub Type") or "").strip().lower()
        timestamp = _parse_timestamp(row.get("Datetime") or "")
        raw_payload = dict(row)

        # v2 has explicit currency columns; v1 embeds them in the cells
        if "Amount currency" in row:
            amount = _parse_decimal(row.get("Amount"))
            amount_ccy = (row.get("Amount currency") or "").strip().upper() or None
            value = _parse_decimal(row.get("Value"))
            value_ccy = (row.get("Value currency") or "").strip().upper() or None
            fee = _parse_decimal(row.get("Fee"))
            fee_ccy = (row.get("Fee currency") or "").strip().upper() or None
        else:
            amount, amount_ccy = _split_amount_currency(row.get("Amount") or "")
            value, value_ccy = _split_amount_currency(row.get("Value") or "")
            fee, fee_ccy = _split_amount_currency(row.get("Fee") or "")

        if amount is None or not amount_ccy:
            raise ValueError("Missing amount/currency")

        txs: list[TransactionCreate] = []

        if tx_type == "market":
            if subtype == "buy":
                event_type = "BUY"
            elif subtype == "sell":
                event_type = "SELL"
            else:
                raise ValueError(f"Unknown Market subtype: {subtype!r}")
            txs.append(TransactionCreate(
                source_platform="BITSTAMP",
                timestamp_utc=timestamp,
                event_type=event_type,
                base_coin=amount_ccy,
                base_amount=abs(amount),
                quote_coin=value_ccy,
                quote_amount=abs(value) if value is not None else None,
                fee_coin=fee_ccy if fee else None,
                fee_amount=abs(fee) if fee else None,
                raw_payload=raw_payload,
            ))
        elif tx_type in ("deposit", "ripple deposit"):
            txs.append(TransactionCreate(
                source_platform="BITSTAMP",
                timestamp_utc=timestamp,
                event_type="TRANSFER_IN",
                base_coin=amount_ccy,
                base_amount=abs(amount),
                raw_payload=raw_payload,
            ))
        elif tx_type in ("withdrawal", "ripple payment"):
            txs.append(TransactionCreate(
                source_platform="BITSTAMP",
                timestamp_utc=timestamp,
                event_type="TRANSFER_OUT",
                base_coin=amount_ccy,
                base_amount=-abs(amount),
                raw_payload=raw_payload,
            ))
        elif tx_type == "staking reward":
            txs.append(TransactionCreate(
                source_platform="BITSTAMP",
                timestamp_utc=timestamp,
                event_type="REWARD",
                base_coin=amount_ccy,
                base_amount=abs(amount),
                raw_payload=raw_payload,
            ))
        # Unknown types are skipped silently (e.g. "Sub account transfer")

        return txs
