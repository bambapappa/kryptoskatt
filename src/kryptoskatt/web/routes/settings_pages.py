"""Settings pages: account info, sessions, custom chains, account deletion."""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.web.auth import (
    clear_session_cookie,
)
from kryptoskatt.web.deps import get_current_account_for_html, get_db
from kryptoskatt.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Account settings: show account info, sessions, and custom chains."""
    from kryptoskatt.models.custom_chain_config import CustomChainConfig
    from kryptoskatt.models.user_session import UserSession
    from kryptoskatt.services.auth import COOKIE_NAME, hash_token

    raw_cookie = request.cookies.get(COOKIE_NAME)
    current_token = hash_token(raw_cookie) if raw_cookie else None
    sessions = (
        db.query(UserSession)
        .filter(UserSession.account_id == account.id)
        .order_by(UserSession.last_used_at.desc())
        .all()
    )
    custom_chains = (
        db.query(CustomChainConfig)
        .filter(CustomChainConfig.account_id == account.id)
        .order_by(CustomChainConfig.chain_name)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "account": account,
            "sessions": sessions,
            "current_token": current_token,
            "custom_chains": custom_chains,
        },
    )


@router.post("/settings/custom-chains/add")
def settings_custom_chain_add(
    chain_name: str = Form(...),
    adapter_type: str = Form(...),
    explorer_url: str = Form(...),
    api_key: str = Form(""),
    native_coin: str = Form(...),
    chain_id: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Add a custom chain configuration."""
    from kryptoskatt.models.custom_chain_config import CustomChainConfig

    name = chain_name.strip().upper()
    if not name:
        return RedirectResponse("/settings?error=Kedjenamn+saknas", status_code=303)

    existing = db.query(CustomChainConfig).filter(
        CustomChainConfig.account_id == account.id,
        CustomChainConfig.chain_name == name,
    ).first()
    if existing:
        return RedirectResponse(f"/settings?error=Kedjan+{name}+finns+redan", status_code=303)

    chain_id_int: int | None = None
    if chain_id.strip():
        try:
            chain_id_int = int(chain_id.strip())
        except ValueError:
            return RedirectResponse("/settings?error=Ogiltigt+chain+ID", status_code=303)

    from kryptoskatt.services.secrets import encrypt_secret

    db.add(CustomChainConfig(
        account_id=account.id,
        chain_name=name,
        adapter_type=adapter_type,
        explorer_url=explorer_url.strip().rstrip("/"),
        api_key=encrypt_secret(api_key.strip()) or None,
        native_coin=native_coin.strip().upper(),
        chain_id=chain_id_int,
    ))
    db.commit()
    return RedirectResponse(f"/settings?ok=Kedjan+{name}+lades+till", status_code=303)


@router.post("/settings/custom-chains/delete")
def settings_custom_chain_delete(
    chain_id_pk: int = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Delete a custom chain configuration."""
    from kryptoskatt.models.custom_chain_config import CustomChainConfig

    entry = db.query(CustomChainConfig).filter(
        CustomChainConfig.id == chain_id_pk,
        CustomChainConfig.account_id == account.id,
    ).first()
    if entry:
        db.delete(entry)
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/sessions/revoke-all")
def settings_revoke_all_sessions(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Revoke all sessions except the current one."""
    from kryptoskatt.models.user_session import UserSession
    from kryptoskatt.services.auth import COOKIE_NAME, hash_token

    current_token = request.cookies.get(COOKIE_NAME)
    query = db.query(UserSession).filter(UserSession.account_id == account.id)
    if current_token:
        query = query.filter(UserSession.session_token != hash_token(current_token))
    query.delete(synchronize_session=False)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/delete-account")
def settings_delete_account(
    request: Request,
    confirm: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Delete the account and all data, then redirect to login."""
    if confirm != "DELETE MY ACCOUNT":
        return RedirectResponse("/settings?error=bad_confirm", status_code=303)

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
    db.query(Account).filter(Account.id == uid).delete(synchronize_session=False)
    db.commit()

    response = RedirectResponse("/auth/login", status_code=303)
    clear_session_cookie(response)
    return response

