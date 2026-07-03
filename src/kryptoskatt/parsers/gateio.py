"""Gate.io CSV parser.

Gate.io "My bill" / transaction history export has columns:
no, time, action_desc, action_data, type, change_amount, amount, total

- `type` holds the currency symbol, `change_amount` the signed amount.
- Trades appear as "Order Placed" (spent, negative) and "Order Filled"
  (received, positive) rows that share the same `action_data` (order id),
  plus optional "Trading Fees" rows.
- Deposits/Withdrawals are single rows.
"""

import csv
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from kryptoskatt.schemas import TransactionCreate

PLATFORM_NAME = "gateio"

_TRADE_ACTIONS = {"order placed", "order filled", "order fullfilled", "order fulfilled"}
_FEE_ACTIONS = {"trading fees", "trade fee"}
_DEPOSIT_ACTIONS = {"deposits", "deposit"}
_WITHDRAW_ACTIONS = {"withdrawals", "withdraw", "withdrawal"}
_REWARD_ACTIONS = {"airdrop", "airdrop bonus", "hodl interest", "interest income",
                   "referral superior rebate"}


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
    """Parse Gate.io timestamp: '2024-01-15 10:30:05' (exported in UTC)."""
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


@dataclass
class ParseResult:
    """Result of parsing a Gate.io CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class GateIoParser:
    """Parser for Gate.io transaction history CSV exports."""

    def parse(self, file_path: Path) -> ParseResult:
        transactions: list[TransactionCreate] = []
        errors: list[str] = []
        # Buffer trade legs and fees by order id (action_data)
        orders: dict[str, dict[str, list[dict]]] = {}

        try:
            with open(file_path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception as e:
            return ParseResult(errors=[f"Failed to read file: {e}"])

        for row_num, row in enumerate(rows, start=2):
            try:
                action = (row.get("action_desc") or "").strip().lower()
                currency = (row.get("type") or "").strip().upper()
                amount = _parse_decimal(row.get("change_amount"))
                timestamp = _parse_timestamp(row.get("time") or "")
                order_id = (row.get("action_data") or "").strip()
                raw_payload = dict(row)

                if amount is None or not currency:
                    raise ValueError("Missing change_amount/currency")

                if action in _TRADE_ACTIONS:
                    side = "received" if amount > 0 else "spent"
                    orders.setdefault(order_id, {}).setdefault(side, []).append(
                        {"time": timestamp, "amount": amount, "currency": currency, "raw": raw_payload}
                    )
                elif action in _FEE_ACTIONS:
                    orders.setdefault(order_id, {}).setdefault("fee", []).append(
                        {"time": timestamp, "amount": amount, "currency": currency, "raw": raw_payload}
                    )
                elif action in _DEPOSIT_ACTIONS:
                    transactions.append(TransactionCreate(
                        source_platform="GATEIO",
                        timestamp_utc=timestamp,
                        event_type="TRANSFER_IN",
                        base_coin=currency,
                        base_amount=abs(amount),
                        raw_payload=raw_payload,
                    ))
                elif action in _WITHDRAW_ACTIONS:
                    transactions.append(TransactionCreate(
                        source_platform="GATEIO",
                        timestamp_utc=timestamp,
                        event_type="TRANSFER_OUT",
                        base_coin=currency,
                        base_amount=-abs(amount),
                        raw_payload=raw_payload,
                    ))
                elif action in _REWARD_ACTIONS and amount > 0:
                    if "airdrop" in action:
                        rtype = "airdrop"
                    elif "interest" in action:
                        rtype = "interest"
                    else:
                        rtype = "other"
                    transactions.append(TransactionCreate(
                        source_platform="GATEIO",
                        timestamp_utc=timestamp,
                        event_type="REWARD",
                        base_coin=currency,
                        base_amount=amount,
                        reward_type=rtype,
                        raw_payload=raw_payload,
                    ))
                # other actions are skipped silently
            except Exception as e:
                errors.append(f"Row {row_num}: {e}")

        # Pair buffered trade legs into BUY transactions
        for order_id, legs in orders.items():
            try:
                transactions.extend(self._pair_order(order_id, legs))
            except Exception as e:
                errors.append(f"Order {order_id}: {e}")

        return ParseResult(transactions=transactions, errors=errors)

    def _pair_order(self, order_id: str, legs: dict[str, list[dict]]) -> list[TransactionCreate]:
        received = legs.get("received", [])
        spent = legs.get("spent", [])
        fees = legs.get("fee", [])
        txs: list[TransactionCreate] = []

        for i in range(max(len(received), len(spent))):
            rec = received[i] if i < len(received) else None
            spe = spent[i] if i < len(spent) else None
            if rec and spe:
                txs.append(TransactionCreate(
                    source_platform="GATEIO",
                    timestamp_utc=rec["time"],
                    event_type="BUY",
                    base_coin=rec["currency"],
                    base_amount=abs(rec["amount"]),
                    quote_coin=spe["currency"],
                    quote_amount=abs(spe["amount"]),
                    raw_payload={**rec["raw"], "spent_leg": spe["raw"], "order_id": order_id},
                ))
            elif rec:
                txs.append(TransactionCreate(
                    source_platform="GATEIO",
                    timestamp_utc=rec["time"],
                    event_type="BUY",
                    base_coin=rec["currency"],
                    base_amount=abs(rec["amount"]),
                    raw_payload={**rec["raw"], "order_id": order_id},
                ))
            elif spe:
                txs.append(TransactionCreate(
                    source_platform="GATEIO",
                    timestamp_utc=spe["time"],
                    event_type="SELL",
                    base_coin=spe["currency"],
                    base_amount=abs(spe["amount"]),
                    raw_payload={**spe["raw"], "order_id": order_id},
                ))

        for fee in fees:
            if fee["amount"] and abs(fee["amount"]) > 0:
                txs.append(TransactionCreate(
                    source_platform="GATEIO",
                    timestamp_utc=fee["time"],
                    event_type="FEE",
                    base_coin=fee["currency"],
                    base_amount=-abs(fee["amount"]),
                    raw_payload={**fee["raw"], "order_id": order_id},
                ))

        return txs
