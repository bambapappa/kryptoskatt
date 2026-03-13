"""Custom chain configuration for user-defined blockchain explorers."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base


class CustomChainConfig(Base):
    __tablename__ = "custom_chain_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    chain_name: Mapped[str] = mapped_column(String(100), nullable=False)
    explorer_url: Mapped[str] = mapped_column(String(512), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    adapter_type: Mapped[str] = mapped_column(String(50), nullable=False)
    native_coin: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    chain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("account_id", "chain_name", name="uq_custom_chain_account_name"),
        Index("ix_custom_chain_account_id", "account_id"),
    )
