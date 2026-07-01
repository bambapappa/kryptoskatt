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
            return True

    def reset(self, key: str) -> None:
        """Clear all recorded requests for a given key (useful in tests)."""
        with self._lock:
            self._windows[key].clear()


# Singletons used by API routers
api_limiter = RateLimiter(max_requests=60, window_seconds=60)
fetch_limiter = RateLimiter(max_requests=5, window_seconds=60)
# Login/account creation: keyed on client IP to slow brute-forcing of account IDs
login_limiter = RateLimiter(max_requests=10, window_seconds=60)
