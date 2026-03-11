"""Import historical price data from local CSV files into price_cache.

Supports two formats:
  - CoinGecko CSV: snapped_at,price,market_cap,total_volume (UTC timestamps, USD prices)
  - CoinMarketCap CSV: timestamp;price;volume (semicolon separated, USD prices)

Prices are converted from USD to SEK using Riksbanken historical rates.
Imported data is stored in price_cache and used as primary source; CoinGecko API
is called only when no cached price is found.
"""

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from kryptoskatt.enums import PriceSource
from kryptoskatt.models.price_cache import PriceCache

logger = logging.getLogger(__name__)

# Riksbanken SWEA API — returns JSON with historical cross rates
_RIKSBANK_BASE = "https://api.riksbank.se/swea/v1"
_USDSEKMID = "USDSEKMID"  # USD/SEK daily mid rate (SEK per 1 USD)

# Map CSV filename stem (lowercased, strip "-usd-max" etc.) → (cache_key, source)
# cache_key for known CoinGecko coins: CoinGecko coin_id (used by PriceService)
# cache_key for unknown/manual coins: SYMBOL (uppercase, matched by get_manual_price_sek)
_FILENAME_MAP: dict[str, tuple[str, str]] = {
    "sol":   ("solana",    PriceSource.COINGECKO.value),
    "eth":   ("ethereum",  PriceSource.COINGECKO.value),
    "btc":   ("bitcoin",   PriceSource.COINGECKO.value),
    "xrp":   ("ripple",    PriceSource.COINGECKO.value),
    "trx":   ("tron",      PriceSource.COINGECKO.value),
    "vet":   ("vechain",   PriceSource.COINGECKO.value),
    "weth":  ("WETH",      PriceSource.MANUAL.value),
    "geod":  ("GEOD",      PriceSource.MANUAL.value),
    "ono":   ("ONO",       PriceSource.MANUAL.value),
    "bmb":   ("BMB",       PriceSource.MANUAL.value),
    "dimo":  ("DIMO",      PriceSource.MANUAL.value),
    "esx":   ("ESX",       PriceSource.MANUAL.value),
    "bono":  ("BONO",      PriceSource.MANUAL.value),
    "hnt":   ("helium",    PriceSource.COINGECKO.value),
    "mobile":("helium-mobile", PriceSource.COINGECKO.value),
    "iot":   ("helium-iot",    PriceSource.COINGECKO.value),
}


@dataclass
class ImportResult:
    files_processed: int = 0
    rows_inserted: int = 0
    rows_skipped: int = 0
    rows_failed: int = 0
    usd_sek_dates_fetched: int = 0
    errors: list[str] = field(default_factory=list)


