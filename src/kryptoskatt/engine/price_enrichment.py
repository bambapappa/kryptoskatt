"""Price enrichment: fill in missing price_sek on transactions via CoinGecko and swap pairs."""

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from kryptoskatt.enums import EventType
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.services.price import PriceService, resolve_coin_id

logger = logging.getLogger(__name__)

# Event types that need a price to compute cost basis / proceeds
PRICE_NEEDED_EVENTS = {
    EventType.BUY,
    EventType.SELL,
    EventType.SWAP_IN,
    EventType.SWAP_OUT,
    EventType.TRANSFER_IN,
    EventType.TRANSFER_OUT,
    EventType.REWARD,
}


@dataclass
class EnrichmentReport:
    total: int
    enriched: int
    skipped_unknown_coin: int
    skipped_api_miss: int
    swap_implied: int


class PriceEnrichmentEngine:
    """Fetches missing price_sek for transactions that need one."""

    def __init__(self, session: Session, user_id: int):
        self.session = session
        self.user_id = user_id
        self.price_service = PriceService(session)

    def enrich(self) -> EnrichmentReport:
        """Fill in price_sek for all transactions where it is currently NULL.

        Pass 1: CoinGecko historical price lookup.
        Pass 2: Derive prices from swap pairs (same tx_hash, different coins).
        """
        txs = (
            self.session.query(Transaction)
            .filter(
                Transaction.user_id == self.user_id,
                Transaction.price_sek.is_(None),
                Transaction.is_duplicate.is_(False),
                Transaction.event_type.in_([e.value for e in PRICE_NEEDED_EVENTS]),
            )
            .all()
        )

        total = len(txs)
        enriched = 0
        skipped_unknown = 0
        skipped_miss = 0
        unknown_coins: set[str] = set()

        for tx in txs:
            price_date = tx.timestamp_utc.date()

            # Manual prices always win — check first regardless of CoinGecko availability
            manual = self.price_service.get_manual_price_sek(tx.base_coin, price_date)
            if manual is not None:
                tx.price_sek = manual
                enriched += 1
                continue

            coin_id = resolve_coin_id(tx.base_coin)
            price: Decimal | None = None

            if coin_id:
                price = self.price_service.get_price_sek(coin_id, price_date)

            if price is None:
                # Free exchange OHLC fallbacks (USD/USDT close → SEK via Riksbank)
                price = self.price_service.fetch_binance_price(tx.base_coin, price_date)

            if price is None:
                price = self.price_service.fetch_kraken_price(tx.base_coin, price_date)

            if price is None:
                # Fallback: try CoinAPI (requires an API key) for exotic coins
                price = self.price_service.fetch_coinapi_price(tx.base_coin, price_date)

            if price is None:
                if not coin_id:
                    if tx.base_coin not in unknown_coins:
                        logger.warning(
                            "No price found for %s on %s (not in CoinGecko map, CoinAPI returned nothing)",
                            tx.base_coin, price_date,
                        )
                        unknown_coins.add(tx.base_coin)
                    skipped_unknown += 1
                else:
                    logger.debug("No price found for %s on %s", tx.base_coin, price_date)
                skipped_miss += 1
                continue

            tx.price_sek = price
            enriched += 1

        self.session.commit()

        # Pass 2: infer prices from swap partners sharing the same tx_hash
        swap_implied = self._enrich_from_swap_pairs()

        logger.info(
            "Price enrichment: %d/%d priced, %d from swap pairs, %d no-price (unknown coins: %d)",
            enriched, total, swap_implied, skipped_miss, skipped_unknown,
        )
        return EnrichmentReport(
            total=total,
            enriched=enriched,
            skipped_unknown_coin=skipped_unknown,
            skipped_api_miss=skipped_miss,
            swap_implied=swap_implied,
        )

    def _enrich_from_swap_pairs(self) -> int:
        """Derive prices for unknown coins from swap partners on the same tx_hash.

        When a transaction has two legs sharing a tx_hash (e.g. GEOD→SOL swap):
        - one leg has a known price (SOL)
        - the other doesn't (GEOD)
        The implied price = (known_amount × known_price_sek) / unknown_amount.

        This handles DEX swaps where exotic tokens can only be priced via the
        SOL/ETH/etc. they were exchanged for.
        """
        # Collect tx_hashes that have at least one transaction still missing price
        unpriced = (
            self.session.query(Transaction)
            .filter(
                Transaction.user_id == self.user_id,
                Transaction.price_sek.is_(None),
                Transaction.is_duplicate.is_(False),
                Transaction.tx_hash.isnot(None),
                Transaction.event_type.in_([e.value for e in PRICE_NEEDED_EVENTS]),
            )
            .all()
        )

        if not unpriced:
            return 0

        tx_hashes = {tx.tx_hash for tx in unpriced}
        enriched = 0

        for tx_hash in tx_hashes:
            all_txs = (
                self.session.query(Transaction)
                .filter(
                    Transaction.user_id == self.user_id,
                    Transaction.tx_hash == tx_hash,
                    Transaction.is_duplicate.is_(False),
                )
                .all()
            )

            priced = [
                tx for tx in all_txs
                if tx.price_sek is not None and tx.base_amount
            ]
            still_unpriced = [
                tx for tx in all_txs
                if tx.price_sek is None and tx.base_amount
            ]

            for known_tx in priced:
                known_amount = abs(Decimal(str(known_tx.base_amount)))
                known_price = Decimal(str(known_tx.price_sek))
                known_value_sek = known_amount * known_price

                for unknown_tx in still_unpriced:
                    # Only pair different coins (same coin on same hash is unusual)
                    if unknown_tx.base_coin == known_tx.base_coin:
                        continue
                    unknown_amount = abs(Decimal(str(unknown_tx.base_amount)))
                    # Skip dust amounts — dividing by near-zero produces nonsensical prices
                    if unknown_amount < Decimal("0.000001"):
                        continue
                    implied = known_value_sek / unknown_amount
                    # NUMERIC(28,18) max is ~9.999e9; cap to avoid DB overflow
                    if implied > Decimal("9999999999"):
                        logger.debug(
                            "Skipping swap-implied price for %s: %.2f SEK (unreasonably large)",
                            unknown_tx.base_coin, implied,
                        )
                        continue
                    unknown_tx.price_sek = implied
                    enriched += 1
                    logger.info(
                        "Swap-implied price for %s on %s: %.6f SEK (from %s swap)",
                        unknown_tx.base_coin,
                        unknown_tx.timestamp_utc.date(),
                        unknown_tx.price_sek,
                        known_tx.base_coin,
                    )

        if enriched:
            self.session.commit()

        return enriched
