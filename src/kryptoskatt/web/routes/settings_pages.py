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
    from kryptoskatt.services.api_keys import account_key_status
    from kryptoskatt.services.share_links import list_share_links

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "account": account,
            "sessions": sessions,
            "current_token": current_token,
            "custom_chains": custom_chains,
            "api_key_status": account_key_status(db, account.id),
            "share_links": list_share_links(db, account.id),
        },
    )


@router.post("/settings/share-links/create")
def settings_share_link_create(
    request: Request,
    days: str = Form("30"),
    label: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Create a read-only share link and show its URL once."""
    from kryptoskatt.services.share_links import DEFAULT_DAYS, create_share_link

    try:
        day_count = int(days)
    except ValueError:
        day_count = DEFAULT_DAYS

    raw_token = create_share_link(db, account.id, days=day_count, label=label)
    share_url = str(request.base_url).rstrip("/") + "/share/" + raw_token
    return templates.TemplateResponse(
        request,
        "share_created.html",
        {"account": account, "share_url": share_url},
    )


@router.post("/settings/share-links/revoke")
def settings_share_link_revoke(
    link_id: int = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Revoke a share link owned by the account."""
    from kryptoskatt.services.share_links import revoke_share_link

    revoke_share_link(db, account.id, link_id)
    return RedirectResponse("/settings?ok=Delningslänk+återkallad#share-links", status_code=303)


@router.post("/settings/api-keys/save")
def settings_api_key_save(
    provider: str = Form(...),
    api_key: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Store (or clear, when empty) the account's own key for a provider."""
    from kryptoskatt.services.api_keys import set_account_api_key
    from kryptoskatt.services.secrets import SecretKeyMissingError

    try:
        set_account_api_key(db, account.id, provider.strip(), api_key)
    except SecretKeyMissingError:
        return RedirectResponse(
            "/settings?error=Servern+saknar+SECRET_KEY+—+nycklar+kan+inte+sparas+säkert",
            status_code=303,
        )
    except ValueError:
        return RedirectResponse("/settings?error=Okänd+leverantör", status_code=303)
    action = "sparad" if api_key.strip() else "borttagen"
    return RedirectResponse(f"/settings?ok=API-nyckel+{action}#api-keys", status_code=303)


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

    from kryptoskatt.utils.url_safety import UnsafeURLError, validate_public_https_url

    if adapter_type not in ("blockscout", "etherscan"):
        return RedirectResponse("/settings?error=Ogiltig+adaptertyp", status_code=303)
    try:
        safe_url = validate_public_https_url(explorer_url)
    except UnsafeURLError:
        return RedirectResponse(
            "/settings?error=Explorer-URL+måste+vara+en+publik+https-adress", status_code=303
        )

    chain_id_int: int | None = None
    if chain_id.strip():
        try:
            chain_id_int = int(chain_id.strip())
        except ValueError:
            return RedirectResponse("/settings?error=Ogiltigt+chain+ID", status_code=303)

    from kryptoskatt.services.secrets import SecretKeyMissingError, encrypt_secret

    try:
        encrypted_key = encrypt_secret(api_key.strip()) or None
    except SecretKeyMissingError:
        return RedirectResponse(
            "/settings?error=Servern+saknar+SECRET_KEY+—+nycklar+kan+inte+sparas+säkert",
            status_code=303,
        )
    db.add(CustomChainConfig(
        account_id=account.id,
        chain_name=name,
        adapter_type=adapter_type,
        explorer_url=safe_url,
        api_key=encrypted_key,
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

    from kryptoskatt.services.account_deletion import delete_account_data

    delete_account_data(db, account.id)

    response = RedirectResponse("/auth/login", status_code=303)
    clear_session_cookie(response)
    return response

