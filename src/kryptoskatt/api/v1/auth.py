"""Auth endpoints for API v1."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from kryptoskatt.api.schemas import AccountCreateResponse, LoginRequest
from kryptoskatt.services.auth import AuthService
from kryptoskatt.web.auth import clear_session_cookie, get_current_account, set_session_cookie

router = APIRouter()


def _get_db():
    from kryptoskatt.db import get_session
    s = get_session()
    try:
        yield s
    finally:
        s.close()


@router.post("/account", response_model=AccountCreateResponse, status_code=201)
def create_account(response: Response, db: Session = Depends(_get_db)):
    """Create a new anonymous account. Returns the account_id (shown only once)."""
    account, token = AuthService(db).create_account()
    set_session_cookie(response, token)
    return AccountCreateResponse(account_id=account.account_id)


@router.post("/session", status_code=200)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(_get_db)):
    """Log in with an existing account_id."""
    from kryptoskatt.services.rate_limiter import login_limiter
    from kryptoskatt.web.auth import client_ip

    if not login_limiter.is_allowed(client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts — try again later",
        )

    auth_service = AuthService(db)
    account = auth_service.get_account_by_id(body.account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid account_id")
    user_session = auth_service.create_session(account)
    set_session_cookie(response, user_session.session_token)
    return {"ok": True}


@router.delete("/session", status_code=200)
def logout(
    response: Response,
    db: Session = Depends(_get_db),
    account=Depends(get_current_account),
):
    """Log out (delete all sessions for the current account)."""
    from kryptoskatt.models.user_session import UserSession
    db.query(UserSession).filter(UserSession.account_id == account.id).delete()
    db.commit()
    clear_session_cookie(response)
    return {"ok": True}


def _mask_account_id(account_id: str) -> str:
    """Mask middle parts of a hyphen-separated account_id.

    Shows first and last word, hides everything in between.
    E.g. 'maple-river-fox-1234' → 'maple-*****-***-1234'
    """
    parts = account_id.split("-")
    if len(parts) < 4:
        return account_id[:4] + "***"
    return f"{parts[0]}-{'*' * len(parts[1])}-{'*' * len(parts[2])}-{parts[3]}"


@router.get("/me")
def me(account=Depends(get_current_account)):
    """Return masked account info for the authenticated account."""
    return {"account_id_masked": _mask_account_id(account.account_id), "created_at": account.created_at}


@router.get("/sessions")
def list_sessions(
    request: Request,
    db: Session = Depends(_get_db),
    account=Depends(get_current_account),
):
    """List active sessions for the authenticated account."""
    from kryptoskatt.models.user_session import UserSession
    from kryptoskatt.services.auth import COOKIE_NAME

    current_token = request.cookies.get(COOKIE_NAME)
    sessions = (
        db.query(UserSession)
        .filter(UserSession.account_id == account.id)
        .order_by(UserSession.last_used_at.desc())
        .all()
    )
    return {
        "sessions": [
            {
                "id": s.id,
                "created_at": s.created_at,
                "last_used_at": s.last_used_at,
                "expires_at": s.expires_at,
                "is_current": s.session_token == current_token,
            }
            for s in sessions
        ]
    }


@router.delete("/sessions/{session_id}", status_code=200)
def delete_session(
    request: Request,
    session_id: int,
    db: Session = Depends(_get_db),
    account=Depends(get_current_account),
):
    """Delete a specific session. Cannot delete the current session."""
    from kryptoskatt.models.user_session import UserSession
    from kryptoskatt.services.auth import COOKIE_NAME

    current_token = request.cookies.get(COOKIE_NAME)
    session = (
        db.query(UserSession)
        .filter(UserSession.id == session_id, UserSession.account_id == account.id)
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.session_token == current_token:
        raise HTTPException(status_code=400, detail="Cannot delete current session")
    db.delete(session)
    db.commit()
    return {"ok": True}


@router.delete("/sessions", status_code=200)
def revoke_all_sessions(
    request: Request,
    db: Session = Depends(_get_db),
    account=Depends(get_current_account),
):
    """Revoke all sessions except the current one."""
    from kryptoskatt.models.user_session import UserSession
    from kryptoskatt.services.auth import COOKIE_NAME

    current_token = request.cookies.get(COOKIE_NAME)
    query = db.query(UserSession).filter(UserSession.account_id == account.id)
    if current_token:
        query = query.filter(UserSession.session_token != current_token)
    revoked = query.count()
    query.delete(synchronize_session=False)
    db.commit()
    return {"revoked": revoked}
