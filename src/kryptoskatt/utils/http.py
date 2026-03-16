"""HTTP utilities with retry and exponential backoff.

All external API calls should go through get_with_retry / post_with_retry.

Retry policy:
  - Retries on:   connection errors, timeouts, 429 (rate limit), 5xx server errors
  - No retry on:  4xx client errors (except 429) — they won't improve with retrying
  - Backoff:      2^attempt seconds, capped at max_backoff
  - 429 specific: honours Retry-After header when present
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

# Status codes that indicate a permanent client error — don't waste retries
_NO_RETRY_4XX = {400, 401, 403, 404, 410, 422, 550}

# Transient network exceptions worth retrying
_TRANSIENT_EXC = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.ReadError,
)


def get_with_retry(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    max_backoff: float = 60.0,
) -> httpx.Response:
    """GET with exponential backoff. Returns the response (may be non-2xx on final attempt)."""
    return _request_with_retry(
        "GET", url,
        params=params, headers=headers,
        timeout=timeout, max_retries=max_retries,
        backoff_base=backoff_base, max_backoff=max_backoff,
    )


def post_with_retry(
    url: str,
    *,
    json: dict | None = None,
    headers: dict | None = None,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    max_backoff: float = 60.0,
) -> httpx.Response:
    """POST with exponential backoff. Returns the response (may be non-2xx on final attempt)."""
    return _request_with_retry(
        "POST", url,
        json=json, headers=headers,
        timeout=timeout, max_retries=max_retries,
        backoff_base=backoff_base, max_backoff=max_backoff,
    )


def _request_with_retry(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
    headers: dict | None = None,
    timeout: float,
    max_retries: int,
    backoff_base: float,
    max_backoff: float,
) -> httpx.Response:
    last_exc: Exception | None = None

    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=timeout) as client:
                if method == "GET":
                    response = client.get(url, params=params, headers=headers)
                else:
                    response = client.post(url, json=json, headers=headers)

            status = response.status_code

            # Permanent client errors — return immediately, caller decides what to do
            if status in _NO_RETRY_4XX:
                return response

            # Rate limit — respect Retry-After if server sends one
            if status == 429:
                delay = _parse_retry_after(response.headers, backoff_base ** (attempt + 1))
                delay = min(delay, max_backoff)
                logger.warning(
                    "Rate limited (429) on %s — waiting %.1fs (attempt %d/%d)",
                    url, delay, attempt + 1, max_retries,
                )
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
                return response  # return 429 on last attempt so caller can log it

            # Server error — retry
            if status >= 500:
                delay = min(backoff_base ** attempt, max_backoff)
                logger.warning(
                    "Server error %d on %s (attempt %d/%d) — retrying in %.1fs",
                    status, url, attempt + 1, max_retries, delay,
                )
                last_exc = httpx.HTTPStatusError(
                    f"Server error {status}", request=response.request, response=response
                )
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
                return response

            return response  # 2xx or 3xx — success

        except _TRANSIENT_EXC as exc:
            last_exc = exc
            delay = min(backoff_base ** attempt, max_backoff)
            logger.warning(
                "%s %s failed (attempt %d/%d): %s — retrying in %.1fs",
                method, url, attempt + 1, max_retries, exc, delay,
            )
            if attempt < max_retries - 1:
                time.sleep(delay)

        except httpx.HTTPError:
            raise  # Other HTTP errors: surface immediately

    if last_exc is not None:
        raise last_exc
    raise httpx.RequestError(f"All {max_retries} attempts failed for {url}")


def _parse_retry_after(headers: httpx.Headers, default: float) -> float:
    """Return Retry-After value in seconds, falling back to default."""
    raw = headers.get("Retry-After", "")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return default
