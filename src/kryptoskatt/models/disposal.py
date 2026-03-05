"""Disposal model."""

from datetime import datetime
from typing import Any

from sqlalchemy import String, Integer, DateTime, Numeric, Index
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base

# Numeric type for all monetary/amount values: precision=28, scale=18
AMOUNT = Numeric(precision=28, scale=18)


class Disposal(Base):
    """Represents a taxable disposal event (sale or transfer out)."""

    __tablename__ = "disposals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    coin: Mapped[str] = mapped_column(String(20), nullable=False)
    sell_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sell_amount: Mapped[Any] = mapped_column(AMOUNT, nullable=False)
    proceeds_sek: Mapped[Any] = mapped_column(AMOUNT, nullable=False)
    cost_basis_sek: Mapped[Any] = mapped_column(AMOUNT, nullable=False)
    gain_loss_sek: Mapped[Any] = mapped_column(AMOUNT, nullable=False)
    gav_at_disposal: Mapped[Any] = mapped_column(AMOUNT, nullable=False)

    __table_args__ = (
        Index("ix_disposals_tax_year", "tax_year"),
        Index("ix_disposals_coin_timestamp", "coin", "sell_timestamp"),
    )
