"""Shared FastAPI dependencies for web (HTML) routes."""

from collections.abc import Generator

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from kryptoskatt.db import get_session
from kryptoskatt.models.account import Account
from kryptoskatt.web.auth import get_optional_account


def get_db() -> Generator[Session, None, None]:
    """Database session dependency."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_current_account_for_html(
    account: Account | None = Depends(get_optional_account),
) -> Account:
    """Dependency for HTML routes: redirect to /auth/login instead of raising 401."""
    if account is None:
        # Return a redirect response by raising it as an exception
        raise HTTPException(
            status_code=302,
            detail="Redirect",
            headers={"Location": "/auth/login"},
        )
    return account
