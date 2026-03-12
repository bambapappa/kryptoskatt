"""CoinBlacklist model — coins excluded from GAV/K4/T2 calculations."""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base


class CoinBlacklist(Base):
    """Coins to ignore in tax calculations. Transactions remain in DB for audit."""

    __tablename__ = "coin_blacklist"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    coin_symbol: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
