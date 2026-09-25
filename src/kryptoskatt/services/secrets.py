"""Encryption at rest for small user secrets (e.g. custom chain API keys).

Values are encrypted with Fernet (AES-128-CBC + HMAC) using a key derived
from ``SECRET_KEY`` in the environment. Encrypted values carry the prefix
``enc:v1:`` so legacy plaintext rows keep working: values without the
prefix are returned as-is by :func:`decrypt_secret`.

If ``SECRET_KEY`` is not configured, storing a new secret is refused
(:class:`SecretKeyMissingError`) — user secrets are never written in plaintext.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from kryptoskatt.config import settings

logger = logging.getLogger(__name__)

_PREFIX = "enc:v1:"


class SecretKeyMissingError(RuntimeError):
    """Raised when a secret must be stored but SECRET_KEY is not configured."""


def _fernet() -> Fernet | None:
    if not settings.secret_key:
        return None
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None) -> str | None:
    """Encrypt a secret for storage. Returns None/empty input unchanged."""
    if not value:
        return value
    f = _fernet()
    if f is None:
        raise SecretKeyMissingError(
            "SECRET_KEY is not set; refusing to store a secret in plaintext. "
            "Set SECRET_KEY in .env (e.g. `openssl rand -hex 32`)."
        )
    return _PREFIX + f.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str:
    """Decrypt a stored secret. Legacy plaintext values (no prefix) pass through."""
    if not value:
        return ""
    if not value.startswith(_PREFIX):
        return value
    f = _fernet()
    if f is None:
        logger.error("Encrypted secret found but SECRET_KEY is not set — cannot decrypt")
        return ""
    try:
        return f.decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt secret — SECRET_KEY changed since it was stored?")
        return ""
