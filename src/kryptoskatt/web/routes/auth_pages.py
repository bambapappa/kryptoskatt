"""Auth web routes (login, account creation, logout)."""

import logging

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.services.auth import AuthService
from kryptoskatt.web.auth import (
    clear_session_cookie,
    get_optional_account,
    set_session_cookie,
)
from kryptoskatt.web.deps import get_db
from kryptoskatt.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/auth/login", response_class=HTMLResponse)
def auth_login_get(request: Request, error: str = ""):
    """Show login form."""
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": error},
    )


@router.post("/auth/login")
async def auth_login_post(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Process login with account_id."""
    from kryptoskatt.services.rate_limiter import (
        login_blocked_globally,
        login_limiter,
        record_failed_login,
    )

    client_ip = request.client.host if request.client else "unknown"
    if login_blocked_globally() or not login_limiter.is_allowed(f"login:{client_ip}"):
        return RedirectResponse("/auth/login?error=För+många+försök+—+vänta+en+minut", status_code=303)

    form = await request.form()
    account_id = (form.get("account_id") or "").strip()

    if not account_id:
        return RedirectResponse("/auth/login?error=Konto-ID+saknas", status_code=303)

    auth_service = AuthService(db)
    account = auth_service.get_account_by_id(account_id)
    if not account:
        record_failed_login()
        return RedirectResponse("/auth/login?error=Ogiltigt+konto-ID", status_code=303)

    _, raw_token = auth_service.create_session(account)
    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, raw_token, request)
    return resp


@router.post("/auth/create")
def auth_create(request: Request, accept_terms: str = Form(""), db: Session = Depends(get_db)):
    """Create a new anonymous account and show its ID once.

    The ID is rendered directly in this response (never put in a URL), so it
    does not end up in server/proxy logs or browser history.
    """
    from kryptoskatt.services.rate_limiter import login_limiter

    if accept_terms != "yes":
        return RedirectResponse("/auth/login?error=Du+måste+godkänna+villkoren", status_code=303)

    client_ip = request.client.host if request.client else "unknown"
    if not login_limiter.is_allowed(f"create:{client_ip}"):
        return RedirectResponse("/auth/login?error=För+många+försök+—+vänta+en+minut", status_code=303)

    account, token = AuthService(db).create_account()
    resp = templates.TemplateResponse(
        request,
        "auth/create.html",
        {"account_id": account.account_id, "qr_svg": _account_qr_svg(account.account_id)},
    )
    resp.headers["Cache-Control"] = "no-store"
    set_session_cookie(resp, token, request)
    return resp


def _account_qr_svg(account_id: str) -> str:
    """Render the account_id as an inline SVG QR code (pure Python, no raster deps)."""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(account_id, image_factory=qrcode.image.svg.SvgPathImage, box_size=12)
    return img.to_string(encoding="unicode")


@router.post("/auth/logout")
def auth_logout(
    response: Response,
    db: Session = Depends(get_db),
    account: Account | None = Depends(get_optional_account),
):
    """Log out current user."""
    if account:
        from kryptoskatt.models.user_session import UserSession
        db.query(UserSession).filter(UserSession.account_id == account.id).delete()
        db.commit()
    resp = RedirectResponse("/auth/login", status_code=303)
    clear_session_cookie(resp)
    return resp
