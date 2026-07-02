"""Fetch endpoint for API v1 — triggers on-chain transaction fetching."""

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kryptoskatt.chains import get_registry_for_user
from kryptoskatt.cli.fetch_cmd import create_import_batch_for_fetch, save_fetched_transactions
from kryptoskatt.db import get_db
from kryptoskatt.models.account import Account
from kryptoskatt.services.rate_limiter import fetch_limiter
from kryptoskatt.services.wallet import WalletService
from kryptoskatt.web.auth import get_current_account

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 30

router = APIRouter()


_get_db = get_db


class FetchRequest(BaseModel):
    wallet_ids: list[int] | None = None


class FetchResponse(BaseModel):
    fetched: int
    saved: int
    skipped: int
    errors: list[str]
    skipped_chains: list[str] = []


@router.post("", response_model=FetchResponse)
def fetch_transactions(
    body: FetchRequest,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
) -> Any:
    """Fetch on-chain transactions for the authenticated user's wallets.

    If wallet_ids is provided, only fetch for those wallets. Otherwise fetch
    all wallets belonging to the account.
    """
    if not fetch_limiter.is_allowed(str(account.id)):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Max 5 fetch requests per minute.")

    uid = account.id
    wallet_service = WalletService(db, uid)
    all_wallets = wallet_service.list_wallets(mine_only=True)

    if body.wallet_ids:
        wallets = [w for w in all_wallets if w.id in body.wallet_ids]
    else:
        wallets = all_wallets

    if not wallets:
        return FetchResponse(fetched=0, saved=0, skipped=0, errors=["No wallets found"])

    registry = get_registry_for_user(db, uid)
    total_saved = 0
    total_skipped = 0
    fetched_count = 0
    errors: list[str] = []
    skipped_chains: set[str] = set()

    for wallet in wallets:
        adapter = registry.get_adapter(wallet.chain)
        if adapter is None:
            errors.append(f"No adapter for chain {wallet.chain} (wallet id={wallet.id})")
            skipped_chains.add(wallet.chain)
            continue

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(adapter.fetch_transactions, wallet.address, wallet.chain)
                try:
                    txs = future.result(timeout=FETCH_TIMEOUT_SECONDS)
                except FuturesTimeoutError:
                    msg = f"Timeout fetching wallet id={wallet.id} ({wallet.address[:20]}…): exceeded {FETCH_TIMEOUT_SECONDS}s"
                    logger.warning(msg)
                    errors.append(msg)
                    continue
            if txs:
                batch = create_import_batch_for_fetch(db, 1, len(txs), uid)
                saved, skipped = save_fetched_transactions(
                    db,
                    txs,
                    batch,
                    user_id=uid,
                    wallet_id=wallet.id,
                    chain_tag=wallet.chain,
                )
                total_saved += saved
                total_skipped += skipped
            fetched_count += 1
        except Exception as exc:
            msg = f"Failed to fetch wallet id={wallet.id} ({wallet.address[:20]}…): {exc}"
            logger.warning(msg)
            errors.append(msg)

    return FetchResponse(
        fetched=fetched_count,
        saved=total_saved,
        skipped=total_skipped,
        errors=errors,
        skipped_chains=sorted(skipped_chains),
    )
