"""Transaction and ImportBatch models."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    Numeric,
    ForeignKey,
    JSON,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base

# Numeric type for all monetary/amount values: precision=28, scale=18
AMOUNT = Numeric(precision=28, scale=18)


class ImportBatch(Base):
    """Represents a batch of imported transactions from a source."""

    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)


class Transaction(Base):
    """Represents a cryptocurrency transaction."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    import_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True
    )
    wallet_id: Mapped[int | None] = mapped_column(ForeignKey("wallets.id"), nullable=True)
    source_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    base_coin: Mapped[str] = mapped_column(String(20), nullable=False)
    base_amount: Mapped[Any] = mapped_column(AMOUNT, nullable=False)
    quote_coin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quote_amount: Mapped[Any | None] = mapped_column(AMOUNT, nullable=True)
    fee_coin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fee_amount: Mapped[Any | None] = mapped_column(AMOUNT, nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    from_address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    to_address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    price_sek: Mapped[Any | None] = mapped_column(AMOUNT, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_payload: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_transactions_tx_hash", "tx_hash"),
        Index("ix_transactions_timestamp_utc", "timestamp_utc"),
        Index("ix_transactions_base_coin_timestamp", "base_coin", "timestamp_utc"),
    )
