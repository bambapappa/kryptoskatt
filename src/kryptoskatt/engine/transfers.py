"""Transfer matching engine for identifying non-taxable wallet-to-wallet transfers."""

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.transfer_link import TransferLink
from kryptoskatt.enums import EventType


# Confidence scores for match methods
TX_HASH_CONFIDENCE = Decimal("0.9500")
AMOUNT_TIME_CONFIDENCE = Decimal("0.7500")


@dataclass
class TransferMatchReport:
    """Report summarizing transfer matching results."""

    total_checked: int  # total TRANSFER_OUT transactions examined
    matched: int  # successfully linked to a TRANSFER_IN
    unmatched: int  # TRANSFER_OUT to external/unknown address
    ambiguous: int  # multiple possible matches found


class TransferMatcher:
    """Matches TRANSFER_OUT transactions to TRANSFER_IN transactions."""

    # Fee tolerance: allow up to 5% difference to account for transfer fees
    FEE_TOLERANCE = Decimal("0.05")
    TIME_WINDOW = timedelta(minutes=30)

    def __init__(self, session: Session, my_addresses: set[tuple[str, str]]):
        """Initialize the TransferMatcher.

        Args:
            session: SQLAlchemy session
            my_addresses: set of (address, chain) tuples from WalletService.get_my_addresses()
        """
        self.session = session
        self.my_addresses = my_addresses
        # Also build a set of just addresses (for cases where chain isn't known)
        self.my_address_set = {addr for addr, _ in my_addresses}

    def match_all(self) -> TransferMatchReport:
        """Match all TRANSFER_OUT transactions to corresponding TRANSFER_IN.

        Returns:
            TransferMatchReport with counts of matched, unmatched, and ambiguous transfers.
        """
        # Get all TRANSFER_OUT transactions not already linked
        transfer_outs = self._get_unlinked_transfer_outs()

        total_checked = 0
        matched = 0
        unmatched = 0
        ambiguous = 0

        for tx_out in transfer_outs:
            total_checked += 1
            result = self._match_single_transfer_out(tx_out)

            if result == "matched":
                matched += 1
            elif result == "unmatched":
                unmatched += 1
            elif result == "ambiguous":
                ambiguous += 1

        return TransferMatchReport(
            total_checked=total_checked,
            matched=matched,
            unmatched=unmatched,
            ambiguous=ambiguous,
        )

    def _get_unlinked_transfer_outs(self) -> list[Transaction]:
        """Get all TRANSFER_OUT transactions not already in a TransferLink."""
        # Get IDs of transactions already linked as tx_out
        linked_out_ids = set(self.session.execute(select(TransferLink.tx_out_id)).scalars().all())

        # Query for TRANSFER_OUT transactions not already linked
        query = (
            select(Transaction)
            .where(Transaction.event_type == EventType.TRANSFER_OUT)
            .order_by(Transaction.timestamp_utc)
        )

        all_transfer_outs = self.session.execute(query).scalars().all()

        # Filter out already linked
        return [tx for tx in all_transfer_outs if tx.id not in linked_out_ids]

    def _match_single_transfer_out(self, tx_out: Transaction) -> str:
        """Attempt to match a single TRANSFER_OUT to a TRANSFER_IN.

        Args:
            tx_out: The TRANSFER_OUT transaction to match.

        Returns:
            'matched' if exactly one match found and link created,
            'unmatched' if no match found,
            'ambiguous' if multiple possible matches found.
        """
        # Check if to_address is in user's wallet addresses
        # If NOT, this is an external withdrawal (potential taxable event)
        if tx_out.to_address not in self.my_address_set:
            return "unmatched"

        # Try TX_HASH match first
        tx_hash_matches = self._find_tx_hash_matches(tx_out)
        if len(tx_hash_matches) == 1:
            self._create_transfer_link(tx_out, tx_hash_matches[0], "TX_HASH", TX_HASH_CONFIDENCE)
            return "matched"
        elif len(tx_hash_matches) > 1:
            return "ambiguous"

        # Try AMOUNT_TIME match
        amount_time_matches = self._find_amount_time_matches(tx_out)
        if len(amount_time_matches) == 1:
            self._create_transfer_link(
                tx_out, amount_time_matches[0], "AMOUNT_TIME", AMOUNT_TIME_CONFIDENCE
            )
            return "matched"
        elif len(amount_time_matches) > 1:
            return "ambiguous"

        # No matches found
        return "unmatched"

    def _find_tx_hash_matches(self, tx_out: Transaction) -> list[Transaction]:
        """Find TRANSFER_IN transactions with the same tx_hash."""
        if not tx_out.tx_hash:
            return []

        # Find TRANSFER_IN with same tx_hash
        query = (
            select(Transaction)
            .where(Transaction.event_type == EventType.TRANSFER_IN)
            .where(Transaction.tx_hash == tx_out.tx_hash)
        )

        return list(self.session.execute(query).scalars().all())

    def _find_amount_time_matches(self, tx_out: Transaction) -> list[Transaction]:
        """Find TRANSFER_IN transactions matching by amount and time.

        Matching criteria:
        - Same base_coin
        - Amount within fee tolerance: abs(out_amount) * (1 - tolerance) <= in_amount <= abs(out_amount) * (1 + tolerance)
        - Timestamp within TIME_WINDOW (30 minutes)
        """
        out_amount_abs = abs(tx_out.base_amount)
        out_time = tx_out.timestamp_utc
        out_coin = tx_out.base_coin

        # Calculate amount bounds
        min_amount = out_amount_abs * (Decimal("1") - self.FEE_TOLERANCE)
        max_amount = out_amount_abs * (Decimal("1") + self.FEE_TOLERANCE)

        # Calculate time bounds
        min_time = out_time - self.TIME_WINDOW
        max_time = out_time + self.TIME_WINDOW

        # Query for potential matches
        query = (
            select(Transaction)
            .where(Transaction.event_type == EventType.TRANSFER_IN)
            .where(Transaction.base_coin == out_coin)
            .where(Transaction.base_amount >= min_amount)
            .where(Transaction.base_amount <= max_amount)
            .where(Transaction.timestamp_utc >= min_time)
            .where(Transaction.timestamp_utc <= max_time)
        )

        potential_matches = self.session.execute(query).scalars().all()

        return list(potential_matches)

    def _create_transfer_link(
        self,
        tx_out: Transaction,
        tx_in: Transaction,
        match_method: str,
        confidence: Decimal,
    ) -> TransferLink:
        """Create a TransferLink between two transactions."""
        link = TransferLink(
            tx_out_id=tx_out.id,
            tx_in_id=tx_in.id,
            match_method=match_method,
            confidence=confidence,
        )
        self.session.add(link)
        self.session.commit()
        return link
