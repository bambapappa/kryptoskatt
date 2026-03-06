"""Price service for fetching historical crypto prices from CoinGecko."""

import logging
import time
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.orm import Session

from kryptoskatt.config import settings
from kryptoskatt.enums import PriceSource
from kryptoskatt.models.price_cache import PriceCache

logger = logging.getLogger(__name__)

# CoinGecko API base URL
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

# Rate limit delay (seconds) for free tier
DEFAULT_RATE_LIMIT_DELAY = 0.2

# Coin ID mapping from symbol to CoinGecko coin_id
COIN_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "BNB": "binancecoin",
    "VET": "vechain",
    "KDA": "kadena",
    "TRX": "tron",
    "POL": "matic-network",
    "MATIC": "matic-network",
    "HNT": "helium",
    "PEAQ": "peaq-2",
    "ALEO": "aleo",
}


def resolve_coin_id(symbol: str) -> str | None:
    """Resolve a coin symbol to CoinGecko coin_id.

    Args:
        symbol: Coin symbol (e.g., "BTC", "ETH", "btc")

    Returns:
        CoinGecko coin_id or None if unknown.
    """
    return COIN_ID_MAP.get(symbol.upper())


class PriceService:
    """Service for fetching and caching cryptocurrency prices."""

    def __init__(self, session: Session, rate_limit_delay: float = DEFAULT_RATE_LIMIT_DELAY):
        """Initialize with a database session.

        Args:
            session: SQLAlchemy session for database operations.
            rate_limit_delay: Delay between API calls in seconds (default 0.2s).
        """
        self.session = session
        self.rate_limit_delay = rate_limit_delay

    def get_price_sek(self, coin_id: str, price_date: date) -> Decimal | None:
        """Get price for a coin on a specific date.

        Args:
            coin_id: CoinGecko coin_id (e.g., "ethereum", "bitcoin").
            price_date: Date to fetch price for.

        Returns:
            Price in SEK as Decimal, or None if unavailable.
        """
        # Check cache first
        cached = self._get_from_cache(coin_id, price_date)
        if cached is not None:
            return cached

        # Fetch from API
        price = self._fetch_from_api(coin_id, price_date)
        if price is None:
            return None

        # Save to cache
        self._save_to_cache(coin_id, price_date, price)

        return price

    def get_prices_batch(
        self, requests: list[tuple[str, date]]
    ) -> dict[tuple[str, date], Decimal | None]:
        """Get prices for multiple coin/date combinations.

        Optimizes by checking cache first, then making API calls only for cache misses.

        Args:
            requests: List of (coin_id, date) tuples.

        Returns:
            Dictionary mapping (coin_id, date) to price in SEK (or None).
        """
        result: dict[tuple[str, date], Decimal | None] = {}
        cache_misses: list[tuple[str, date]] = []

        # Check cache for all requests
        for coin_id, price_date in requests:
            cached = self._get_from_cache(coin_id, price_date)
            if cached is not None:
                result[(coin_id, price_date)] = cached
            else:
                cache_misses.append((coin_id, price_date))
                result[(coin_id, price_date)] = None  # Placeholder

        # Fetch missing prices from API
        if cache_misses:
            prices = self._fetch_multiple_from_api(cache_misses)

            for (coin_id, price_date), price in prices.items():
                if price is not None:
                    # Save to cache
                    self._save_to_cache(coin_id, price_date, price)
                result[(coin_id, price_date)] = price

        return result

    def _get_from_cache(self, coin_id: str, price_date: date) -> Decimal | None:
        """Check if price exists in cache."""
        cached = (
            self.session.query(PriceCache)
            .filter(PriceCache.coin_id == coin_id, PriceCache.date == price_date)
            .first()
        )
        if cached:
            logger.debug(f"Cache hit for {coin_id} on {price_date}")
            return cached.price_sek
        return None

    def _save_to_cache(self, coin_id: str, price_date: date, price: Decimal) -> None:
        """Save price to cache database."""
        # Check if already exists (race condition handling)
        existing = (
            self.session.query(PriceCache)
            .filter(PriceCache.coin_id == coin_id, PriceCache.date == price_date)
            .first()
        )

        if existing:
            existing.price_sek = price
            existing.source = PriceSource.COINGECKO.value
        else:
            cache_entry = PriceCache(
                coin_id=coin_id,
                date=price_date,
                price_sek=price,
                source=PriceSource.COINGECKO.value,
            )
            self.session.add(cache_entry)

        self.session.commit()
        logger.debug(f"Saved to cache: {coin_id} on {price_date} = {price} SEK")

    def _fetch_from_api(self, coin_id: str, price_date: date) -> Decimal | None:
        """Fetch price from CoinGecko API.

        Args:
            coin_id: CoinGecko coin_id.
            price_date: Date to fetch price for.

        Returns:
            Price in SEK as Decimal, or None if unavailable.
        """
        # CoinGecko uses DD-MM-YYYY format
        date_str = price_date.strftime("%d-%m-%Y")
        url = f"{COINGECKO_BASE_URL}/coins/{coin_id}/history"
        params = {
            "date": date_str,
            "localization": "false",
        }

        headers = {}
        if settings.coingecko_api_key:
            headers["x-cg-demo-api-key"] = settings.coingecko_api_key

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=params, headers=headers)

                if response.status_code == 404:
                    logger.warning(f"Coin not found: {coin_id}")
                    return None

                if response.status_code == 429:
                    logger.warning(f"Rate limit hit for {coin_id}")
                    return None

                if response.status_code != 200:
                    logger.error(f"API error {response.status_code} for {coin_id}: {response.text}")
                    return None

                data = response.json()
                return self._extract_price(data)

        except httpx.TimeoutException:
            logger.error(f"Timeout fetching price for {coin_id}")
            return None
        except Exception as e:
            logger.error(f"Error fetching price for {coin_id}: {e}")
            return None

    def _fetch_multiple_from_api(
        self, requests: list[tuple[str, date]]
    ) -> dict[tuple[str, date], Decimal | None]:
        """Fetch multiple prices from API with rate limiting.

        Args:
            requests: List of (coin_id, date) tuples to fetch.

        Returns:
            Dictionary mapping (coin_id, date) to price or None.
        """
        results: dict[tuple[str, date], Decimal | None] = {}

        for i, (coin_id, price_date) in enumerate(requests):
            # Rate limit: sleep between API calls (except for first)
            if i > 0:
                time.sleep(self.rate_limit_delay)

            price = self._fetch_from_api(coin_id, price_date)
            results[(coin_id, price_date)] = price

        return results

    def _extract_price(self, data: dict[str, Any]) -> Decimal | None:
        """Extract price SEK from CoinGecko API response.

        Args:
            data: JSON response from CoinGecko.

        Returns:
            Price as Decimal, or None if unavailable.
        """
        try:
            market_data = data.get("market_data", {})
            current_price = market_data.get("current_price", {})

            # Try SEK first
            sek_price = current_price.get("sek")
            if sek_price is not None:
                # Convert float to Decimal - use string to preserve precision
                return Decimal(str(sek_price))

            # Fallback: try USD (would need conversion - not implemented)
            usd_price = current_price.get("usd")
            if usd_price is not None:
                logger.debug("SEK not available, USD not converted (requires Riksbanken rate)")
                return None

            logger.warning("No price data in response")
            return None

        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"Error extracting price from response: {e}")
            return None
