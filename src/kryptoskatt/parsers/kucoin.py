"""KuCoin order history CSV parser."""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from kryptoskatt.enums import EventType
from kryptoskatt.schemas import TransactionCreate

PLATFORM_NAME = "kucoin"


@dataclass
class ParseResult:
    """Result of parsing a CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _parse_symbol(symbol: str) -> tuple[str, str]:
    """Split 'BTC-USDT' into ('BTC', 'USDT').

    Args:
        symbol: Trading pair like 'BTC-USDT'.

    Returns:
        Tuple of (base_coin, quote_coin).

    Raises:
        ValueError: If symbol cannot be split.
    """
    parts = symbol.strip().split("-")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Unrecognised symbol format: '{symbol}'")
    return parts[0], parts[1]


def _parse_timestamp(ts: str) -> datetime:
    """Parse KuCoin ISO-8601 timestamp to UTC datetime.

    Args:
        ts: Timestamp string like '2024-01-15T10:30:00Z'.

    Returns:
        datetime with UTC timezone.
    """
    ts = ts.strip()
    # Handle trailing Z (UTC) and +00:00 variants
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    return dt.astimezone(UTC)


class KuCoinParser:
    """Parser for KuCoin order history CSV exports.

    Expected header:
    tradeId,symbol,side,price,size,funds,fee,feeRate,feeCurrency,
    fixFee,context,orderId,orderPlacedAt,orderType,orderSide

    Each row produces one BUY/SELL transaction plus a FEE transaction
    when fee > 0.
    """

    def parse(self, file_path: Path) -> ParseResult:
        """Parse a KuCoin CSV export file.

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
        """Parse one CSV row into one or two TransactionCreate objects.

        Args:
            row: CSV row as dict.

        Returns:
            List with one trade transaction; a FEE transaction is appended
            when fee > 0.
        """
        side = row.get("side", "").strip().lower()
        if side == "buy":
            event_type = EventType.BUY
        elif side == "sell":
            event_type = EventType.SELL
        else:
            raise ValueError(f"Unknown side: '{side}'")

        symbol = row.get("symbol", "").strip()
        base_coin, quote_coin = _parse_symbol(symbol)

        try:
            base_amount = Decimal(row.get("size", "0").strip())
        except InvalidOperation as exc:
            raise ValueError(f"Invalid size: '{row.get('size')}'") from exc

        try:
            quote_amount = Decimal(row.get("funds", "0").strip())
        except InvalidOperation as exc:
            raise ValueError(f"Invalid funds: '{row.get('funds')}'") from exc

        timestamp = _parse_timestamp(row.get("orderPlacedAt", "").strip())
        raw_payload: dict[str, Any] = dict(row)

        trade_tx = TransactionCreate(
            source_platform=PLATFORM_NAME.upper(),
            timestamp_utc=timestamp,
            event_type=event_type.value,
            base_coin=base_coin,
            base_amount=base_amount,
            quote_coin=quote_coin,
            quote_amount=quote_amount,
            raw_payload=raw_payload,
        )

        result: list[TransactionCreate] = [trade_tx]

        # Emit a FEE transaction when fee > 0
        fee_str = row.get("fee", "0").strip()
        try:
            fee_amount = Decimal(fee_str) if fee_str else Decimal("0")
        except InvalidOperation:
            fee_amount = Decimal("0")

        fee_currency = row.get("feeCurrency", "").strip()
        if fee_amount > 0 and fee_currency:
            fee_tx = TransactionCreate(
                source_platform=PLATFORM_NAME.upper(),
                timestamp_utc=timestamp,
                event_type=EventType.FEE.value,
                base_coin=fee_currency,
                base_amount=fee_amount,
                raw_payload=raw_payload,
            )
            result.append(fee_tx)

        return result
