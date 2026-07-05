"""Per-account API keys for on-chain data providers.

Lets each account supply its own Etherscan/Helius/etc. keys instead of sharing
the instance-wide keys from the environment. Values are encrypted at rest with
the same Fernet scheme as custom chain keys (see ``services.secrets``).
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kryptoskatt.models.base import Base


class AccountApiKey(Base):
    __tablename__ = "account_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    # Provider slug, e.g. "etherscan", "helius", "solscan", "tronscan".
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    # Encrypted key (enc:v1:… when SECRET_KEY is set, else plaintext).
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("account_id", "provider", name="uq_account_api_key_provider"),
    )
