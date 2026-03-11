"""Deduplication Engine for cryptocurrency transactions."""

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kryptoskatt.models.transaction import Transaction


# Platform priority (lower index = higher priority to keep).
# Helius is preferred over Solscan because it returns wallet-owner addresses
# (fromUserAccount/toUserAccount) rather than SPL token account addresses.
PLATFORM_PRIORITY = [
    "helius",      # Solana: wallet-owner addresses — highest quality
    "solscan",     # Solana: may store SPL token account addresses
    "ON_CHAIN",
    "COINBASE",
    "CRYPTO_COM",
    "MEXC",
    "MANUAL",
]

# Time window for heuristic matching (in minutes)
HEURISTIC_TIME_WINDOW_MINUTES = 5


@dataclass
class DeduplicationReport:
    """Report of deduplication results."""

    total_checked: int
    exact_matches: int
    heuristic_matches: int
    kept_count: int
    removed_count: int


class DeduplicationEngine:
    """Engine for identifying and marking duplicate transactions."""

    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def normalize_tx_hash(tx_hash: str) -> str:
        """Strip MEXC TxID suffix (e.g., ':010').

        Args:
            tx_hash: The transaction hash to normalize.

        Returns:
            The normalized tx_hash without MEXC suffix.
        """
        return re.sub(r":\d+$", "", tx_hash)

    def deduplicate_all(self) -> DeduplicationReport:
        """Run deduplication across all transactions.

        Resets all is_duplicate flags first so that platform-priority changes
        (e.g. helius now preferred over solscan) are re-evaluated correctly.

        Returns:
            DeduplicationReport with counts of operations performed.
        """
        # Reset all duplicate flags so priority changes take effect on re-runs
        self.session.query(Transaction).filter(
            Transaction.is_duplicate.is_(True)
        ).update({"is_duplicate": False}, synchronize_session=False)
        self.session.flush()

        # Get all transactions (now all are non-duplicate after reset)
        stmt = select(Transaction)
        transactions = list(self.session.execute(stmt).scalars().all())

        total_checked = len(transactions)
        exact_matches = 0
        heuristic_matches = 0

        # Step 1: Exact matching on normalized tx_hash
        tx_hash_groups: dict[str, list[Transaction]] = {}
        null_hash_transactions: list[Transaction] = []

        for tx in transactions:
            if tx.tx_hash is not None:
                normalized = self.normalize_tx_hash(tx.tx_hash)
                if normalized not in tx_hash_groups:
                    tx_hash_groups[normalized] = []
                tx_hash_groups[normalized].append(tx)
            else:
                null_hash_transactions.append(tx)

        # Process exact matches
        for normalized_hash, tx_list in tx_hash_groups.items():
            if len(tx_list) > 1:
                # Sort by priority (lower index = higher priority)
                tx_list.sort(
                    key=lambda t: (
                        PLATFORM_PRIORITY.index(t.source_platform)
                        if t.source_platform in PLATFORM_PRIORITY
                        else len(PLATFORM_PRIORITY)
                    )
                )
                # Mark all but first as duplicates
                for tx in tx_list[1:]:
                    tx.is_duplicate = True
                # Count this as one exact match group
                exact_matches += 1

        # Step 2: Heuristic matching for null tx_hash transactions
        # Group by (base_coin, base_amount)
        coin_amount_groups: dict[tuple[str, Any], list[Transaction]] = {}
        for tx in null_hash_transactions:
            key = (tx.base_coin, tx.base_amount)
            if key not in coin_amount_groups:
                coin_amount_groups[key] = []
            coin_amount_groups[key].append(tx)

        # For each coin+amount group, check timestamp proximity
        for (coin, amount), tx_list in coin_amount_groups.items():
            if len(tx_list) > 1:
                # Sort by timestamp
                tx_list.sort(key=lambda t: t.timestamp_utc)

                # Mark duplicates based on time proximity
                processed: set[int] = set()
                for i, tx in enumerate(tx_list):
                    if tx.id in processed:
                        continue

                    # Find all transactions within time window
                    time_window = timedelta(minutes=HEURISTIC_TIME_WINDOW_MINUTES)
                    similar_txs = [tx]

                    for j, other_tx in enumerate(tx_list[i + 1 :], start=i + 1):
                        if other_tx.id in processed:
                            continue

                        time_diff = abs((other_tx.timestamp_utc - tx.timestamp_utc).total_seconds())
                        if time_diff <= time_window.total_seconds():
                            similar_txs.append(other_tx)
                            processed.add(other_tx.id)

                    if len(similar_txs) > 1:
                        # Sort by priority
                        similar_txs.sort(
                            key=lambda t: (
                                PLATFORM_PRIORITY.index(t.source_platform)
                                if t.source_platform in PLATFORM_PRIORITY
                                else len(PLATFORM_PRIORITY)
                            )
                        )
                        # Mark all but first as duplicates
                        for duplicate_tx in similar_txs[1:]:
                            duplicate_tx.is_duplicate = True
                        # Count this as one heuristic match group
                        heuristic_matches += 1

        # Commit all changes
        self.session.commit()

        # Calculate final counts
        kept_count = sum(1 for tx in transactions if not tx.is_duplicate)
        removed_count = sum(1 for tx in transactions if tx.is_duplicate)

        return DeduplicationReport(
            total_checked=total_checked,
            exact_matches=exact_matches,
            heuristic_matches=heuristic_matches,
            kept_count=kept_count,
            removed_count=removed_count,
        )
