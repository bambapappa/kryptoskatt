"""Wallet endpoints for API v1."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from kryptoskatt.db import get_db
from kryptoskatt.models.account import Account
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.wallet import WalletService
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


_get_db = get_db


def _wallet_to_dict(w) -> dict:
    return {
        "id": w.id,
        "address": w.address,
        "chain": w.chain,
        "label": w.label,
        "is_mine": w.is_mine,
        "category": w.category,
        "created_at": w.created_at,
    }


@router.get("")
def list_wallets(
    db: Session = Depends(_get_db), account: Account = Depends(get_current_account)
):
    service = WalletService(db, account.id)
    wallets = service.list_wallets()
    return {"wallets": [_wallet_to_dict(w) for w in wallets]}


@router.post("", status_code=201)
def add_wallet(
    body: WalletCreate,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    service = WalletService(db, account.id)
    try:
        wallet = service.add_wallet(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _wallet_to_dict(wallet)


@router.get("/unsupported")
def list_unsupported_wallets(
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """List wallets that cannot be fetched (no adapter or custom chain not yet configured)."""
    from kryptoskatt.chains import get_registry_for_user
    registry = get_registry_for_user(db, account.id)
    service = WalletService(db, account.id)
    wallets = service.list_wallets(mine_only=True)
    unsupported = [
        _wallet_to_dict(w) for w in wallets
        if registry.get_adapter(w.chain) is None
    ]
    return {"wallets": unsupported}


@router.delete("/{wallet_id}")
def remove_wallet(
    wallet_id: int,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    from kryptoskatt.models.wallet import Wallet
    w = db.query(Wallet).filter(Wallet.id == wallet_id, Wallet.user_id == account.id).first()
    if not w:
        raise HTTPException(status_code=404, detail="Wallet not found")
    db.delete(w)
    db.commit()
    return {"ok": True}
