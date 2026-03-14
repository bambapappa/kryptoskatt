"""Binance transaction history CSV parser."""

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from kryptoskatt.enums import EventType
from kryptoskatt.schemas import TransactionCreate

PLATFORM_NAME = "binance"

# Operations that are paired with a "Transaction Related" row at the same timestamp
_PAIRED_OPERATIONS = {"Buy", "Sell"}

# Direct single-row operation mappings
_DIRECT_OPERATION_MAP: dict[str, EventType] = {
    "Deposit": EventType.TRANSFER_IN,
    "Withdraw": EventType.TRANSFER_OUT,
    "POS savings interest": EventType.REWARD,
    "Savings Interest": EventType.REWARD,
    "Commission History": EventType.FEE,
    "Referral Kickback": EventType.REWARD,
    "Staking Rewards": EventType.REWARD,
    "ETH 2.0 Staking Rewards": EventType.REWARD,
    "Launchpool Interest": EventType.REWARD,
    "Simple Earn Flexible Interest": EventType.REWARD,
    "Simple Earn Locked Rewards": EventType.REWARD,
}


@dataclass
class ParseResult:
    """Result of parsing a CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BinanceParser:
    """Parser for Binance transaction history CSV exports.

    Expected header:
    UTC_Time,Account,Operation,Coin,Change,Remark

    BUY and SELL rows are paired with a "Transaction Related" row at the same
    timestamp. The signed Change field determines which is the asset and which
    is the quote currency.
    """

    def parse(self, file_path: Path) -> ParseResult:
        """Parse a Binance CSV export file.

        Args:
            file_path: Path to the CSV file.

        Returns:
            ParseResult containing transactions and errors.
        """
        transactions: list[TransactionCreate] = []
        errors: list[str] = []

        try:
            all_rows = self._read_rows(file_path)
            txs, errs = self._process_rows(all_rows)
            transactions.extend(txs)
            errors.extend(errs)
        except Exception as e:
            errors.append(f"Failed to read file: {str(e)}")

        return ParseResult(transactions=transactions, errors=errors)

    def _read_rows(self, file_path: Path) -> list[dict[str, str]]:
        """Read all CSV rows into a list."""
        with open(file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def _process_rows(
        self, rows: list[dict[str, str]]
    ) -> tuple[list[TransactionCreate], list[str]]:
        """Process all rows, pairing Buy/Sell rows with their Transaction Related rows.

        Args:
            rows: All CSV rows as dicts.

        Returns:
            Tuple of (transactions, errors).
        """
        transactions: list[TransactionCreate] = []
        errors: list[str] = []

        # Group rows by (UTC_Time, Account) for pairing
        grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        direct_rows: list[tuple[int, dict[str, str]]] = []

        for row_num, row in enumerate(rows, start=2):
            operation = row.get("Operation", "").strip()
            if operation in _PAIRED_OPERATIONS or operation == "Transaction Related":
                key = (row.get("UTC_Time", "").strip(), row.get("Account", "").strip())
                grouped[key].append(row)
            else:
                direct_rows.append((row_num, row))

        # Process paired rows (Buy/Sell with Transaction Related)
        for key, group_rows in grouped.items():
            try:
                txs = self._process_paired_group(group_rows)
                transactions.extend(txs)
            except Exception as e:
                errors.append(f"Timestamp {key[0]}: {str(e)}")

        # Process direct single-row operations
        for row_num, row in direct_rows:
            try:
                tx = self._parse_direct_row(row)
                if tx is not None:
                    transactions.append(tx)
            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")

        return transactions, errors

    def _process_paired_group(
        self, rows: list[dict[str, str]]
    ) -> list[TransactionCreate]:
        """Process a group of rows at the same timestamp for a Buy or Sell.

        Args:
            rows: Rows sharing the same UTC_Time and Account.

        Returns:
            List of TransactionCreate objects.
        """
        # Separate primary operation row from "Transaction Related" rows
        primary_rows = [r for r in rows if r.get("Operation", "").strip() in _PAIRED_OPERATIONS]
        related_rows = [r for r in rows if r.get("Operation", "").strip() == "Transaction Related"]

        if not primary_rows:
            # Only "Transaction Related" rows — skip
            return []

        primary = primary_rows[0]
        operation = primary.get("Operation", "").strip()
        timestamp = self._parse_timestamp(primary.get("UTC_Time", "").strip())
        raw_payload: dict[str, Any] = dict(primary)

        base_coin = primary.get("Coin", "").strip()
        base_change = Decimal(primary.get("Change", "0").strip())

        # Find quote from related row (negative Change = cost, positive = proceeds)
        quote_coin: str | None = None
        quote_amount: Decimal | None = None
        if related_rows:
            related = related_rows[0]
            quote_coin = related.get("Coin", "").strip()
            related_change = Decimal(related.get("Change", "0").strip())
            quote_amount = abs(related_change)

        if operation == "Buy":
            event_type = EventType.BUY
            base_amount = abs(base_change)
        else:  # Sell
            event_type = EventType.SELL
            base_amount = abs(base_change)

        return [
            TransactionCreate(
                source_platform=PLATFORM_NAME.upper(),
                timestamp_utc=timestamp,
                event_type=event_type,
                base_coin=base_coin,
                base_amount=base_amount,
                quote_coin=quote_coin,
                quote_amount=quote_amount,
                raw_payload=raw_payload,
            )
        ]

    def _parse_direct_row(self, row: dict[str, str]) -> TransactionCreate | None:
        """Parse a single-row operation (Deposit, Withdraw, Reward, Fee).

        Args:
            row: CSV row as dict.

        Returns:
            TransactionCreate or None if the operation is unknown/skipped.
        """
        operation = row.get("Operation", "").strip()
        event_type = _DIRECT_OPERATION_MAP.get(operation)

        if event_type is None:
            # Unknown operation — skip silently
            return None

        timestamp = self._parse_timestamp(row.get("UTC_Time", "").strip())
        coin = row.get("Coin", "").strip()
        change_str = row.get("Change", "").strip()
        change = Decimal(change_str)
        raw_payload: dict[str, Any] = dict(row)

        # For withdrawals/fee the change may be negative — use absolute value
        amount = abs(change)

        return TransactionCreate(
            source_platform=PLATFORM_NAME.upper(),
            timestamp_utc=timestamp,
            event_type=event_type,
            base_coin=coin,
            base_amount=amount,
            raw_payload=raw_payload,
        )

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse timestamp string to UTC datetime.

        Args:
            timestamp_str: Timestamp like '2024-01-15 10:30:00'.

        Returns:
            datetime with UTC timezone.
        """
        dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=UTC)
