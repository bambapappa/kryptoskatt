"""Advanced edge-case tests for the in-memory sliding window rate limiter."""

import threading
from datetime import UTC, datetime
from unittest.mock import patch

from kryptoskatt.services.rate_limiter import RateLimiter


def test_different_keys_independent():
    """Rate-limit windows for distinct keys do not interfere with each other."""
    limiter = RateLimiter(max_requests=2, window_seconds=60)

    # Exhaust key "a"
    assert limiter.is_allowed("a") is True
    assert limiter.is_allowed("a") is True
    assert limiter.is_allowed("a") is False  # blocked

    # Key "b" still has a completely fresh window
    assert limiter.is_allowed("b") is True
    assert limiter.is_allowed("b") is True
    assert limiter.is_allowed("b") is False  # its own limit

    # Key "c" has never been touched — should be allowed
    assert limiter.is_allowed("c") is True


def test_concurrent_requests_respect_limit():
    """Under concurrent load, exactly max_requests threads are admitted.

    10 threads all call is_allowed("x") simultaneously.  With max_requests=5,
    exactly 5 should receive True and 5 should receive False.
    """
    max_req = 5
    total_threads = 10
    limiter = RateLimiter(max_requests=max_req, window_seconds=60)
    results: list[bool] = []
    barrier = threading.Barrier(total_threads)

    def worker():
        barrier.wait()  # all threads start at the same moment
        results.append(limiter.is_allowed("x"))

    threads = [threading.Thread(target=worker) for _ in range(total_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    allowed = sum(1 for r in results if r)
    denied = sum(1 for r in results if not r)

    assert allowed == max_req, f"Expected {max_req} allowed, got {allowed}"
    assert denied == total_threads - max_req, f"Expected {total_threads - max_req} denied, got {denied}"


def test_window_is_sliding_not_fixed():
    """The sliding window discards old timestamps as time advances.

    Setup:
    - max_requests=3, window=3 s
    - Inject 3 timestamps 0s, 1s, 2s ago (all inside the 3-second window)
    - At t=now:   next call is blocked  (window still full)
    - At t=now+1: first timestamp falls outside the 3-second window, so one
                  slot frees up and the next call is allowed
    """
    limiter = RateLimiter(max_requests=3, window_seconds=3)

    base_ts = 1_000_000.0  # arbitrary fixed epoch second

    # Plant three timestamps exactly 2 s, 1 s, and 0 s before base_ts
    limiter._windows["key"].append(base_ts - 2.0)
    limiter._windows["key"].append(base_ts - 1.0)
    limiter._windows["key"].append(base_ts - 0.0)

    # --- check 1: right at base_ts, window is full → blocked ---
    with patch("kryptoskatt.services.rate_limiter.datetime") as mock_dt:
        mock_dt.now.return_value = datetime.fromtimestamp(base_ts, tz=UTC)
        result_at_base = limiter.is_allowed("key")

    assert result_at_base is False, "Expected False when window is exactly full"

    # --- check 2: 1.001 s later, the oldest timestamp (base_ts-2) is now 3.001 s
    #              old, strictly less than the cutoff (now - 3) → evicted, 1 slot
    #              frees up and the next call is allowed ---
    limiter.reset("key")
    limiter._windows["key"].append(base_ts - 2.0)
    limiter._windows["key"].append(base_ts - 1.0)
    limiter._windows["key"].append(base_ts - 0.0)

    # Move 1.001 s forward so base_ts-2 is strictly outside [later-3, later]
    later = base_ts + 1.001
    with patch("kryptoskatt.services.rate_limiter.datetime") as mock_dt:
        mock_dt.now.return_value = datetime.fromtimestamp(later, tz=UTC)
        result_after_slide = limiter.is_allowed("key")

    assert result_after_slide is True, (
        "Expected True after sliding window evicts the oldest request"
    )


def test_is_allowed_returns_bool():
    """is_allowed must always return a plain bool, not a truthy object."""
    limiter = RateLimiter(max_requests=1, window_seconds=60)

    first = limiter.is_allowed("typecheck")
    second = limiter.is_allowed("typecheck")

    assert type(first) is bool  # noqa: E721
    assert type(second) is bool  # noqa: E721
    assert first is True
    assert second is False


def test_empty_key_treated_as_valid_key():
    """The empty string is a valid dict key and has its own independent window."""
    limiter = RateLimiter(max_requests=1, window_seconds=60)

    assert limiter.is_allowed("") is True
    assert limiter.is_allowed("") is False
    # Other keys are unaffected
    assert limiter.is_allowed("other") is True
