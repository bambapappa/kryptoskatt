"""PriceCache model."""

from datetime import date
from typing import Any

from sqlalchemy import Date, Index, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base

# Numeric type for all monetary/amount values: precision=28, scale=18
AMOUNT = Numeric(precision=28, scale=18)


class PriceCache(Base):
    """Caches historical price data for coins."""

    __tablename__ = "price_cache"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    coin_id: Mapped[str] = mapped_column(String(50), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    price_sek: Mapped[Any] = mapped_column(AMOUNT, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        UniqueConstraint("coin_id", "date", name="uq_price_cache_coin_date"),
        Index("ix_price_cache_coin_id_date", "coin_id", "date"),
    )
