"""Price service for fetching historical crypto prices from CoinGecko."""

import logging
import time
from datetime import UTC, date, datetime
from datetime import time as dtime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from kryptoskatt.config import settings
from kryptoskatt.enums import PriceSource
from kryptoskatt.models.price_cache import PriceCache
from kryptoskatt.services.riksbank import get_usd_sek_rate
from kryptoskatt.utils.http import get_with_retry

logger = logging.getLogger(__name__)

# CoinGecko API base URL
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"

# CoinAPI base URL
COINAPI_BASE_URL = "https://rest.coinapi.io/v1"

# Binance public market-data mirror (no auth, no geo restriction) for daily OHLC
BINANCE_BASE_URL = "https://data-api.binance.vision/api/v3"

# Kraken public OHLC endpoint (recent candles only, ~720 days back)
KRAKEN_BASE_URL = "https://api.kraken.com/0/public"

# Kraken uses non-standard asset codes for a few symbols
_KRAKEN_ASSET_ALIASES = {"BTC": "XBT", "DOGE": "XDG"}

# Stablecoins we treat as 1:1 with USD when converting exchange OHLC to SEK
_USD_STABLES = frozenset({"USDT", "USDC", "USD", "BUSD", "DAI", "TUSD"})

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
    "MOBILE": "helium-mobile",
    "IOT": "helium-iot",
    "PEAQ": "peaq-2",
    "ALEO": "aleo",
    "USDC": "usd-coin",
    "USDT": "tether",
    # USDT0 = LayerZero OFT bridged USDT, pegged 1:1 to USDT
    "USDT0": "tether",
    "JUP": "jupiter-exchange-solana",
    "BONK": "bonk",
    "MSOL": "marinade-staked-sol",
    "STSOL": "lido-staked-sol",
    "GEOD": "geodnet",
    "ONO": "onocoy",
    "MXC": "moonchain",
    "ESX": "estatex",
    "ARB": "arbitrum",
    "VTHO": "vethor-token",
}

# Lookalike Unicode → ASCII substitutions.
# Spam tokens and some cross-chain bridges encode token symbols with Cyrillic
# or other script characters that are visually identical to Latin letters.
# Normalising before lookup means e.g. "UЅdТ0" → "USDT0" → "tether".
_UNICODE_LOOKALIKES = str.maketrans({
    "\u0405": "S",   # Ѕ CYRILLIC CAPITAL LETTER DZE
    "\u0455": "s",   # ѕ CYRILLIC SMALL LETTER DZE
    "\u0422": "T",   # Т CYRILLIC CAPITAL LETTER TE
    "\u0442": "t",   # т CYRILLIC SMALL LETTER TE
    "\u0410": "A",   # А CYRILLIC CAPITAL LETTER A
    "\u0430": "a",   # а CYRILLIC SMALL LETTER A
    "\u0415": "E",   # Е CYRILLIC CAPITAL LETTER IE
    "\u0435": "e",   # е CYRILLIC SMALL LETTER IE
    "\u041E": "O",   # О CYRILLIC CAPITAL LETTER O
    "\u043E": "o",   # о CYRILLIC SMALL LETTER O
    "\u0421": "C",   # С CYRILLIC CAPITAL LETTER ES
    "\u0441": "c",   # с CYRILLIC SMALL LETTER ES
    "\u0412": "B",   # В CYRILLIC CAPITAL LETTER VE
    "\u0432": "b",   # в CYRILLIC SMALL LETTER VE
    "\u0420": "R",   # Р CYRILLIC CAPITAL LETTER ER  (looks like P but maps to R)
    "\u0440": "r",   # р CYRILLIC SMALL LETTER ER
    "\u0406": "I",   # І CYRILLIC CAPITAL LETTER BYELORUSSIAN-UKRAINIAN I
    "\u0456": "i",   # і CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I
    "\u04C0": "I",   # Ӏ CYRILLIC LETTER PALOCHKA
    "\u0399": "I",   # Ι GREEK CAPITAL LETTER IOTA
    "\u03BF": "o",   # ο GREEK SMALL LETTER OMICRON
    "\u039F": "O",   # Ο GREEK CAPITAL LETTER OMICRON
})


def normalize_coin_symbol(symbol: str) -> str:
    """Replace lookalike Unicode characters with their ASCII equivalents.

    Handles Cyrillic/Greek homoglyphs used in spam token names so that
    e.g. "UЅDТ" (Cyrillic Ѕ and Т) normalises to "USDT".
    """
    return symbol.translate(_UNICODE_LOOKALIKES)


