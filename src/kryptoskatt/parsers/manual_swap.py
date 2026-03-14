"""Manual DEX-swap CSV parser.

Lets users record DeFi swaps that lack an on-chain adapter.

Expected CSV header:
timestamp,from_coin,from_amount,to_coin,to_amount,fee_coin,fee_amount,tx_hash,notes

Each row generates:
  - SWAP_OUT  for (from_coin, from_amount)
  - SWAP_IN   for (to_coin, to_amount)
  - FEE       for (fee_coin, fee_amount) — only when fee_amount > 0
"""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from kryptoskatt.enums import EventType
from kryptoskatt.schemas import TransactionCreate

PLATFORM_NAME = "manual_swap"


@dataclass
class ParseResult:
    """Result of parsing a CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _parse_timestamp(ts: str) -> datetime:
    """Parse ISO-8601 timestamp to UTC datetime.

    Args:
        ts: Timestamp string, e.g. '2024-01-15T10:30:00Z'.

    Returns:
        datetime with UTC timezone.
    """
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    return dt.astimezone(UTC)


class ManualSwapParser:
    """Parser for manually recorded DEX swap CSV files."""

    def parse(self, file_path: Path) -> ParseResult:
        """Parse a manual swap CSV file.

        Args:
            file_path: Path to the CSV file.

        Returns:
            ParseResult containing transactions and errors.
        """
        transactions: list[TransactionCreate] = []
        errors: list[str] = []

        try:
            with open(file_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row_num, row in enumerate(reader, start=2):
                    try:
                        txs = self._parse_row(row)
                        transactions.extend(txs)
                    except Exception as e:
                        errors.append(f"Row {row_num}: {e}")
        except Exception as e:
            errors.append(f"Failed to read file: {e}")

        return ParseResult(transactions=transactions, errors=errors)

    def _parse_row(self, row: dict[str, str]) -> list[TransactionCreate]:
        """Parse one row into SWAP_OUT + SWAP_IN + optional FEE transactions.

        Args:
            row: CSV row as dict.

        Returns:
            List of TransactionCreate objects.
        """
        timestamp = _parse_timestamp(row.get("timestamp", "").strip())
        tx_hash = row.get("tx_hash", "").strip() or None
        raw_payload: dict[str, Any] = dict(row)

        from_coin = row.get("from_coin", "").strip()
        to_coin = row.get("to_coin", "").strip()

        try:
            from_amount = Decimal(row.get("from_amount", "0").strip())
        except InvalidOperation as exc:
            raise ValueError(f"Invalid from_amount: '{row.get('from_amount')}'") from exc

        try:
            to_amount = Decimal(row.get("to_amount", "0").strip())
        except InvalidOperation as exc:
            raise ValueError(f"Invalid to_amount: '{row.get('to_amount')}'") from exc

        swap_out = TransactionCreate(
            source_platform=PLATFORM_NAME.upper(),
            timestamp_utc=timestamp,
            event_type=EventType.SWAP_OUT.value,
            base_coin=from_coin,
            base_amount=from_amount,
            tx_hash=tx_hash,
            raw_payload=raw_payload,
        )

        swap_in = TransactionCreate(
            source_platform=PLATFORM_NAME.upper(),
            timestamp_utc=timestamp,
            event_type=EventType.SWAP_IN.value,
            base_coin=to_coin,
            base_amount=to_amount,
            tx_hash=tx_hash,
            raw_payload=raw_payload,
        )

        result: list[TransactionCreate] = [swap_out, swap_in]

        fee_coin = row.get("fee_coin", "").strip()
        fee_amount_str = row.get("fee_amount", "0").strip()
        try:
            fee_amount = Decimal(fee_amount_str) if fee_amount_str else Decimal("0")
        except InvalidOperation:
            fee_amount = Decimal("0")

        if fee_amount > 0 and fee_coin:
            fee_tx = TransactionCreate(
                source_platform=PLATFORM_NAME.upper(),
                timestamp_utc=timestamp,
                event_type=EventType.FEE.value,
                base_coin=fee_coin,
                base_amount=fee_amount,
                tx_hash=tx_hash,
                raw_payload=raw_payload,
            )
            result.append(fee_tx)

        return result
