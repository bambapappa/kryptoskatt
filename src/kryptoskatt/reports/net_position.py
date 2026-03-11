"""Net position report: holding changes for coins without a known price."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from kryptoskatt.enums import EventType
from kryptoskatt.models.transaction import Transaction

# Event types that increase holdings
_INFLOW_EVENTS = {
    EventType.BUY,
    EventType.SWAP_IN,
    EventType.TRANSFER_IN,
    EventType.REWARD,
}

# Event types that decrease holdings
_OUTFLOW_EVENTS = {
    EventType.SELL,
    EventType.SWAP_OUT,
    EventType.TRANSFER_OUT,
}


@dataclass
class NetPositionRow:
    coin: str
    total_received: Decimal   # sum of inflows (positive)
    total_sent: Decimal       # sum of outflows (positive magnitude)
    net_change: Decimal       # total_received - total_sent


class NetPositionReport:
    """Computes net holding changes for the coins that still have no price_sek."""

    def __init__(self, session: Session):
        self._session = session

    def generate(self, year: int) -> list[NetPositionRow]:
        """Return one row per coin that has transactions in the given year
        but where price_sek is NULL on all of them (i.e. completely unpriced).

        Coins that have at least one priced transaction are not included here —
        they should appear in the normal K4 report.
        """
        # All non-duplicate transactions for the year (by timestamp year)
        txs = (
            self._session.query(Transaction)
            .filter(
                Transaction.is_duplicate.is_(False),
                Transaction.event_type.in_(
                    [e.value for e in (_INFLOW_EVENTS | _OUTFLOW_EVENTS)]
                ),
            )
            .all()
        )

        # Filter to given year
        txs = [tx for tx in txs if tx.timestamp_utc.year == year]

        # Group by coin
        coin_txs: dict[str, list[Transaction]] = {}
        for tx in txs:
            coin_txs.setdefault(tx.base_coin, []).append(tx)

        rows: list[NetPositionRow] = []

        for coin, coin_tx_list in sorted(coin_txs.items()):
            # Only include coins where ALL transactions are unpriced
            if any(tx.price_sek is not None for tx in coin_tx_list):
                continue

            total_received = Decimal("0")
            total_sent = Decimal("0")

            for tx in coin_tx_list:
                if not tx.base_amount:
                    continue
                amount = Decimal(str(tx.base_amount))
                event_type = tx.event_type

                if event_type in {e.value for e in _INFLOW_EVENTS}:
                    total_received += abs(amount)
                elif event_type in {e.value for e in _OUTFLOW_EVENTS}:
                    total_sent += abs(amount)

            if total_received == Decimal("0") and total_sent == Decimal("0"):
                continue

            rows.append(
                NetPositionRow(
                    coin=coin,
                    total_received=total_received.quantize(Decimal("0.000001")),
                    total_sent=total_sent.quantize(Decimal("0.000001")),
                    net_change=(total_received - total_sent).quantize(Decimal("0.000001")),
                )
            )

        return rows
