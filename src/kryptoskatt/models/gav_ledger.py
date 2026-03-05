"""GavLedger model."""

from datetime import datetime
from typing import Any

from sqlalchemy import String, Integer, DateTime, Numeric, Index
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base

# Numeric type for all monetary/amount values: precision=28, scale=18
AMOUNT = Numeric(precision=28, scale=18)


class GavLedger(Base):
    """Tracks Generalized Average Value (GAV) per coin for tax calculations."""

    __tablename__ = "gav_ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    coin: Mapped[str] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount_change: Mapped[Any] = mapped_column(AMOUNT, nullable=False)
    total_amount: Mapped[Any] = mapped_column(AMOUNT, nullable=False)
    total_cost_sek: Mapped[Any] = mapped_column(AMOUNT, nullable=False)
    gav_per_unit_sek: Mapped[Any] = mapped_column(AMOUNT, nullable=False)

    __table_args__ = (Index("ix_gav_ledger_coin_timestamp", "coin", "timestamp"),)
