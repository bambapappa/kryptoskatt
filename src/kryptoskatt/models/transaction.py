"""Transaction and ImportBatch models."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base

# Numeric type for all monetary/amount values: precision=28, scale=18
AMOUNT = Numeric(precision=28, scale=18)


class ImportBatch(Base):
    """Represents a batch of imported transactions from a source."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)


class Transaction(Base):
    """Represents a cryptocurrency transaction."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True
    )
    wallet_id: Mapped[int | None] = mapped_column(ForeignKey("wallets.id"), nullable=True)
    source_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    base_coin: Mapped[str] = mapped_column(String(100), nullable=False)
    base_amount: Mapped[Any] = mapped_column(AMOUNT, nullable=False)
    quote_coin: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quote_amount: Mapped[Any | None] = mapped_column(AMOUNT, nullable=True)
    fee_coin: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fee_amount: Mapped[Any | None] = mapped_column(AMOUNT, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    from_address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    to_address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    price_sek: Mapped[Any | None] = mapped_column(AMOUNT, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Sub-classification for REWARD events: staking | mining | airdrop | interest | other
    reward_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    raw_payload: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_transactions_tx_hash", "tx_hash"),
        Index("ix_transactions_timestamp_utc", "timestamp_utc"),
        Index("ix_transactions_base_coin_timestamp", "base_coin", "timestamp_utc"),
        Index("ix_transactions_user_id", "user_id"),
        Index("ix_transactions_user_id_timestamp", "user_id", "timestamp_utc"),
    )
