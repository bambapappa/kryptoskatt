"""Per-account API keys for on-chain data providers.

Each account may store its own provider keys (encrypted); when absent the
instance-wide key from the environment (``settings``) is used. This lets users
run on their own rate limits without every account sharing the operator's keys.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from kryptoskatt.config import settings
from kryptoskatt.models.account_api_key import AccountApiKey
from kryptoskatt.services.secrets import decrypt_secret, encrypt_secret


@dataclass(frozen=True)
class Provider:
    slug: str
    label: str
    settings_attr: str


# On-chain data providers that accept a per-account key. Order is the display
# order in the settings UI.
PROVIDERS: tuple[Provider, ...] = (
    Provider("etherscan", "Etherscan (ETH/Polygon/BNB/Base/Arbitrum)", "etherscan_api_key"),
    Provider("helius", "Helius (Solana)", "helius_api_key"),
    Provider("solscan", "Solscan (Solana, reserv)", "solscan_api_key"),
    Provider("tronscan", "Tronscan (TRON)", "tronscan_api_key"),
    Provider("vechainstats", "VeChainStats (VeChain)", "vechainstats_api_key"),
    Provider("subscan", "Subscan (PEAQ/Substrate)", "subscan_api_key"),
)

_PROVIDERS_BY_SLUG = {p.slug: p for p in PROVIDERS}

VALID_PROVIDERS = frozenset(p.slug for p in PROVIDERS)


def get_account_api_keys(session: Session, account_id: int) -> dict[str, str]:
    """Return the account's own (decrypted) keys, keyed by provider slug.

    Only providers the account has actually set are included.
    """
    rows = (
        session.query(AccountApiKey)
        .filter(AccountApiKey.account_id == account_id)
        .all()
    )
    result: dict[str, str] = {}
    for row in rows:
        value = decrypt_secret(row.api_key)
        if value:
            result[row.provider] = value
    return result


def resolve_api_keys(session: Session, account_id: int) -> dict[str, str]:
    """Return effective keys per provider: account key if set, else the instance key."""
    account_keys = get_account_api_keys(session, account_id)
    resolved: dict[str, str] = {}
    for provider in PROVIDERS:
        value = account_keys.get(provider.slug) or getattr(settings, provider.settings_attr, "")
        if value:
            resolved[provider.slug] = value
    return resolved


def set_account_api_key(
    session: Session, account_id: int, provider: str, value: str
) -> None:
    """Upsert (or, for an empty value, delete) an account's key for a provider."""
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")

    existing = (
        session.query(AccountApiKey)
        .filter(
            AccountApiKey.account_id == account_id,
            AccountApiKey.provider == provider,
        )
        .first()
    )

    value = value.strip()
    if not value:
        # Empty means "remove my key and fall back to the instance key".
        if existing:
            session.delete(existing)
            session.commit()
        return

    encrypted = encrypt_secret(value)
    if existing:
        existing.api_key = encrypted or value
    else:
        session.add(
            AccountApiKey(account_id=account_id, provider=provider, api_key=encrypted or value)
        )
    session.commit()


def account_key_status(session: Session, account_id: int) -> list[dict]:
    """Per-provider status for the settings UI: label + whether an own key is set."""
    own = set(get_account_api_keys(session, account_id))
    return [
        {
            "slug": p.slug,
            "label": p.label,
            "has_own_key": p.slug in own,
            "instance_fallback": bool(getattr(settings, p.settings_attr, "")),
        }
        for p in PROVIDERS
    ]
