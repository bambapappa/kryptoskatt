"""In-memory sliding window rate limiter for API endpoints."""

from collections import defaultdict, deque
from datetime import UTC, datetime
from threading import Lock


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._windows: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()
        self._last_prune = 0.0

    def is_allowed(self, key: str) -> bool:
        """Return True if request is allowed, False if rate limited."""
        now = datetime.now(UTC).timestamp()
        with self._lock:
            window = self._windows[key]
            # Remove timestamps outside the current window
            cutoff = now - self.window_seconds
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= self.max_requests:
                return False
            window.append(now)
            self._prune(cutoff)
            return True

    def _prune(self, cutoff: float) -> None:
        """Drop keys (client IPs) with no request inside the window.

        Keeps memory bounded and means an IP is held no longer than needed.
        Called with the lock held.
        """
        if cutoff - self._last_prune < 1:
            return
        self._last_prune = cutoff
        stale = [k for k, w in self._windows.items() if not w or w[-1] < cutoff]
        for k in stale:
            del self._windows[k]

    def reset(self, key: str) -> None:
        """Clear all recorded requests for a given key (useful in tests)."""
        with self._lock:
            self._windows[key].clear()


# Singletons used by API routers
api_limiter = RateLimiter(max_requests=60, window_seconds=60)
fetch_limiter = RateLimiter(max_requests=5, window_seconds=60)
# Login/account creation: keyed on client IP to slow brute-forcing of account IDs
login_limiter = RateLimiter(max_requests=10, window_seconds=60)
# Site-wide cap on *failed* logins. Per-IP limits alone do not stop a guesser
# spread over many IPs; this bounds total guesses for the whole instance.
failed_login_global_limiter = RateLimiter(max_requests=200, window_seconds=60)
GLOBAL_KEY = "global"


def login_blocked_globally() -> bool:
    """True when the site-wide failed-login budget for this window is spent."""
    limiter = failed_login_global_limiter
    now = datetime.now(UTC).timestamp()
    with limiter._lock:
        window = limiter._windows[GLOBAL_KEY]
        cutoff = now - limiter.window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        return len(window) >= limiter.max_requests


def record_failed_login() -> None:
    failed_login_global_limiter.is_allowed(GLOBAL_KEY)
