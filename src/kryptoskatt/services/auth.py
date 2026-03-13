"""Authentication service for anonymous account management."""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.models.user_session import UserSession
from kryptoskatt.services.account_id import generate_account_id_unique

SESSION_TTL_DAYS = 30
COOKIE_NAME = "kryptoskatt_session"

LEGACY_ACCOUNT_ID = "legacy-single-user-0000"


class AuthService:
    """Service for managing accounts and sessions."""

    def __init__(self, session: Session):
        self.session = session

    def create_account(self) -> tuple[Account, str]:
        """Create a new anonymous account and initial session.

        Returns:
            (Account, session_token) — the session_token is shown only once.
        """
        account_id = generate_account_id_unique(self.session)
        now = datetime.now(UTC)
        account = Account(account_id=account_id, created_at=now, last_active_at=now, is_active=True)
        self.session.add(account)
        self.session.flush()

        user_session = self._new_session(account.id)
        self.session.add(user_session)
        self.session.commit()
        self.session.refresh(account)
        return account, user_session.session_token

    def create_session(self, account: Account) -> UserSession:
        """Create a new session for an existing account."""
        user_session = self._new_session(account.id)
        self.session.add(user_session)
        self.session.commit()
        self.session.refresh(user_session)
        return user_session

    def authenticate(self, token: str) -> Account | None:
        """Validate session token and return the associated Account, or None if invalid/expired."""
        now = datetime.now(UTC)
        user_session = (
            self.session.query(UserSession)
            .filter(
                UserSession.session_token == token,
                UserSession.expires_at > now,
            )
            .first()
        )
        if not user_session:
            return None

        # Extend session and update activity timestamps
        user_session.last_used_at = now
        user_session.expires_at = now + timedelta(days=SESSION_TTL_DAYS)

        account = self.session.query(Account).filter(Account.id == user_session.account_id).first()
        if not account or not account.is_active:
            return None

        account.last_active_at = now
        self.session.commit()
        return account

    def logout(self, token: str) -> None:
        """Delete a session token."""
        user_session = (
            self.session.query(UserSession).filter(UserSession.session_token == token).first()
        )
        if user_session:
            self.session.delete(user_session)
            self.session.commit()

    def get_account_by_id(self, account_id: str) -> Account | None:
        """Look up an account by its human-readable account_id."""
        return (
            self.session.query(Account)
            .filter(Account.account_id == account_id, Account.is_active == True)  # noqa: E712
            .first()
        )

    def _new_session(self, account_db_id: int) -> UserSession:
        now = datetime.now(UTC)
        return UserSession(
            session_token=secrets.token_hex(32),
            account_id=account_db_id,
            created_at=now,
            last_used_at=now,
            expires_at=now + timedelta(days=SESSION_TTL_DAYS),
        )


def get_legacy_user_id(session: Session) -> int:
    """Return the DB id of the legacy single-user account."""
    account = session.query(Account).filter(Account.account_id == LEGACY_ACCOUNT_ID).first()
    if not account:
        raise RuntimeError("Legacy account not found — run migration 008_multi_tenant first")
    return account.id
