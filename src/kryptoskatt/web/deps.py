"""Shared FastAPI dependencies for web (HTML) routes."""

from fastapi import Depends, HTTPException

from kryptoskatt.db import get_db  # noqa: F401  (re-exported: single shared DB dependency)
from kryptoskatt.models.account import Account
from kryptoskatt.web.auth import get_optional_account


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
