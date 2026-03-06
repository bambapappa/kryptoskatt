"""GAV History Report for Skatteverket audit trail."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from kryptoskatt.models.gav_ledger import GavLedger
from kryptoskatt.schemas import GavSnapshot


class GavHistoryReport:
    """Generate GAV history report from GavLedger entries."""

    def __init__(self, session: Session):
        self._session = session

    def generate(self, coin: Optional[str] = None, year: Optional[int] = None) -> list[GavSnapshot]:
        """Generate GAV history report.

        Args:
            coin: Optional coin to filter (e.g., 'ETH')
            year: Optional year to filter events

        Returns:
            List of GavSnapshot with timestamp, event_type, amount_change, total_units, total_cost, gav_per_unit
        """
        # Build query
        stmt = select(GavLedger)

        if coin:
            stmt = stmt.where(GavLedger.coin == coin)

        if year:
            # Filter to events within the year
            start = datetime(year, 1, 1, tzinfo=datetime.now().tzinfo)
            end = datetime(year + 1, 1, 1, tzinfo=datetime.now().tzinfo)
            stmt = stmt.where(GavLedger.timestamp >= start, GavLedger.timestamp < end)

        stmt = stmt.order_by(GavLedger.coin, GavLedger.timestamp)

        results = self._session.execute(stmt).scalars().all()

        # Convert to GavSnapshot
        return [
            GavSnapshot(
                coin=r.coin,
                timestamp=r.timestamp,
                event_type=r.event_type,
                amount_change=r.amount_change,
                gav_per_unit=r.gav_per_unit_sek,
                total_units=r.total_amount,
                total_cost=r.total_cost_sek,
            )
            for r in results
        ]
