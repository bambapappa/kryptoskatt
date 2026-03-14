"""Kraken CSV parser.

Kraken exports ledger history as CSV with columns:
txid, refid, time, type, subtype, aclass, asset, amount, fee, balance

Trade rows come in pairs sharing the same refid — one for the crypto asset
and one for the counter-currency (fiat or another crypto).
"""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from kryptoskatt.schemas import TransactionCreate

PLATFORM_NAME = "kraken"

# Kraken uses X/Z prefixes for some assets — strip them to get canonical symbols.
_ASSET_MAP: dict[str, str] = {
    "XXBT": "BTC",
    "XBTC": "BTC",
    "XBT": "BTC",
    "XETH": "ETH",
    "XLTC": "LTC",
    "XXMR": "XMR",
    "XXRP": "XRP",
    "XXLM": "XLM",
    "ZUSD": "USD",
    "ZEUR": "EUR",
    "ZGBP": "GBP",
    "ZCAD": "CAD",
    "ZJPY": "JPY",
    "ZAUD": "AUD",
    "ZSEK": "SEK",
    "ZNOK": "NOK",
    "ZDKK": "DKK",
    "ZCHF": "CHF",
}


def _normalize_asset(raw: str) -> str:
    """Normalise Kraken asset name to canonical symbol."""
    stripped = raw.strip()
    return _ASSET_MAP.get(stripped, stripped)


def _parse_decimal(value: str) -> Decimal | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return Decimal(stripped)
    except InvalidOperation:
        return None


def _parse_timestamp(value: str) -> datetime:
    """Parse Kraken timestamp: '2024-01-15 10:30:00'."""
    stripped = value.strip()
    dt = datetime.strptime(stripped, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=UTC)


