"""Additional tests for account ID generation: uniqueness under load and wordlist validation."""

import re

from kryptoskatt.services.account_id import _load_wordlist, generate_account_id_unique


class MockSession:
    """Minimal session stub that always reports no existing account_id (always unique)."""

    def query(self, model):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None  # simulate: candidate not found in DB → always unique


def test_generate_1000_unique():
    """Generate 1 000 account IDs against a session that never has collisions.

    All 1 000 results must be distinct.
    """
    session = MockSession()
    ids = [generate_account_id_unique(session) for _ in range(1000)]

    assert len(ids) == 1000
    assert len(set(ids)) == 1000, "Duplicate account IDs found in 1 000 generated IDs"


def test_wordlist_loaded():
    """The wordlist file is readable and contains at least 1 024 entries."""
    words = _load_wordlist()

    assert isinstance(words, list), "Wordlist should be a list"
    assert len(words) >= 1024, (
        f"Expected at least 1 024 words in wordlist, got {len(words)}"
    )
    # Every word should be a non-empty string
    for word in words:
        assert isinstance(word, str) and word, "Every wordlist entry must be a non-empty string"


def test_wordlist_words_are_lowercase_alpha():
    """Wordlist entries should be lowercase and alphabetic (sanity check)."""
    words = _load_wordlist()

    for word in words:
        assert word.islower(), f"Word {word!r} is not lowercase"
        assert word.isalpha(), f"Word {word!r} is not purely alphabetic"


def test_generate_format_matches_pattern():
    """Each generated ID must match word-word-word-NNNN."""
    session = MockSession()
    for _ in range(20):
        account_id = generate_account_id_unique(session)
        assert re.match(r"^[a-z]+-[a-z]+-[a-z]+-\d{4}$", account_id), (
            f"ID {account_id!r} does not match expected format"
        )


def test_collision_retried_until_unique():
    """When the DB reports a collision, the generator retries until it finds a unique ID.

    The mock session returns a non-None object for the first call (simulating a
    collision), then None for subsequent calls so the generator can succeed.
    """
    call_count = 0

    class CollidingOnce:
        def query(self, model):
            return self

        def filter(self, *args, **kwargs):
            return self

        def first(self):
            nonlocal call_count
            call_count += 1
            # Simulate a collision for the first 3 attempts, then succeed
            if call_count <= 3:
                return object()  # truthy → collision
            return None  # unique from the 4th attempt onward

    session = CollidingOnce()
    account_id = generate_account_id_unique(session)

    assert re.match(r"^[a-z]+-[a-z]+-[a-z]+-\d{4}$", account_id)
    assert call_count >= 4, f"Expected at least 4 DB queries, got {call_count}"
