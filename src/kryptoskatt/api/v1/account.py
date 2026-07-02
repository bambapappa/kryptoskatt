"""Account-level endpoints: GDPR data export and account deletion."""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kryptoskatt.db import get_db
from kryptoskatt.models.account import Account
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


_get_db = get_db


class DeleteAccountRequest(BaseModel):
    confirm: str


@router.get("/export")
def export_account_data(
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Export all account data as JSON for GDPR data portability."""
    from kryptoskatt.models.custom_chain_config import CustomChainConfig
    from kryptoskatt.models.disposal import Disposal
    from kryptoskatt.models.gav_ledger import GavLedger
    from kryptoskatt.models.t2_manual_entry import T2ManualEntry
    from kryptoskatt.models.t2_manual_income_entry import T2ManualIncomeEntry
    from kryptoskatt.models.transaction import Transaction
    from kryptoskatt.models.wallet import Wallet

    wallets = db.query(Wallet).filter(Wallet.user_id == account.id).all()
    transactions = (
        db.query(Transaction)
        .filter(Transaction.user_id == account.id)
        .order_by(Transaction.timestamp_utc)
        .all()
    )
    disposals = (
        db.query(Disposal)
        .filter(Disposal.user_id == account.id)
        .order_by(Disposal.tax_year)
        .all()
    )
    gav_ledger = (
        db.query(GavLedger)
        .filter(GavLedger.user_id == account.id)
        .order_by(GavLedger.id)
        .all()
    )
    t2_entries = (
        db.query(T2ManualEntry)
        .filter(T2ManualEntry.user_id == account.id)
        .all()
    )
    t2_income_entries = (
        db.query(T2ManualIncomeEntry)
        .filter(T2ManualIncomeEntry.user_id == account.id)
        .all()
    )
    custom_chains = (
        db.query(CustomChainConfig)
        .filter(CustomChainConfig.account_id == account.id)
        .all()
    )

    def _wallet_dict(w):
        return {
            "id": w.id,
            "address": w.address,
            "chain": w.chain,
            "label": w.label,
            "is_mine": w.is_mine,
            "category": w.category,
            "created_at": str(w.created_at),
        }

    def _tx_dict(t):
        return {
            "id": t.id,
            "timestamp_utc": str(t.timestamp_utc),
            "event_type": str(t.event_type),
            "base_coin": t.base_coin,
            "base_amount": str(t.base_amount),
            "quote_coin": t.quote_coin,
            "quote_amount": str(t.quote_amount) if t.quote_amount is not None else None,
            "fee_coin": t.fee_coin,
            "fee_amount": str(t.fee_amount) if t.fee_amount is not None else None,
            "source_platform": t.source_platform,
            "tx_hash": t.tx_hash,
            "is_duplicate": t.is_duplicate,
        }

    def _disposal_dict(d):
        return {
            "id": d.id,
            "tax_year": d.tax_year,
            "coin": d.coin,
            "amount_disposed": str(d.amount_disposed),
            "proceeds_sek": str(d.proceeds_sek),
            "cost_basis_sek": str(d.cost_basis_sek),
            "gain_loss_sek": str(d.gain_loss_sek),
            "timestamp_utc": str(d.timestamp_utc),
        }

    def _ledger_dict(g):
        return {
            "id": g.id,
            "coin": g.coin,
            "event_type": str(g.event_type),
            "amount_change": str(g.amount_change),
            "running_balance": str(g.running_balance),
            "gav_per_unit_sek": str(g.gav_per_unit_sek),
            "timestamp_utc": str(g.timestamp_utc),
        }

    def _t2_dict(e):
        return {
            "id": e.id,
            "year": e.year,
            "description": e.description,
            "amount_sek": str(e.amount_sek),
        }

    def _t2_income_dict(e):
        return {
            "id": e.id,
            "year": e.year,
            "description": e.description,
            "amount_sek": str(e.amount_sek),
        }

    def _chain_dict(c):
        return {
            "id": c.id,
            "chain_name": c.chain_name,
            "adapter_type": c.adapter_type,
            "explorer_url": c.explorer_url,
            "native_coin": c.native_coin,
            "created_at": str(c.created_at),
        }

    data = {
        "exported_at": datetime.now(UTC).isoformat(),
        "account_id": account.account_id,
        "wallets": [_wallet_dict(w) for w in wallets],
        "transactions": [_tx_dict(t) for t in transactions],
        "disposals": [_disposal_dict(d) for d in disposals],
        "gav_ledger": [_ledger_dict(g) for g in gav_ledger],
        "t2_entries": [_t2_dict(e) for e in t2_entries],
        "t2_income_entries": [_t2_income_dict(e) for e in t2_income_entries],
        "custom_chains": [_chain_dict(c) for c in custom_chains],
    }

    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"kryptoskatt-export-{account.account_id[:8]}.json"
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("")
def delete_account(
    body: DeleteAccountRequest,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Permanently delete the account and all associated data (GDPR right to erasure)."""
    if body.confirm != "DELETE MY ACCOUNT":
        raise HTTPException(
            status_code=400,
            detail="Confirmation string does not match. Send {\"confirm\": \"DELETE MY ACCOUNT\"}.",
        )

    from kryptoskatt.models.custom_chain_config import CustomChainConfig
    from kryptoskatt.models.disposal import Disposal
    from kryptoskatt.models.gav_ledger import GavLedger
    from kryptoskatt.models.t2_manual_entry import T2ManualEntry
    from kryptoskatt.models.t2_manual_income_entry import T2ManualIncomeEntry
    from kryptoskatt.models.transaction import ImportBatch, Transaction
    from kryptoskatt.models.transfer_link import TransferLink
    from kryptoskatt.models.user_session import UserSession
    from kryptoskatt.models.wallet import Wallet

    uid = account.id

    # Delete in dependency order (most-derived first to avoid FK violations).
    # TransferLinks reference Transactions directly.
    tx_ids = [row[0] for row in db.query(Transaction.id).filter(Transaction.user_id == uid).all()]
    if tx_ids:
        db.query(TransferLink).filter(
            (TransferLink.tx_out_id.in_(tx_ids)) | (TransferLink.tx_in_id.in_(tx_ids))
        ).delete(synchronize_session=False)

    db.query(Transaction).filter(Transaction.user_id == uid).delete(synchronize_session=False)
    db.query(ImportBatch).filter(ImportBatch.user_id == uid).delete(synchronize_session=False)
    db.query(Wallet).filter(Wallet.user_id == uid).delete(synchronize_session=False)
    db.query(Disposal).filter(Disposal.user_id == uid).delete(synchronize_session=False)
    db.query(GavLedger).filter(GavLedger.user_id == uid).delete(synchronize_session=False)
    db.query(T2ManualEntry).filter(T2ManualEntry.user_id == uid).delete(synchronize_session=False)
    db.query(T2ManualIncomeEntry).filter(T2ManualIncomeEntry.user_id == uid).delete(synchronize_session=False)
    db.query(CustomChainConfig).filter(CustomChainConfig.account_id == uid).delete(synchronize_session=False)
    db.query(UserSession).filter(UserSession.account_id == uid).delete(synchronize_session=False)
    db.delete(account)
    db.commit()

    return {"ok": True}