@dataclass
class ParseResult:
    """Result of parsing a Kraken CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class KrakenParser:
    """Parser for Kraken ledger CSV exports."""

    def parse(self, file_path: Path) -> ParseResult:
        """Parse a Kraken ledger CSV export.

        Trade rows are paired via refid. Each pair produces one BUY or SELL
        transaction. Single-row entries (deposit, withdrawal, staking, reward)
        are handled directly.
        """
        transactions: list[TransactionCreate] = []
        errors: list[str] = []
        # Buffer trade rows by refid so we can pair them
        trade_buffer: dict[str, list[dict]] = {}

        try:
            with open(file_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception as e:
            return ParseResult(errors=[f"Failed to read file: {e}"])

        for row_num, row in enumerate(rows, start=2):
            try:
                tx_type = row.get("type", "").strip().lower()
                refid = row.get("refid", "").strip()

                if tx_type == "trade":
                    # Buffer trade rows; process when we have a pair
                    if refid not in trade_buffer:
                        trade_buffer[refid] = []
                    trade_buffer[refid].append(row)
                else:
                    txs = self._parse_non_trade_row(row, row_num)
                    transactions.extend(txs)
            except Exception as e:
                errors.append(f"Row {row_num}: {e}")

        # Process trade pairs
        for refid, trade_rows in trade_buffer.items():
            try:
                txs = self._parse_trade_pair(refid, trade_rows)
                transactions.extend(txs)
            except Exception as e:
                errors.append(f"Trade refid {refid}: {e}")

        return ParseResult(transactions=transactions, errors=errors)

    def _parse_non_trade_row(self, row: dict, row_num: int) -> list[TransactionCreate]:
        """Parse deposit, withdrawal, staking, reward, transfer rows."""
        tx_type = row.get("type", "").strip().lower()
        asset = _normalize_asset(row.get("asset", ""))
        amount_raw = _parse_decimal(row.get("amount", ""))
        fee_raw = _parse_decimal(row.get("fee", ""))
        timestamp = _parse_timestamp(row.get("time", ""))
        txid = row.get("txid", "").strip() or None
        raw_payload = dict(row)

        if amount_raw is None:
            raise ValueError(f"Missing amount in row {row_num}")

        txs: list[TransactionCreate] = []

        if tx_type == "deposit":
            # Always incoming — amount is positive in Kraken export
            txs.append(TransactionCreate(
                source_platform="KRAKEN",
                timestamp_utc=timestamp,
                event_type="TRANSFER_IN",
                base_coin=asset,
                base_amount=abs(amount_raw),
                tx_hash=txid,
                raw_payload=raw_payload,
            ))
        elif tx_type == "withdrawal":
            txs.append(TransactionCreate(
                source_platform="KRAKEN",
                timestamp_utc=timestamp,
                event_type="TRANSFER_OUT",
                base_coin=asset,
                base_amount=-abs(amount_raw),
                tx_hash=txid,
                raw_payload=raw_payload,
            ))
        elif tx_type in ("staking", "reward"):
            txs.append(TransactionCreate(
                source_platform="KRAKEN",
                timestamp_utc=timestamp,
                event_type="REWARD",
                base_coin=asset,
                base_amount=abs(amount_raw),
                tx_hash=txid,
                raw_payload=raw_payload,
            ))
        elif tx_type == "transfer":
            if amount_raw > 0:
                txs.append(TransactionCreate(
                    source_platform="KRAKEN",
                    timestamp_utc=timestamp,
                    event_type="TRANSFER_IN",
                    base_coin=asset,
                    base_amount=amount_raw,
                    tx_hash=txid,
                    raw_payload=raw_payload,
                ))
            else:
                txs.append(TransactionCreate(
                    source_platform="KRAKEN",
                    timestamp_utc=timestamp,
                    event_type="TRANSFER_OUT",
                    base_coin=asset,
                    base_amount=amount_raw,  # already negative
                    tx_hash=txid,
                    raw_payload=raw_payload,
                ))
        else:
            # Unknown type — skip silently; caller can inspect raw errors
            return []

        # Attach separate FEE transaction when fee > 0
        if fee_raw and abs(fee_raw) > 0:
            txs.append(TransactionCreate(
                source_platform="KRAKEN",
                timestamp_utc=timestamp,
                event_type="FEE",
                base_coin=asset,
                base_amount=-abs(fee_raw),
                raw_payload=raw_payload,
            ))

        return txs

    def _parse_trade_pair(self, refid: str, rows: list[dict]) -> list[TransactionCreate]:
        """Convert a trade row-pair into a BUY transaction.

        Kraken emits two rows per trade:
        - one with the crypto asset (positive = bought, negative = sold)
        - one with the counter asset (opposite sign)

        We look at which row has the positive amount to determine direction:
        positive crypto + negative fiat → BUY
        negative crypto + positive fiat → SELL
        """
        if not rows:
            return []

        # Handle single trade row (incomplete export) — create UNKNOWN
        if len(rows) == 1:
            row = rows[0]
            asset = _normalize_asset(row.get("asset", ""))
            amount_raw = _parse_decimal(row.get("amount", ""))
            timestamp = _parse_timestamp(row.get("time", ""))
            if amount_raw is None:
                return []
            event_type = "BUY" if amount_raw > 0 else "SELL"
            return [TransactionCreate(
                source_platform="KRAKEN",
                timestamp_utc=timestamp,
                event_type=event_type,
                base_coin=asset,
                base_amount=abs(amount_raw),
                raw_payload=dict(row),
            )]

        # Use the first two rows (ignore extras)
        row_a = rows[0]
        row_b = rows[1]

        amount_a = _parse_decimal(row_a.get("amount", "")) or Decimal("0")
        amount_b = _parse_decimal(row_b.get("amount", "")) or Decimal("0")
        asset_a = _normalize_asset(row_a.get("asset", ""))
        asset_b = _normalize_asset(row_b.get("asset", ""))
        fee_a = _parse_decimal(row_a.get("fee", "")) or Decimal("0")
        fee_b = _parse_decimal(row_b.get("fee", "")) or Decimal("0")
        timestamp = _parse_timestamp(row_a.get("time", ""))
        raw_payload = {**dict(row_a), **{"row_b": dict(row_b)}}

        # Positive side = what was received, negative side = what was paid
        if amount_a > 0:
            # Row A = crypto received (BUY)
            base_coin, base_amount = asset_a, amount_a
            quote_coin, quote_amount = asset_b, abs(amount_b)
            fee_coin = asset_a if abs(fee_a) > 0 else (asset_b if abs(fee_b) > 0 else None)
            fee_amount_val = abs(fee_a) if abs(fee_a) > 0 else (abs(fee_b) if abs(fee_b) > 0 else None)
            event_type = "BUY"
        else:
            # Row A = crypto paid (SELL)
            base_coin, base_amount = asset_a, abs(amount_a)
            quote_coin, quote_amount = asset_b, amount_b
            fee_coin = asset_b if abs(fee_b) > 0 else (asset_a if abs(fee_a) > 0 else None)
            fee_amount_val = abs(fee_b) if abs(fee_b) > 0 else (abs(fee_a) if abs(fee_a) > 0 else None)
            event_type = "SELL"

        txs: list[TransactionCreate] = [
            TransactionCreate(
                source_platform="KRAKEN",
                timestamp_utc=timestamp,
                event_type=event_type,
                base_coin=base_coin,
                base_amount=base_amount,
                quote_coin=quote_coin,
                quote_amount=quote_amount,
                raw_payload=raw_payload,
            )
        ]

        # Separate FEE transaction when fee is non-zero
        if fee_coin and fee_amount_val and fee_amount_val > 0:
            txs.append(TransactionCreate(
                source_platform="KRAKEN",
                timestamp_utc=timestamp,
                event_type="FEE",
                base_coin=fee_coin,
                base_amount=-fee_amount_val,
                raw_payload=raw_payload,
            ))

        return txs
