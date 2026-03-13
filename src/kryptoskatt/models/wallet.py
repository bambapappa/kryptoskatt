"""Wallet model."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base


class Wallet(Base):
    """Represents a tracked cryptocurrency wallet/address."""

    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    address: Mapped[str] = mapped_column(String(256), nullable=False)
    chain: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_mine: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Category: "own" (default), "mining_pool", "depin", "exchange"
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="own")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_wallets_address_chain", "address", "chain"),
        Index("ix_wallets_user_id_chain", "user_id", "chain"),
    )