class PriceHistoryImporter:
    """Loads CSV price files into price_cache with USD→SEK conversion."""

    def __init__(self, session: Session):
        self.session = session

    def import_directory(self, directory: Path) -> ImportResult:
        """Import all recognised CSV files from *directory*.

        Returns an ImportResult summarising what happened.
        """
        result = ImportResult()

        csv_files = list(directory.glob("*.csv"))
        if not csv_files:
            result.errors.append(f"No CSV files found in {directory}")
            return result

        # Step 1: parse all files → {(cache_key, source): {date: usd_price}}
        coin_data: dict[tuple[str, str], dict[date, Decimal]] = {}
        all_dates: set[date] = set()

        for csv_path in csv_files:
            mapping = self._resolve_mapping(csv_path)
            if mapping is None:
                logger.debug("No mapping for %s — skipping", csv_path.name)
                continue

            cache_key, source = mapping
            try:
                rows = self._parse_csv(csv_path)
                if not rows:
                    continue
                result.files_processed += 1
                coin_data[(cache_key, source)] = rows
                all_dates.update(rows.keys())
            except Exception as e:
                msg = f"{csv_path.name}: {e}"
                result.errors.append(msg)
                logger.warning("Failed to parse %s: %s", csv_path.name, e)

        if not all_dates:
            result.errors.append("No valid price rows found in any CSV")
            return result

        # Step 2: fetch USD/SEK rates for all needed dates
        min_date = min(all_dates)
        max_date = max(all_dates)
        usd_sek = self._fetch_usd_sek_rates(min_date, max_date)
        result.usd_sek_dates_fetched = len(usd_sek)

        if not usd_sek:
            result.errors.append(
                "Could not fetch USD/SEK rates from Riksbanken — no prices imported"
            )
            return result

        # Step 3: convert and upsert into price_cache
        # Pre-load existing keys to skip duplicates efficiently
        existing = {
            (r.coin_id, r.date)
            for r in self.session.query(PriceCache.coin_id, PriceCache.date).all()
        }

        for (cache_key, source), date_prices in coin_data.items():
            for price_date, usd_price in date_prices.items():
                rate = usd_sek.get(price_date)
                if rate is None:
                    # Try nearest previous day (weekends / holidays)
                    for delta in range(1, 5):
                        rate = usd_sek.get(price_date - timedelta(days=delta))
                        if rate:
                            break

                if rate is None:
                    result.rows_failed += 1
                    continue

                sek_price = usd_price * rate

                if (cache_key, price_date) in existing:
                    result.rows_skipped += 1
                    continue

                self.session.add(
                    PriceCache(
                        coin_id=cache_key,
                        date=price_date,
                        price_sek=sek_price,
                        source=source,
                    )
                )
                existing.add((cache_key, price_date))
                result.rows_inserted += 1

        self.session.commit()
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_mapping(self, csv_path: Path) -> tuple[str, str] | None:
        """Map a CSV filename to (cache_key, source) or None if unknown."""
        stem = csv_path.stem.lower()
        # Strip common suffixes from CoinGecko exports
        for suffix in ("-usd-max", "-usd-1y", "-usd", "_1y_graph_coinmarketcap"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        return _FILENAME_MAP.get(stem)

    def _parse_csv(self, csv_path: Path) -> dict[date, Decimal]:
        """Parse a CSV file and return {date: usd_price}.

        Handles both CoinGecko (comma) and CoinMarketCap (semicolon) formats.
        Price column is always the second column (index 1).
        """
        text = csv_path.read_text(encoding="utf-8-sig").strip()
        if not text:
            return {}

        # Detect delimiter by checking first line
        first_line = text.splitlines()[0]
        delimiter = ";" if ";" in first_line else ","

        rows: dict[date, Decimal] = {}
        reader = csv.reader(StringIO(text), delimiter=delimiter)
        header = None

        for row in reader:
            if header is None:
                header = row
                continue
            if len(row) < 2:
                continue
            try:
                date_str = row[0].strip().strip('"')
                # Accept: "2025-01-15 00:00:00 UTC", "2025-01-15 01:00:00", "2025-01-15"
                date_part = date_str.split(" ")[0]
                parsed_date = date.fromisoformat(date_part)

                price_str = row[1].strip().strip('"')
                usd_price = Decimal(price_str)
                if usd_price <= 0:
                    continue

                rows[parsed_date] = usd_price
            except (ValueError, InvalidOperation):
                continue

        return rows

    def _fetch_usd_sek_rates(self, from_date: date, to_date: date) -> dict[date, Decimal]:
        """Fetch USD/SEK daily mid rates from Riksbanken SWEA API.

        Returns {date: sek_per_usd} for dates where data is available.
        """
        url = f"{_RIKSBANK_BASE}/Observations/{_USDSEKMID}/{from_date}/{to_date}"
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, headers={"Accept": "application/json"})
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error("Riksbanken API error: %s", e)
            return {}

        rates: dict[date, Decimal] = {}
        # Riksbanken SWEA response: list of {"date": "YYYY-MM-DD", "value": 10.23}
        if isinstance(data, list):
            for entry in data:
                try:
                    d = date.fromisoformat(entry["date"])
                    v = Decimal(str(entry["value"]))
                    if v > 0:
                        rates[d] = v
                except (KeyError, ValueError, InvalidOperation):
                    continue
        else:
            logger.warning("Unexpected Riksbanken response format: %s", type(data))

        logger.info(
            "Riksbanken USD/SEK: fetched %d rates from %s to %s",
            len(rates), from_date, to_date,
        )
        return rates