def resolve_coin_id(symbol: str) -> str | None:
    """Resolve a coin symbol to CoinGecko coin_id.

    Tries the symbol as-is first, then with Unicode lookalikes normalised.
    This handles cross-chain tokens whose on-chain symbol metadata uses
    Cyrillic/Greek characters visually identical to Latin letters.

    Args:
        symbol: Coin symbol (e.g., "BTC", "ETH", "UЅDТ")

    Returns:
        CoinGecko coin_id or None if unknown.
    """
    upper = symbol.upper()
    result = COIN_ID_MAP.get(upper)
    if result is not None:
        return result
    # Try with Unicode normalization
    normalized = normalize_coin_symbol(upper)
    if normalized != upper:
        return COIN_ID_MAP.get(normalized)
    return None


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
        # Memoise Riksbank USD/SEK lookups within a single enrichment run so a
        # batch of exchange-priced coins doesn't hammer the Riksbank API.
        self._usd_sek_cache: dict[date, Decimal | None] = {}

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

    def get_manual_price_sek(self, symbol: str, price_date: date) -> Decimal | None:
        """Get a manually entered price for a coin symbol on a specific date.

        Manual prices are stored with source=MANUAL and coin_id=SYMBOL (uppercase).
        They take precedence over CoinGecko for exotic/unlisted coins.

        Args:
            symbol: Coin symbol (e.g., "GEOD", "BONO").
            price_date: Date to look up.

        Returns:
            Price in SEK as Decimal, or None if not found.
        """
        cached = (
            self.session.query(PriceCache)
            .filter(
                PriceCache.coin_id == symbol.upper(),
                PriceCache.date == price_date,
                PriceCache.source == PriceSource.MANUAL.value,
            )
            .first()
        )
        return Decimal(str(cached.price_sek)) if cached else None

    def save_manual_price(self, symbol: str, price_date: date, price: Decimal) -> None:
        """Store a manually provided price, overwriting any existing manual entry.

        Args:
            symbol: Coin symbol (e.g., "GEOD").
            price_date: Date the price applies to.
            price: Price in SEK per unit.
        """
        symbol = symbol.upper()
        existing = (
            self.session.query(PriceCache)
            .filter(
                PriceCache.coin_id == symbol,
                PriceCache.date == price_date,
                PriceCache.source == PriceSource.MANUAL.value,
            )
            .first()
        )
        if existing:
            existing.price_sek = price
        else:
            self.session.add(
                PriceCache(
                    coin_id=symbol,
                    date=price_date,
                    price_sek=price,
                    source=PriceSource.MANUAL.value,
                )
            )
        self.session.commit()
        logger.info("Saved manual price: %s on %s = %s SEK", symbol, price_date, price)

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

    def _save_to_cache(
        self, coin_id: str, price_date: date, price: Decimal, source: str = PriceSource.COINGECKO.value
    ) -> None:
        """Save price to cache database."""
        existing = (
            self.session.query(PriceCache)
            .filter(PriceCache.coin_id == coin_id, PriceCache.date == price_date)
            .first()
        )

        if existing:
            existing.price_sek = price
            existing.source = source
        else:
            self.session.add(PriceCache(
                coin_id=coin_id,
                date=price_date,
                price_sek=price,
                source=source,
            ))

        self.session.commit()
        logger.debug(f"Saved to cache: {coin_id} on {price_date} = {price} SEK ({source})")

    def fetch_coinapi_price(self, symbol: str, price_date: date) -> Decimal | None:
        """Fetch historical price from CoinAPI.io as a fallback.

        Uses the exchange rate endpoint: /exchangerate/{base}/SEK?time=...
        Falls back to /exchangerate/{base}/USD?time=... if SEK is unavailable.

        Args:
            symbol: Coin ticker (e.g. "GEOD", "ONO").
            price_date: Date to fetch price for.

        Returns:
            Price in SEK as Decimal, or None if unavailable.
        """
        if not settings.coinapi_api_key:
            return None

        headers = {"X-CoinAPI-Key": settings.coinapi_api_key}
        # CoinAPI wants a datetime — use noon UTC of the target day
        time_str = f"{price_date.isoformat()}T12:00:00.0000000Z"
        upper = symbol.upper()

        try:
            # Try SEK directly first
            url = f"{COINAPI_BASE_URL}/exchangerate/{upper}/SEK"
            resp = get_with_retry(url, params={"time": time_str}, headers=headers, timeout=30.0)

            if resp.status_code == 200:
                rate = resp.json().get("rate")
                if rate:
                    price = Decimal(str(rate))
                    self._save_to_cache(upper, price_date, price, PriceSource.COINAPI.value)
                    logger.info("CoinAPI price for %s on %s: %.6f SEK", symbol, price_date, price)
                    return price

            if resp.status_code in (404, 550):
                logger.debug("CoinAPI: %s not available in SEK on %s", symbol, price_date)
            elif resp.status_code == 429:
                logger.warning("CoinAPI rate limit hit for %s (all retries exhausted)", symbol)
            else:
                logger.debug("CoinAPI %d status for %s", resp.status_code, symbol)

        except Exception as e:
            logger.error("CoinAPI fetch error for %s: %s", symbol, e)

        return None

    def _usd_sek(self, price_date: date) -> Decimal | None:
        """Riksbank USD/SEK rate for a date, memoised for the service's lifetime."""
        if price_date not in self._usd_sek_cache:
            self._usd_sek_cache[price_date] = get_usd_sek_rate(price_date)
        return self._usd_sek_cache[price_date]

    def _cached_symbol_price(self, symbol: str, price_date: date) -> Decimal | None:
        """Return any cached price stored under the bare symbol (uppercase)."""
        cached = (
            self.session.query(PriceCache)
            .filter(PriceCache.coin_id == symbol.upper(), PriceCache.date == price_date)
            .first()
        )
        return Decimal(str(cached.price_sek)) if cached else None

    def fetch_binance_price(self, symbol: str, price_date: date) -> Decimal | None:
        """Fetch a daily close price from Binance public OHLC as a free fallback.

        Binance quotes against USDT (treated 1:1 with USD); the close is
        converted to SEK with the Riksbank USD/SEK rate for the same day.
        Historical klines reach back to each pair's listing date, which makes
        this a good gap-filler for coins missing from the CoinGecko map.

        Args:
            symbol: Coin ticker (e.g. "BTC", "ARB").
            price_date: Date to fetch the close price for.

        Returns:
            Price in SEK as Decimal, or None if unavailable.
        """
        upper = symbol.upper()
        if upper in _USD_STABLES:
            return None  # no meaningful crypto pair; handled elsewhere if needed

        cached = self._cached_symbol_price(upper, price_date)
        if cached is not None:
            return cached

        start_ms = int(datetime.combine(price_date, dtime.min, tzinfo=UTC).timestamp() * 1000)
        end_ms = start_ms + 86_400_000 - 1
        params = {
            "symbol": f"{upper}USDT",
            "interval": "1d",
            "startTime": str(start_ms),
            "endTime": str(end_ms),
            "limit": "1",
        }
        try:
            resp = get_with_retry(
                f"{BINANCE_BASE_URL}/klines", params=params, timeout=15.0
            )
            if resp.status_code != 200:
                logger.debug("Binance %d for %sUSDT on %s", resp.status_code, upper, price_date)
                return None
            candles = resp.json()
            if not candles:
                return None
            # kline layout: [openTime, open, high, low, close, volume, ...]
            close_usd = Decimal(str(candles[0][4]))
        except Exception as e:
            logger.debug("Binance fetch error for %s: %s", upper, e)
            return None

        rate = self._usd_sek(price_date)
        if rate is None:
            logger.debug("No USD/SEK rate for %s — cannot convert Binance price", price_date)
            return None
        price = close_usd * rate
        self._save_to_cache(upper, price_date, price, PriceSource.BINANCE.value)
        logger.info("Binance price for %s on %s: %.6f SEK", upper, price_date, price)
        return price

    def fetch_kraken_price(self, symbol: str, price_date: date) -> Decimal | None:
        """Fetch a daily close price from Kraken public OHLC as a free fallback.

        Kraken's OHLC endpoint only returns the most recent ~720 daily
        candles, so this works for recent tax years but not historical ones.
        Quoted in USD and converted to SEK via the Riksbank rate.

        Args:
            symbol: Coin ticker (e.g. "BTC", "ETH").
            price_date: Date to fetch the close price for.

        Returns:
            Price in SEK as Decimal, or None if unavailable.
        """
        upper = symbol.upper()
        if upper in _USD_STABLES:
            return None

        cached = self._cached_symbol_price(upper, price_date)
        if cached is not None:
            return cached

        asset = _KRAKEN_ASSET_ALIASES.get(upper, upper)
        params = {"pair": f"{asset}USD", "interval": "1440"}
        try:
            resp = get_with_retry(f"{KRAKEN_BASE_URL}/OHLC", params=params, timeout=15.0)
            if resp.status_code != 200:
                logger.debug("Kraken %d for %sUSD on %s", resp.status_code, asset, price_date)
                return None
            payload = resp.json()
            if payload.get("error"):
                logger.debug("Kraken error for %sUSD: %s", asset, payload["error"])
                return None
            result = payload.get("result", {})
            candles: list = next(
                (v for k, v in result.items() if k != "last" and isinstance(v, list)), []
            )
            close_usd: Decimal | None = None
            for candle in candles:
                # candle: [time, open, high, low, close, vwap, volume, count]
                if datetime.fromtimestamp(candle[0], tz=UTC).date() == price_date:
                    close_usd = Decimal(str(candle[4]))
                    break
            if close_usd is None:
                return None
        except Exception as e:
            logger.debug("Kraken fetch error for %s: %s", asset, e)
            return None

        rate = self._usd_sek(price_date)
        if rate is None:
            return None
        price = close_usd * rate
        self._save_to_cache(upper, price_date, price, PriceSource.KRAKEN.value)
        logger.info("Kraken price for %s on %s: %.6f SEK", upper, price_date, price)
        return price

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
            response = get_with_retry(url, params=params, headers=headers, timeout=30.0)

            if response.status_code == 404:
                logger.warning("Coin not found: %s", coin_id)
                return None

            if response.status_code == 429:
                logger.warning("Rate limit hit for %s (all retries exhausted)", coin_id)
                return None

            if response.status_code != 200:
                logger.error("API error %d for %s: %s", response.status_code, coin_id, response.text)
                return None

            data = response.json()
            return self._extract_price(data)

        except Exception as e:
            logger.error("Error fetching price for %s: %s", coin_id, e)
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
