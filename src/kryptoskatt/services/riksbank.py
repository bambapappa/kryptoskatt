"""Fetch USD/SEK exchange rates from Riksbank open API."""

import logging
from datetime import date, timedelta
from decimal import Decimal

import httpx

from kryptoskatt.utils.http import get_with_retry

logger = logging.getLogger(__name__)

_RIKSBANK_BASE = "https://api.riksbank.se/swea/v1"
_SERIES_ID = "SEKUSDPMI"  # SEK per 1 USD, daily mid rate


def get_usd_sek_rate(target_date: date) -> Decimal | None:
    """Fetch USD/SEK rate for a given date.

    Queries a 7-day window ending on target_date and returns the most
    recent observation on or before that date. This handles weekends and
    bank holidays where no rate is published.

    Returns None if the API is unreachable or returns no data.
    """
    end = target_date.strftime("%Y-%m-%d")
    start = (target_date - timedelta(days=7)).strftime("%Y-%m-%d")
    url = f"{_RIKSBANK_BASE}/Observations/{_SERIES_ID}/{start}/{end}"

    try:
        resp = get_with_retry(url, headers={"Accept": "application/json"}, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Riksbank API unavailable for %s: %s", target_date, exc)
        return None

    # Response is a plain list: [{"date": "YYYY-MM-DD", "value": 10.23}, ...]
    observations: list[dict] = data if isinstance(data, list) else []
    if not observations:
        logger.debug("Riksbank returned no observations for window ending %s", end)
        return None

    # Walk backwards to find the most recent rate on or before target_date
    for obs in reversed(observations):
        obs_date = obs.get("date", "")
        if obs_date <= end:
            value = obs.get("value")
            if value is not None:
                try:
                    return Decimal(str(value))
                except Exception:
                    continue

    return None
