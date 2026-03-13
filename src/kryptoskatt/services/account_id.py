"""Generate unique human-readable account IDs in the format word-word-word-NNNN."""

import secrets
from pathlib import Path

from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account

_WORDLIST_PATH = Path(__file__).parent.parent / "data" / "wordlist.txt"
_WORDLIST: list[str] | None = None


def _load_wordlist() -> list[str]:
    global _WORDLIST
    if _WORDLIST is None:
        words = _WORDLIST_PATH.read_text(encoding="utf-8").splitlines()
        _WORDLIST = [w.strip() for w in words if w.strip()]
    return _WORDLIST


def generate_account_id_unique(session: Session) -> str:
    """Generate a unique account_id of the form 'word-word-word-NNNN'.

    Tries up to 10 times, checking uniqueness against the DB each attempt.
    """
    wordlist = _load_wordlist()
    rng = secrets.SystemRandom()

    for _ in range(10):
        words = rng.choices(wordlist, k=3)
        number = secrets.randbelow(10000)
        candidate = f"{words[0]}-{words[1]}-{words[2]}-{number:04d}"
        existing = session.query(Account).filter(Account.account_id == candidate).first()
        if not existing:
            return candidate

    raise RuntimeError("Could not generate a unique account_id after 10 attempts")
