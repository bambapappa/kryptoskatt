"""TransferLink model."""

from typing import Any

from sqlalchemy import String, Integer, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base


class TransferLink(Base):
    """Links two transactions representing a transfer (outgoing to incoming)."""

    __tablename__ = "transfer_links"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tx_out_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    tx_in_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    match_method: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[Any | None] = mapped_column(Numeric(precision=5, scale=4), nullable=True)
