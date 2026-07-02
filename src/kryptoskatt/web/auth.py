"""FastAPI auth dependencies and cookie helpers."""

from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from kryptoskatt.config import settings
from kryptoskatt.db import get_db
from kryptoskatt.models.account import Account
from kryptoskatt.services.auth import COOKIE_NAME, AuthService

# Alias of the shared dependency: overriding either name in
# app.dependency_overrides targets the same function object.
_get_db_session = get_db


def get_current_account(
    kryptoskatt_session: str | None = Cookie(default=None),
    db: Session = Depends(_get_db_session),
) -> Account:
    """Dependency: require a valid session cookie, return the Account."""
    if not kryptoskatt_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    account = AuthService(db).authenticate(kryptoskatt_session)
    if not account:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    return account


def get_optional_account(
    kryptoskatt_session: str | None = Cookie(default=None),
    db: Session = Depends(_get_db_session),
) -> Account | None:
    """Dependency: return Account if authenticated, None otherwise."""
    if not kryptoskatt_session:
        return None
    return AuthService(db).authenticate(kryptoskatt_session)


def set_session_cookie(response: Response, token: str, request: Request | None = None) -> None:
    """Set the session cookie on a response.

    secure flag: uses settings.cookie_secure unless the actual request
    came over HTTP, in which case Secure=True would prevent the browser
    from ever sending the cookie back.
    """
    if request is not None:
        # Auto-detect: honour X-Forwarded-Proto from a reverse proxy too
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        secure = proto == "https"
    else:
        secure = settings.cookie_secure
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=30 * 24 * 3600,
    )


def clear_session_cookie(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME)
