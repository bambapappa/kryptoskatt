"""Unit tests for the in-memory sliding window rate limiter."""

from unittest.mock import patch

from kryptoskatt.services.rate_limiter import RateLimiter


def test_allows_under_limit():
    """All requests under the limit are allowed."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    for _ in range(5):
        assert limiter.is_allowed("user-1") is True


def test_blocks_over_limit():
    """The 6th request exceeds the limit and is denied."""
    limiter = RateLimiter(max_requests=5, window_seconds=60)
    for _ in range(5):
        limiter.is_allowed("user-2")
    assert limiter.is_allowed("user-2") is False


def test_window_resets():
    """After the window expires, requests are allowed again."""
    limiter = RateLimiter(max_requests=3, window_seconds=60)

    # Fill up the window with timestamps from 120 seconds ago
    old_time = 1_000_000.0  # arbitrary fixed past timestamp
    for _ in range(3):
        limiter._windows["user-3"].append(old_time)

    # All three slots are "old" — after sliding the window they should be evicted.
    # Mock datetime.now to return a time 120 seconds after old_time.
    from datetime import UTC, datetime

    future = datetime.fromtimestamp(old_time + 120, tz=UTC)
    with patch("kryptoskatt.services.rate_limiter.datetime") as mock_dt:
        mock_dt.now.return_value = future
        result = limiter.is_allowed("user-3")

    assert result is True


def test_different_keys_are_independent():
    """Rate limits are tracked per key independently."""
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    # Fill up key A
    limiter.is_allowed("key-a")
    limiter.is_allowed("key-a")
    assert limiter.is_allowed("key-a") is False

    # key-b should still have a full window
    assert limiter.is_allowed("key-b") is True


def test_reset_clears_window():
    """reset() allows a previously exhausted key to make requests again."""
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    limiter.is_allowed("user-r")
    assert limiter.is_allowed("user-r") is False

    limiter.reset("user-r")
    assert limiter.is_allowed("user-r") is True
