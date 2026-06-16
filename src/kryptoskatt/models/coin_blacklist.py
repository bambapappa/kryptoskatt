"""CoinBlacklist model — coins excluded from GAV/K4/T2 calculations."""

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base


class CoinBlacklist(Base):
    """Coins to ignore in tax calculations. Transactions remain in DB for audit.

    Scoped per account: each user maintains their own blacklist so one user can
    never affect another user's tax calculation. Legacy rows created before
    multi-tenancy may have a NULL user_id (see migration 013).
    """

    __tablename__ = "coin_blacklist"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True
    )
    coin_symbol: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "coin_symbol", name="uq_coin_blacklist_user_symbol"),
        Index("ix_coin_blacklist_user_id", "user_id"),
    )
