"""Manual fiat cost entries for Bilaga T2 (hardware purchases, etc.)."""

from datetime import UTC, datetime

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, Numeric, String

from kryptoskatt.models.base import Base


class T2ManualEntry(Base):
    """A manually entered fiat cost that belongs on Bilaga T2.

    Used for hardware purchases, electricity bills, etc. paid in fiat currency
    where no blockchain transaction exists.
    """

    __tablename__ = "t2_manual_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    tax_year = Column(Integer, nullable=False, index=True)
    entry_date = Column(Date, nullable=True)          # date on invoice/receipt
    description = Column(String, nullable=False)       # e.g. "Inköp ASIC miner"
    amount_sek = Column(Numeric(18, 2), nullable=False)  # positive = cost (deduction)
    vendor = Column(String, nullable=True)             # e.g. "Inet", "Elgiganten"
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
