"""Bilaga T2 income report for mining and DePIN rewards.

Swedish tax rules:
- Mining rewards and DePIN (Geodnet, Onocoy, Helium) income are reported on Bilaga T2
  as income from hobby/business activity, NOT on K4.
- The SEK value on the day of receipt defines both the taxable income AND the GAV
  acquisition cost for future disposals.
- Hardware and other allowable deductions are also tracked here.

Income is identified by two criteria (either):
  1. Event type is REWARD (mining pool payouts, staking rewards).
  2. Event type is TRANSFER_IN and from_address belongs to a wallet with
     category "mining_pool" or "depin".

Costs (deductions) are identified by:
  - TRANSFER_OUT or SELL/SWAP_OUT where to_address belongs to a wallet with
    category "hardware_vendor". The SEK value at time of transaction is the
    deductible cost.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import extract
from sqlalchemy.orm import Session

from kryptoskatt.enums import EventType
from kryptoskatt.models.t2_manual_entry import T2ManualEntry
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.wallet import Wallet

_INCOME_CATEGORIES = {"mining_pool", "depin"}
_COST_CATEGORIES = {"hardware_vendor"}

# All event types that can represent an outgoing payment for goods/services
_OUTGOING_TYPES = {
    EventType.TRANSFER_OUT.value,
    EventType.SELL.value,
    EventType.SWAP_OUT.value,
}


@dataclass
class T2IncomeRow:
    """One aggregated income row per (coin, category, label)."""

    coin: str
    category: str           # "mining_pool" | "depin" | "reward"
    label: str              # human-readable source label
    event_count: int
    total_units: Decimal
    total_sek: Decimal      # sum of price_sek * base_amount; 0 if price unknown
    unpriced_units: Decimal  # units where price was unknown


@dataclass
class T2CostRow:
    """One aggregated cost row per (coin, category, label)."""

    coin: str
    category: str           # "hardware_vendor" etc.
    label: str
    event_count: int
    total_units: Decimal
    total_sek: Decimal      # SEK value paid (deductible cost)
    unpriced_units: Decimal


@dataclass
class T2ManualCostRow:
    """One manually entered fiat cost entry."""

    id: int
    entry_date: object      # date or None
    description: str
    amount_sek: Decimal
    vendor: str


@dataclass
class T2Report:
    """Complete Bilaga T2 report for a tax year."""

    tax_year: int
    income_rows: list[T2IncomeRow]
    cost_rows: list[T2CostRow]
    manual_cost_rows: list[T2ManualCostRow]
    total_income_sek: Decimal
    total_cost_sek: Decimal
    net_sek: Decimal


class T2IncomeReport:
    """Generates Bilaga T2 income/cost report from the transaction database."""

    def __init__(self, session: Session, user_id: int):
        self.session = session
        self.user_id = user_id

    def generate(self, year: int) -> T2Report:
        """Return T2Report for *year*."""
        # ── Build wallet address maps ─────────────────────────────────────────
        income_address_map: dict[str, tuple[str, str]] = {}  # addr → (cat, label)
        cost_address_map: dict[str, tuple[str, str]] = {}

        for w in self.session.query(Wallet).filter(Wallet.user_id == self.user_id).all():
            label = w.label or w.category
            if w.category in _INCOME_CATEGORIES:
                income_address_map[w.address] = (w.category, label)
            elif w.category in _COST_CATEGORIES:
                cost_address_map[w.address] = (w.category, label)

        # ── Income ────────────────────────────────────────────────────────────
        income_txs: list[tuple[Transaction, str, str]] = []

        # REWARD events (any source)
        for tx in (
            self.session.query(Transaction)
            .filter(
                Transaction.user_id == self.user_id,
                Transaction.event_type == EventType.REWARD.value,
                Transaction.is_duplicate.is_(False),
                extract("year", Transaction.timestamp_utc) == year,
            )
            .all()
        ):
            income_txs.append((tx, "reward", tx.source_platform or "reward"))

        # TRANSFER_IN from mining_pool / depin wallets
        if income_address_map:
            for tx in (
                self.session.query(Transaction)
                .filter(
                    Transaction.user_id == self.user_id,
                    Transaction.event_type == EventType.TRANSFER_IN.value,
                    Transaction.is_duplicate.is_(False),
                    extract("year", Transaction.timestamp_utc) == year,
                    Transaction.from_address.in_(list(income_address_map.keys())),
                )
                .all()
            ):
                cat, label = income_address_map[tx.from_address]
                income_txs.append((tx, cat, label))

        income_agg: dict[tuple[str, str, str], list] = {}
        for tx, category, label in income_txs:
            key = (tx.base_coin, category, label)
            if key not in income_agg:
                income_agg[key] = [0, Decimal("0"), Decimal("0"), Decimal("0")]
            amount = abs(tx.base_amount) if tx.base_amount else Decimal("0")
            income_agg[key][0] += 1
            income_agg[key][1] += amount
            if tx.price_sek is not None and tx.price_sek > 0:
                income_agg[key][2] += amount * tx.price_sek
            else:
                income_agg[key][3] += amount

        income_rows: list[T2IncomeRow] = []
        total_income = Decimal("0")
        for (coin, category, label), (count, units, sek, unpriced) in sorted(income_agg.items()):
            income_rows.append(
                T2IncomeRow(
                    coin=coin,
                    category=category,
                    label=label,
                    event_count=count,
                    total_units=units.normalize(),
                    total_sek=sek.quantize(Decimal("0.01")),
                    unpriced_units=unpriced.normalize(),
                )
            )
            total_income += sek

        # ── Costs ─────────────────────────────────────────────────────────────
        cost_txs: list[tuple[Transaction, str, str]] = []

        if cost_address_map:
            for tx in (
                self.session.query(Transaction)
                .filter(
                    Transaction.user_id == self.user_id,
                    Transaction.event_type.in_(list(_OUTGOING_TYPES)),
                    Transaction.is_duplicate.is_(False),
                    extract("year", Transaction.timestamp_utc) == year,
                    Transaction.to_address.in_(list(cost_address_map.keys())),
                )
                .all()
            ):
                cat, label = cost_address_map[tx.to_address]
                cost_txs.append((tx, cat, label))

        cost_agg: dict[tuple[str, str, str], list] = {}
        for tx, category, label in cost_txs:
            key = (tx.base_coin, category, label)
            if key not in cost_agg:
                cost_agg[key] = [0, Decimal("0"), Decimal("0"), Decimal("0")]
            amount = abs(tx.base_amount) if tx.base_amount else Decimal("0")
            cost_agg[key][0] += 1
            cost_agg[key][1] += amount
            if tx.price_sek is not None and tx.price_sek > 0:
                cost_agg[key][2] += amount * tx.price_sek
            else:
                cost_agg[key][3] += amount

        cost_rows: list[T2CostRow] = []
        total_cost = Decimal("0")
        for (coin, category, label), (count, units, sek, unpriced) in sorted(cost_agg.items()):
            cost_rows.append(
                T2CostRow(
                    coin=coin,
                    category=category,
                    label=label,
                    event_count=count,
                    total_units=units.normalize(),
                    total_sek=sek.quantize(Decimal("0.01")),
                    unpriced_units=unpriced.normalize(),
                )
            )
            total_cost += sek

        # ── Manual fiat cost entries ───────────────────────────────────────────
        manual_entries = (
            self.session.query(T2ManualEntry)
            .filter(T2ManualEntry.user_id == self.user_id, T2ManualEntry.tax_year == year)
            .order_by(T2ManualEntry.entry_date, T2ManualEntry.id)
            .all()
        )
        manual_cost_rows = [
            T2ManualCostRow(
                id=e.id,
                entry_date=e.entry_date,
                description=e.description,
                amount_sek=Decimal(str(e.amount_sek)),
                vendor=e.vendor or "",
            )
            for e in manual_entries
        ]
        total_manual_cost = sum((r.amount_sek for r in manual_cost_rows), Decimal("0"))
        total_cost += total_manual_cost

        net = total_income - total_cost

        return T2Report(
            tax_year=year,
            income_rows=income_rows,
            cost_rows=cost_rows,
            manual_cost_rows=manual_cost_rows,
            total_income_sek=total_income.quantize(Decimal("0.01")),
            total_cost_sek=total_cost.quantize(Decimal("0.01")),
            net_sek=net.quantize(Decimal("0.01")),
        )
