"""Pydantic schemas for data transfer."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TransactionCreate(BaseModel):
    """Input schema from parsers."""

    source_platform: str
    timestamp_utc: datetime
    event_type: str
    base_coin: str
    base_amount: Decimal
    quote_coin: str | None = None
    quote_amount: Decimal | None = None
    fee_coin: str | None = None
    fee_amount: Decimal | None = None
    tx_hash: str | None = None
    from_address: str | None = None
    to_address: str | None = None
    price_sek: Decimal | None = None
    raw_payload: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class TransactionRead(TransactionCreate):
    """Output schema with additional fields."""

    id: int
    is_duplicate: bool = False
    import_batch_id: int | None = None


class WalletCreate(BaseModel):
    """Input for adding wallets."""

    address: str
    chain: str
    label: str
    is_mine: bool = True
    # "own" = normal wallet, "mining_pool" = mining payout address (e.g. Kryptex),
    # "depin" = DePIN reward address (Geodnet, Onocoy, Helium), "exchange" = CEX deposit
    category: str = "own"

    model_config = ConfigDict(from_attributes=True)


class WalletRead(WalletCreate):
    """Output schema for wallets."""

    id: int
    created_at: datetime


class K4SummaryRow(BaseModel):
    """One row in K4 report."""

    coin: str
    proceeds_sek: Decimal
    cost_basis_sek: Decimal
    gain_loss_sek: Decimal


class K4Report(BaseModel):
    """Complete K4 report."""

    tax_year: int
    rows: list[K4SummaryRow]
    total_gains: Decimal
    total_losses: Decimal


class GavSnapshot(BaseModel):
    """GAV state at a point in time."""

    coin: str
    timestamp: datetime
    event_type: str
    amount_change: Decimal
    gav_per_unit: Decimal
    total_units: Decimal
    total_cost: Decimal
