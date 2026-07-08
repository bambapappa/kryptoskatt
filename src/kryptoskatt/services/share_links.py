"""Read-only share links for accountants.

Tokens are 256-bit URL-safe secrets; only their SHA-256 hash is stored. A link
is valid until it expires or is revoked and grants read-only access to the
account's tax summary — never any mutation.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from kryptoskatt.models.share_link import ShareLink
from kryptoskatt.services.auth import hash_token

# Guard rails for the expiry chosen in the UI.
MIN_DAYS = 1
MAX_DAYS = 365
DEFAULT_DAYS = 30


def create_share_link(
    session: Session, account_id: int, days: int = DEFAULT_DAYS, label: str = ""
) -> str:
    """Create a share link and return the raw token (shown to the user once)."""
    days = max(MIN_DAYS, min(MAX_DAYS, days))
    raw_token = secrets.token_urlsafe(32)
    link = ShareLink(
        account_id=account_id,
        token_hash=hash_token(raw_token),
        label=(label.strip() or None),
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=days),
        revoked=False,
    )
    session.add(link)
    session.commit()
    return raw_token


def resolve_share_link(session: Session, raw_token: str) -> ShareLink | None:
    """Return the active ShareLink for a raw token, or None if invalid/expired/revoked."""
    if not raw_token:
        return None
    link = (
        session.query(ShareLink)
        .filter(ShareLink.token_hash == hash_token(raw_token))
        .first()
    )
    if link is None or link.revoked:
        return None
    # Compare timezone-aware; stores may return naive datetimes (SQLite).
    expires = link.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires <= datetime.now(UTC):
        return None
    return link


def list_share_links(session: Session, account_id: int) -> list[ShareLink]:
    """All non-revoked links for an account, newest first."""
    return (
        session.query(ShareLink)
        .filter(ShareLink.account_id == account_id, ShareLink.revoked.is_(False))
        .order_by(ShareLink.created_at.desc())
        .all()
    )


def revoke_share_link(session: Session, account_id: int, link_id: int) -> bool:
    """Revoke a link owned by the account. Returns True if a link was revoked."""
    link = (
        session.query(ShareLink)
        .filter(ShareLink.id == link_id, ShareLink.account_id == account_id)
        .first()
    )
    if link is None or link.revoked:
        return False
    link.revoked = True
    session.commit()
    return True
