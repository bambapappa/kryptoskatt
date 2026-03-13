"""API layer Pydantic response models for v1."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class AccountCreateResponse(BaseModel):
    account_id: str


class LoginRequest(BaseModel):
    account_id: str


class WalletBulkCreate(BaseModel):
    wallets: list[dict[str, Any]]


class WalletBulkResponse(BaseModel):
    created: int
    errors: list[dict[str, Any]]


class FetchRequest(BaseModel):
    wallet_ids: list[int] | None = None


class FetchError(BaseModel):
    wallet_id: int
    address: str
    chain: str
    error: str


class FetchResponse(BaseModel):
    fetched: int
    saved: int
    skipped: int
    errors: list[FetchError]


class CalculateRequest(BaseModel):
    year: int | None = None


class DedupSummary(BaseModel):
    total_checked: int
    exact_matches: int
    heuristic_matches: int


class TransferSummary(BaseModel):
    matched: int
    unmatched: int
    ambiguous: int


class EnrichmentSummary(BaseModel):
    total: int
    enriched: int
    skipped_unknown_coin: int
    skipped_api_miss: int


class CalculateResponse(BaseModel):
    disposals_created: int
    gav_entries_created: int
    dedup_report: DedupSummary
    transfer_report: TransferSummary
    enrichment_report: EnrichmentSummary
    warnings: list[str]


class TransactionListResponse(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})
    transactions: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class CustomChainConfigCreate(BaseModel):
    chain_name: str
    explorer_url: str
    api_key: str | None = None
    adapter_type: str
    native_coin: str = ""       # main coin symbol, e.g. "ETH", "GLMR"
    chain_id: int | None = None  # required for Etherscan-type adapters


class CustomChainConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    chain_name: str
    explorer_url: str
    adapter_type: str
    native_coin: str = ""
    chain_id: int | None = None
    created_at: datetime
