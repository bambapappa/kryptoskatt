"""Coinbase Advanced Trade CSV parser."""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from kryptoskatt.enums import EventType
from kryptoskatt.schemas import TransactionCreate

PLATFORM_NAME = "coinbase_advanced"


@dataclass
class ParseResult:
    """Result of parsing a CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CoinbaseAdvancedParser:
    """Parser for Coinbase Advanced Trade CSV exports.

    Expected header:
    portfolio,trade id,product,side,created at,size,size unit,price,fee,total,price/fee/total unit
    """

    def parse(self, file_path: Path) -> ParseResult:
        """Parse a Coinbase Advanced Trade CSV export file.

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
                        errors.append(f"Row {row_num}: {str(e)}")

        except Exception as e:
            errors.append(f"Failed to read file: {str(e)}")

        return ParseResult(transactions=transactions, errors=errors)

    def _parse_row(self, row: dict[str, str]) -> list[TransactionCreate]:
        """Parse a single CSV row into TransactionCreate objects.

        Args:
            row: CSV row as dict.

        Returns:
            List of TransactionCreate objects (1 or 2 depending on fee).
        """
        side = row.get("side", "").strip().upper()
        product = row.get("product", "").strip()
        created_at = row.get("created at", "").strip()
        size_str = row.get("size", "").strip()
        fee_str = row.get("fee", "").strip()
        total_str = row.get("total", "").strip()
        quote_unit = row.get("price/fee/total unit", "").strip()

        timestamp = self._parse_timestamp(created_at)
        size = Decimal(size_str)
        fee = Decimal(fee_str) if fee_str else Decimal("0")
        total = Decimal(total_str) if total_str else None

        base_coin, quote_coin = self._parse_product(product)
        raw_payload: dict[str, Any] = dict(row)

        # Map side to event type
        if side == "BUY":
            event_type = EventType.BUY
            # For a buy, total is positive (cost paid)
            quote_amount = abs(total) if total is not None else None
        elif side == "SELL":
            event_type = EventType.SELL
            # For a sell, total is the proceeds received
            quote_amount = abs(total) if total is not None else None
        else:
            raise ValueError(f"Unknown side: '{side}'")

        result = []

        main_tx = TransactionCreate(
            source_platform=PLATFORM_NAME.upper(),
            timestamp_utc=timestamp,
            event_type=event_type,
            base_coin=base_coin,
            base_amount=size,
            quote_coin=quote_coin if quote_coin else quote_unit,
            quote_amount=quote_amount,
            raw_payload=raw_payload,
        )
        result.append(main_tx)

        # Emit separate FEE transaction when fee > 0
        if fee and fee > Decimal("0"):
            fee_tx = TransactionCreate(
                source_platform=PLATFORM_NAME.upper(),
                timestamp_utc=timestamp,
                event_type=EventType.FEE,
                base_coin=quote_unit if quote_unit else quote_coin,
                base_amount=fee,
                raw_payload=raw_payload,
            )
            result.append(fee_tx)

        return result

    def _parse_product(self, product: str) -> tuple[str, str]:
        """Parse product string like 'BTC-EUR' into (base, quote) coins.

        Args:
            product: Product string, e.g. 'BTC-EUR'.

        Returns:
            Tuple of (base_coin, quote_coin).
        """
        parts = product.split("-", 1)
        if len(parts) != 2:
            raise ValueError(f"Cannot parse product: '{product}'")
        return parts[0], parts[1]

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse ISO 8601 timestamp string to UTC datetime.

        Args:
            timestamp_str: Timestamp string like '2024-01-15T10:30:00Z'.

        Returns:
            datetime with UTC timezone.
        """
        ts = timestamp_str.rstrip("Z")
        dt = datetime.fromisoformat(ts)
        return dt.replace(tzinfo=UTC)
