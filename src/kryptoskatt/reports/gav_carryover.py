"""Year-to-year GAV carryover.

Shows the closing GAV balance per coin at the end of a tax year (the "utgående
balans" that carries into next year's declaration) alongside the opening
balance carried in from the previous year, and the change between them.

The running balances already live in :class:`GavLedger` (rebuilt on every
``GavEngine.calculate()`` across the full history), so the closing balance for a
year is simply the last ledger entry for that coin dated in that year or
earlier. Comparing by calendar year keeps this robust whether the store returns
timezone-aware (PostgreSQL) or naive (SQLite) timestamps.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from kryptoskatt.models.gav_ledger import GavLedger

_Q = Decimal("0.01")
_QU = Decimal("0.00000001")


@dataclass
class CarryoverRow:
    coin: str
    opening_units: Decimal
    opening_cost_sek: Decimal
    opening_gav_sek: Decimal
    closing_units: Decimal
    closing_cost_sek: Decimal
    closing_gav_sek: Decimal
    units_delta: Decimal
    cost_delta_sek: Decimal


@dataclass
class CarryoverReport:
    year: int
    rows: list[CarryoverRow]
    opening_total_cost_sek: Decimal
    closing_total_cost_sek: Decimal


class GavCarryoverReport:
    """Computes opening/closing GAV balances per coin for a tax year."""

    def __init__(self, session: Session, user_id: int):
        self._session = session
        self._user_id = user_id

    def generate(self, year: int) -> CarryoverReport:
        entries = list(
            self._session.execute(
                select(GavLedger)
                .where(GavLedger.user_id == self._user_id)
                .order_by(GavLedger.coin, GavLedger.timestamp, GavLedger.id)
            ).scalars()
        )

        # Group chronological entries per coin.
        by_coin: dict[str, list[GavLedger]] = {}
        for e in entries:
            by_coin.setdefault(e.coin, []).append(e)

        rows: list[CarryoverRow] = []
        opening_total = Decimal("0")
        closing_total = Decimal("0")

        for coin, coin_entries in by_coin.items():
            opening = self._balance_at_year_end(coin_entries, year - 1)
            closing = self._balance_at_year_end(coin_entries, year)

            open_units, open_cost = opening
            close_units, close_cost = closing

            # Skip coins that are flat at zero across the whole window (no holdings
            # entering, leaving, or held) — nothing to carry over.
            if open_units == 0 and close_units == 0 and open_cost == 0 and close_cost == 0:
                continue

            open_gav = (open_cost / open_units) if open_units > 0 else Decimal("0")
            close_gav = (close_cost / close_units) if close_units > 0 else Decimal("0")

            opening_total += open_cost
            closing_total += close_cost

            rows.append(
                CarryoverRow(
                    coin=coin,
                    opening_units=open_units.quantize(_QU),
                    opening_cost_sek=open_cost.quantize(_Q),
                    opening_gav_sek=open_gav.quantize(_Q),
                    closing_units=close_units.quantize(_QU),
                    closing_cost_sek=close_cost.quantize(_Q),
                    closing_gav_sek=close_gav.quantize(_Q),
                    units_delta=(close_units - open_units).quantize(_QU),
                    cost_delta_sek=(close_cost - open_cost).quantize(_Q),
                )
            )

        rows.sort(key=lambda r: r.coin)
        return CarryoverReport(
            year=year,
            rows=rows,
            opening_total_cost_sek=opening_total.quantize(_Q),
            closing_total_cost_sek=closing_total.quantize(_Q),
        )

    @staticmethod
    def _balance_at_year_end(
        coin_entries: list[GavLedger], year: int
    ) -> tuple[Decimal, Decimal]:
        """Return (units, cost_sek) from the last entry dated in ``year`` or before."""
        last = None
        for e in coin_entries:
            if e.timestamp.year <= year:
                last = e
            else:
                break
        if last is None:
            return Decimal("0"), Decimal("0")
        return Decimal(str(last.total_amount)), Decimal(str(last.total_cost_sek))
