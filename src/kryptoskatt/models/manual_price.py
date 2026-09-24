"""Per-account manual prices.

Manual prices are user input, so they belong to one account only: a price one
user enters must never influence another user's tax calculation.
"""

from datetime import date
from typing import Any

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base
from kryptoskatt.models.price_cache import AMOUNT


class ManualPrice(Base):
    __tablename__ = "manual_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    price_sek: Mapped[Any] = mapped_column(AMOUNT, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "symbol", "date", name="uq_manual_prices_user_symbol_date"),
    )
