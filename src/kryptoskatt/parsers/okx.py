"""OKX CSV parser.

Handles the two common OKX exports:

Funding statement ("Funding bill"):
    id, Time, Type, Amount, Before Balance, After Balance, Fee, Symbol
    Type: Deposit / Withdrawal / Staking Yield / Fee rebate

Trading account statement (v2):
    id, Order id, Time, Trade Type, Instrument, Type, Amount, Unit, PL, Fee,
    Position Change, Position Balance, Balance Change, Balance, Unit
    Each fill produces one Buy row (asset received) and one Sell row
    (asset spent) sharing the same Order id — paired into BUY transactions.
    Note: the header contains two "Unit" columns, so the file is read
    positionally instead of with DictReader.
"""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from kryptoskatt.schemas import TransactionCreate

PLATFORM_NAME = "okx"


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


def _parse_timestamp(value: str) -> datetime:
    """Parse OKX timestamp: '2024-01-15 10:30:05' (UTC)."""
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


@dataclass
class ParseResult:
    """Result of parsing an OKX CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class OkxParser:
    """Parser for OKX funding and trading statement CSV exports."""

    def parse(self, file_path: Path) -> ParseResult:
        try:
            with open(file_path, encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        except Exception as e:
            return ParseResult(errors=[f"Failed to read file: {e}"])

        if not rows:
            return ParseResult(errors=["Empty file"])

        header = [h.strip().lower() for h in rows[0]]
        if "before balance" in header and "after balance" in header:
            return self._parse_funding(header, rows[1:])
        if "trade type" in header and "order id" in header:
            return self._parse_trades(header, rows[1:])
        return ParseResult(errors=["Unrecognized OKX file format"])

    # ── Funding statement ──────────────────────────────────────────────

    def _parse_funding(self, header: list[str], rows: list[list[str]]) -> ParseResult:
        transactions: list[TransactionCreate] = []
        errors: list[str] = []
        idx = {name: i for i, name in enumerate(header)}

        for row_num, row in enumerate(rows, start=2):
            if not any(cell.strip() for cell in row):
                continue
            try:
                tx_type = row[idx["type"]].strip().lower()
                timestamp = _parse_timestamp(row[idx["time"]])
                amount = _parse_decimal(row[idx["amount"]])
                fee = _parse_decimal(row[idx["fee"]]) if "fee" in idx else None
                symbol = row[idx["symbol"]].strip().upper()
                raw_payload = dict(zip(header, row))

                if amount is None or not symbol:
                    raise ValueError("Missing amount/symbol")

                if tx_type == "deposit":
                    transactions.append(TransactionCreate(
                        source_platform="OKX",
                        timestamp_utc=timestamp,
                        event_type="TRANSFER_IN",
                        base_coin=symbol,
                        base_amount=abs(amount),
                        raw_payload=raw_payload,
                    ))
                elif tx_type == "withdrawal":
                    transactions.append(TransactionCreate(
                        source_platform="OKX",
                        timestamp_utc=timestamp,
                        event_type="TRANSFER_OUT",
                        base_coin=symbol,
                        base_amount=-abs(amount),
                        raw_payload=raw_payload,
                    ))
                elif tx_type in ("staking yield", "fee rebate", "yield", "earn"):
                    transactions.append(TransactionCreate(
                        source_platform="OKX",
                        timestamp_utc=timestamp,
                        event_type="REWARD",
                        base_coin=symbol,
                        base_amount=abs(amount),
                        reward_type="other" if tx_type == "fee rebate" else "staking",
                        raw_payload=raw_payload,
                    ))
                else:
                    continue  # unknown funding type — skip

                if fee and abs(fee) > 0:
                    transactions.append(TransactionCreate(
                        source_platform="OKX",
                        timestamp_utc=timestamp,
                        event_type="FEE",
                        base_coin=symbol,
                        base_amount=-abs(fee),
                        raw_payload=raw_payload,
                    ))
            except Exception as e:
                errors.append(f"Row {row_num}: {e}")

        return ParseResult(transactions=transactions, errors=errors)

    # ── Trading account statement ──────────────────────────────────────

    def _parse_trades(self, header: list[str], rows: list[list[str]]) -> ParseResult:
        transactions: list[TransactionCreate] = []
        errors: list[str] = []
        idx: dict[str, int] = {}
        for i, name in enumerate(header):
            idx.setdefault(name, i)  # first occurrence wins ("unit" appears twice)

        # Buffer Buy/Sell legs by order id
        orders: dict[str, dict[str, list[dict]]] = {}
        for row_num, row in enumerate(rows, start=2):
            if not any(cell.strip() for cell in row):
                continue
            try:
                order_id = row[idx["order id"]].strip()
                side = row[idx["type"]].strip().lower()
                leg = {
                    "time": _parse_timestamp(row[idx["time"]]),
                    "amount": _parse_decimal(row[idx["amount"]]),
                    "unit": row[idx["unit"]].strip().upper(),
                    "fee": _parse_decimal(row[idx["fee"]]) if "fee" in idx else None,
                    "raw": dict(zip(header, row)),
                }
                if side in ("buy", "sell"):
                    orders.setdefault(order_id, {}).setdefault(side, []).append(leg)
                # other row types (funding fee etc.) are skipped
            except Exception as e:
                errors.append(f"Row {row_num}: {e}")

        for order_id, sides in orders.items():
            try:
                buys = sides.get("buy", [])
                sells = sides.get("sell", [])
                for i in range(max(len(buys), len(sells))):
                    buy = buys[i] if i < len(buys) else None
                    sell = sells[i] if i < len(sells) else None
                    txs = self._pair_to_transaction(order_id, buy, sell)
                    transactions.extend(txs)
            except Exception as e:
                errors.append(f"Order {order_id}: {e}")

        return ParseResult(transactions=transactions, errors=errors)

    def _pair_to_transaction(self, order_id: str, buy: dict | None, sell: dict | None) -> list[TransactionCreate]:
        """A Buy leg (asset received) + Sell leg (asset spent) become one BUY."""
        if buy and sell:
            txs = [TransactionCreate(
                source_platform="OKX",
                timestamp_utc=buy["time"],
                event_type="BUY",
                base_coin=buy["unit"],
                base_amount=abs(buy["amount"]),
                quote_coin=sell["unit"],
                quote_amount=abs(sell["amount"]),
                raw_payload={**buy["raw"], "sell_leg": sell["raw"], "order_id": order_id},
            )]
            fee_leg = buy if (buy["fee"] and abs(buy["fee"]) > 0) else (
                sell if (sell["fee"] and abs(sell["fee"]) > 0) else None)
            if fee_leg:
                txs.append(TransactionCreate(
                    source_platform="OKX",
                    timestamp_utc=fee_leg["time"],
                    event_type="FEE",
                    base_coin=fee_leg["unit"],
                    base_amount=-abs(fee_leg["fee"]),
                    raw_payload={"order_id": order_id},
                ))
            return txs

        # Unpaired leg (partial export) — record direction only
        leg = buy or sell
        if leg is None or leg["amount"] is None:
            return []
        return [TransactionCreate(
            source_platform="OKX",
            timestamp_utc=leg["time"],
            event_type="BUY" if buy else "SELL",
            base_coin=leg["unit"],
            base_amount=abs(leg["amount"]),
            raw_payload={**leg["raw"], "order_id": order_id},
        )]
