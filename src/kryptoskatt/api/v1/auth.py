"""Auth endpoints for API v1."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
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
def login(body: LoginRequest, response: Response, db: Session = Depends(_get_db)):
    """Log in with an existing account_id."""
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


@router.get("/me")
def me(account=Depends(get_current_account)):
    """Return masked account info."""
    aid = account.account_id
    parts = aid.rsplit("-", 1)
    masked = parts[0] + "-****" if len(parts) == 2 else "****"
    return {"account_id_masked": masked, "created_at": account.created_at}
