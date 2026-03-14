"""Manual income entries for Bilaga T2 (mining rewards not captured automatically, etc.)."""

from datetime import UTC, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from kryptoskatt.models.base import Base

# Allowed event categories for manual T2 income
T2_INCOME_CATEGORIES = ["REWARD", "MINING", "DEPIN", "STAKING", "OTHER"]


class T2ManualIncomeEntry(Base):
    """A manually entered income entry that belongs on Bilaga T2.

    Used when a reward or mining income was not automatically captured via
    wallet category detection — for example income received off-chain or
    from a service that lacks a blockchain adapter.
    """

    __tablename__ = "t2_manual_income_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    tax_year = Column(Integer, nullable=False, index=True)
    entry_date = Column(Date, nullable=True)           # date received
    category = Column(String(50), nullable=False, default="REWARD")  # from T2_INCOME_CATEGORIES
    description = Column(String, nullable=False)        # e.g. "Geodnet mining Jan 2024"
    amount_sek = Column(Numeric(18, 2), nullable=False)  # positive = income
    source = Column(String, nullable=True)              # e.g. "Geodnet", "Helium"
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
