"""GAV (Genomsnittsmetoden) Calculation Engine for Swedish cryptocurrency taxation."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from kryptoskatt.enums import EventType
from kryptoskatt.models.coin_blacklist import CoinBlacklist
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.gav_ledger import GavLedger
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.transfer_link import TransferLink


@dataclass
class CalculationResult:
    """Result of GAV calculation."""

    disposals: list[Disposal] = field(default_factory=list)
    gav_ledger_entries: list[GavLedger] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class GavEngine:
    """Engine for calculating GAV (Genomsnittsmetoden / Average Cost Method).

    Implements Swedish Skatteverket's average cost method for cryptocurrency
    tax calculations.
    """

    # Event types that are acquisitions (add to holdings)
    ACQUISITION_EVENTS = {EventType.BUY, EventType.SWAP_IN, EventType.REWARD}

    # Event types that are disposals (taxable events)
    DISPOSAL_EVENTS = {EventType.SELL, EventType.SWAP_OUT}

    # Event types that are transfers (potentially non-taxable if linked)
    TRANSFER_EVENTS = {EventType.TRANSFER_IN, EventType.TRANSFER_OUT}

    def __init__(self, session: Session):
        self.session = session
        # Per-coin state: coin -> (total_units, total_cost_sek)
        self._holdings: dict[str, tuple[Decimal, Decimal]] = {}

    def calculate(self, year: int | None = None) -> CalculationResult:
        """Calculate GAV and generate disposal records.

        Args:
            year: Optional year to filter disposals. If None, all disposals returned.

        Returns:
            CalculationResult with disposals, GavLedger entries, and warnings.
        """
        # Reset state
        self._holdings = {}

        # Clear previous results so re-runs don't accumulate duplicates.
        # GavLedger spans all years so always fully cleared.
        # Disposals are cleared for the requested year only (or all if year=None).
        self.session.execute(delete(GavLedger))
        if year is not None:
            self.session.execute(delete(Disposal).where(Disposal.tax_year == year))
        else:
            self.session.execute(delete(Disposal))
        self.session.commit()

        # Load blacklisted coin symbols (stored uppercase; compare case-insensitively
        # because spam token names arrive in mixed case from chain explorers)
        blacklisted = {
            row.coin_symbol.upper()
            for row in self.session.execute(select(CoinBlacklist)).scalars().all()
        }

        # Get all non-duplicate transactions ordered by timestamp, excluding blacklisted coins
        from sqlalchemy import func as sqlfunc
        stmt = select(Transaction).where(
            Transaction.is_duplicate == False,
            sqlfunc.upper(Transaction.base_coin).notin_(blacklisted) if blacklisted else True,
        ).order_by(Transaction.timestamp_utc, Transaction.id)
        transactions = list(self.session.execute(stmt).scalars().all())

        # Detect DEX swaps in memory: same tx_hash with TRANSFER_OUT of coin A and
        # TRANSFER_IN of coin B (A ≠ B) → reclassify to SWAP_OUT/SWAP_IN so the GAV
        # engine treats them as taxable disposals/acquisitions rather than transfers.
        # The DB is not modified; overrides apply only during this calculation.
        swap_overrides = self._detect_swap_pairs(transactions)

        # Build transfer link lookup
        transfer_links = self._build_transfer_lookup()

        # Separate acquisitions and disposals for same-timestamp ordering
        # Process acquisitions (BUY, SWAP_IN, REWARD) before disposals (SELL, SWAP_OUT)
        # at the same timestamp
        sorted_events = self._sort_events_by_timestamp_and_type(transactions, swap_overrides)

        warnings: list[str] = []
        disposals: list[Disposal] = []

        # Process each event
        for tx in sorted_events:
            event_warnings = self._process_event(tx, transfer_links, year, swap_overrides)
            warnings.extend(event_warnings)

        # Fetch created disposals for the result
        if year is not None:
            disposal_stmt = select(Disposal).where(Disposal.tax_year == year)
        else:
            disposal_stmt = select(Disposal)

        disposals = list(self.session.execute(disposal_stmt).scalars().all())

        # Fetch all GavLedger entries
        ledger_stmt = select(GavLedger).order_by(GavLedger.timestamp, GavLedger.id)
        ledger_entries = list(self.session.execute(ledger_stmt).scalars().all())

        return CalculationResult(
            disposals=disposals,
            gav_ledger_entries=ledger_entries,
            warnings=warnings,
        )

    def _build_transfer_lookup(self) -> dict[int, int | None]:
        """Build lookup for transfer links: tx_id -> linked_tx_id (or None if address-registry)."""
        links = self.session.execute(select(TransferLink)).scalars().all()
        lookup: dict[int, int | None] = {}
        for link in links:
            # tx_out is always present; tx_in may be None for ADDRESS_REGISTRY links
            lookup[link.tx_out_id] = link.tx_in_id
            if link.tx_in_id is not None:
                lookup[link.tx_in_id] = link.tx_out_id
        return lookup

    def _detect_swap_pairs(self, transactions: list[Transaction]) -> dict[int, EventType]:
        """Detect DEX swap pairs from transactions sharing the same tx_hash.

        When a tx_hash has TRANSFER_OUT of coin A and TRANSFER_IN of coin B (A ≠ B),
        it is a DEX swap — not a wallet-to-wallet transfer. Reclassify:
          - TRANSFER_OUT of coins that only go out (not in) → SWAP_OUT
          - TRANSFER_IN of coins that only come in (not out) → SWAP_IN

        Coins appearing in BOTH directions (e.g. intermediate hops, partial refunds)
        are left unchanged. DB is never modified; returned dict is applied in memory.
        """
        from collections import defaultdict

        by_hash: dict[str, list[Transaction]] = defaultdict(list)
        for tx in transactions:
            if tx.tx_hash:
                by_hash[tx.tx_hash].append(tx)

        overrides: dict[int, EventType] = {}

        for _tx_hash, group in by_hash.items():
            transfer_outs = [t for t in group if t.event_type == EventType.TRANSFER_OUT]
            transfer_ins = [t for t in group if t.event_type == EventType.TRANSFER_IN]

            if not transfer_outs or not transfer_ins:
                continue

            out_coins = {t.base_coin for t in transfer_outs}
            in_coins = {t.base_coin for t in transfer_ins}

            # Only reclassify coins that appear exclusively in one direction
            swap_out_coins = out_coins - in_coins
            swap_in_coins = in_coins - out_coins

            # Both sides must have exclusive coins for this to be a swap
            if not swap_out_coins or not swap_in_coins:
                continue

            for t in transfer_outs:
                if t.base_coin in swap_out_coins:
                    overrides[t.id] = EventType.SWAP_OUT

            for t in transfer_ins:
                if t.base_coin in swap_in_coins:
                    overrides[t.id] = EventType.SWAP_IN

        return overrides

    def _sort_events_by_timestamp_and_type(
        self,
        transactions: list[Transaction],
        swap_overrides: dict[int, EventType] | None = None,
    ) -> list[Transaction]:
        """Sort events: chronologically, acquisitions before disposals at same time."""
        acquisition_types = {EventType.BUY, EventType.SWAP_IN, EventType.REWARD}
        disposal_types = {EventType.SELL, EventType.SWAP_OUT}
        overrides = swap_overrides or {}

        def sort_key(tx: Transaction) -> tuple:
            # Primary: timestamp
            # Secondary: acquisitions/inflows (1) before disposals/outflows (2) before others (3)
            # TRANSFER_IN must sort before TRANSFER_OUT at same timestamp so holdings exist
            timestamp = tx.timestamp_utc
            effective_type = overrides.get(tx.id, EventType(tx.event_type))
            if effective_type in acquisition_types or effective_type == EventType.TRANSFER_IN:
                type_order = 1
            elif effective_type in disposal_types or effective_type == EventType.TRANSFER_OUT:
                type_order = 2
            else:
                type_order = 3
            return (timestamp, type_order, tx.id)

        return sorted(transactions, key=sort_key)

    def _process_event(
        self,
        tx: Transaction,
        transfer_lookup: dict[int, int],
        filter_year: int | None,
        swap_overrides: dict[int, EventType] | None = None,
    ) -> list[str]:
        """Process a single transaction event.

        Returns:
            List of warning messages generated during processing.
        """
        warnings: list[str] = []
        coin = tx.base_coin
        amount = Decimal(str(tx.base_amount)) if tx.base_amount else Decimal("0")
        price_sek = Decimal(str(tx.price_sek)) if tx.price_sek else Decimal("0")
        fee_amount = Decimal(str(tx.fee_amount)) if tx.fee_amount else Decimal("0")
        overrides = swap_overrides or {}
        event_type = overrides.get(tx.id, EventType(tx.event_type))

        # Get or initialize holdings for this coin
        if coin not in self._holdings:
            self._holdings[coin] = (Decimal("0"), Decimal("0"))
        total_units, total_cost_sek = self._holdings[coin]

        # Calculate current GAV
        current_gav = Decimal("0")
        if total_units > 0:
            current_gav = total_cost_sek / total_units

        # Handle based on event type
        if event_type in self.ACQUISITION_EVENTS:
            # Acquisition: BUY, SWAP_IN, REWARD
            abs_amount = abs(amount)
            if abs_amount <= 0:
                return warnings

            # Calculate cost basis
            cost_basis = abs_amount * price_sek

            # Handle fee - add to cost if fee coin matches base coin
            fee_sek = Decimal("0")
            if tx.fee_coin == coin and fee_amount > 0:
                fee_sek = fee_amount * price_sek
            elif tx.fee_coin == "SEK":
                fee_sek = fee_amount
            # If fee is in different coin, we skip (not deductible for that coin)

            total_cost_sek += cost_basis + fee_sek
            total_units += abs_amount
            self._holdings[coin] = (total_units, total_cost_sek)

            # Create GavLedger entry
            self._create_gav_ledger_entry(
                coin=coin,
                timestamp=tx.timestamp_utc,
                event_type=event_type,
                amount_change=abs_amount,
                total_amount=total_units,
                total_cost_sek=total_cost_sek,
            )

        elif event_type in self.DISPOSAL_EVENTS:
            # Disposal: SELL, SWAP_OUT
            abs_amount = abs(amount)
            if abs_amount <= 0:
                return warnings

            # Check if price is known
            if tx.price_sek is None or Decimal(str(tx.price_sek)) == Decimal("0"):
                warnings.append(
                    f"Unknown price for {coin} at {tx.timestamp_utc.isoformat()}"
                )

            # Check if selling more than owned
            if abs_amount > total_units:
                warnings.append(
                    f"Selling {abs_amount} {coin} but only {total_units} held"
                )
                # Only sell what's available
                abs_amount = total_units

            if abs_amount > 0:
                # Calculate proceeds (use price_sek or 0 if unknown)
                proceeds = abs_amount * price_sek

                # Subtract fee from proceeds if fee is in SEK
                fee_sek = Decimal("0")
                if tx.fee_coin == "SEK" and fee_amount > 0:
                    fee_sek = fee_amount
                proceeds -= fee_sek

                # Calculate cost basis using current GAV
                cost_basis = abs_amount * current_gav

                # Calculate gain/loss
                gain_loss = proceeds - cost_basis

                # Determine tax year
                tax_year = tx.timestamp_utc.year
                create_disposal = filter_year is None or tax_year == filter_year

                if create_disposal:
                    # Create Disposal record
                    disposal = Disposal(
                        tax_year=tax_year,
                        coin=coin,
                        sell_timestamp=tx.timestamp_utc,
                        sell_amount=abs_amount,
                        proceeds_sek=proceeds,
                        cost_basis_sek=cost_basis,
                        gain_loss_sek=gain_loss,
                        gav_at_disposal=current_gav,
                    )
                    self.session.add(disposal)
                    self.session.commit()

                # Update holdings
                total_units -= abs_amount
                total_cost_sek -= cost_basis

                # If fully sold, reset GAV
                if total_units == Decimal("0"):
                    total_cost_sek = Decimal("0")

                self._holdings[coin] = (total_units, total_cost_sek)

                # Create GavLedger entry
                self._create_gav_ledger_entry(
                    coin=coin,
                    timestamp=tx.timestamp_utc,
                    event_type=event_type,
                    amount_change=-abs_amount,
                    total_amount=total_units,
                    total_cost_sek=total_cost_sek,
                )

        elif event_type in self.TRANSFER_EVENTS:
            # Transfer: TRANSFER_IN or TRANSFER_OUT
            # Check if this transfer has a linked counterpart (non-taxable)
            linked_tx_id = transfer_lookup.get(tx.id)

            if tx.id in transfer_lookup:
                # Linked transfer - non-taxable (tx_in_id may be None for address-registry links)
                # Handle fee if present (transfer fees are deductible)
                fee_sek = Decimal("0")
                if tx.fee_coin == "SEK" and fee_amount > 0:
                    fee_sek = fee_amount
                elif tx.fee_coin == coin and fee_amount > 0:
                    # Fee in same coin - convert to SEK
                    fee_sek = fee_amount * price_sek

                if event_type == EventType.TRANSFER_IN:
                    # Receiving coins - add to holdings
                    abs_amount = abs(amount)
                    total_units += abs_amount
                    total_cost_sek += (abs_amount * price_sek) + fee_sek
                else:
                    # Sending coins - remove from holdings
                    abs_amount = abs(amount)
                    if abs_amount > total_units:
                        warnings.append(
                            f"Transferring {abs_amount} {coin} but only {total_units} held"
                        )
                        abs_amount = total_units

                    cost_basis = abs_amount * current_gav
                    total_units -= abs_amount
                    total_cost_sek -= cost_basis

                    # If fully transferred, reset
                    if total_units == Decimal("0"):
                        total_cost_sek = Decimal("0")

                self._holdings[coin] = (total_units, total_cost_sek)

                # Create GavLedger entry for transfer
                amount_change = abs(amount) if event_type == EventType.TRANSFER_IN else -abs(amount)
                self._create_gav_ledger_entry(
                    coin=coin,
                    timestamp=tx.timestamp_utc,
                    event_type=event_type,
                    amount_change=amount_change,
                    total_amount=total_units,
                    total_cost_sek=total_cost_sek,
                )
            else:
                # Unlinked transfer
                abs_amount = abs(amount)
                if abs_amount > 0:
                    if event_type == EventType.TRANSFER_IN:
                        # Unlinked TRANSFER_IN: external receipt (e.g. mining reward, gift,
                        # withdrawal from untracked exchange). Treat as acquisition at market price.
                        total_units += abs_amount
                        total_cost_sek += abs_amount * price_sek
                        self._holdings[coin] = (total_units, total_cost_sek)

                        self._create_gav_ledger_entry(
                            coin=coin,
                            timestamp=tx.timestamp_utc,
                            event_type=event_type,
                            amount_change=abs_amount,
                            total_amount=total_units,
                            total_cost_sek=total_cost_sek,
                        )
                    else:
                        # Unlinked TRANSFER_OUT: taxable disposal (sent to external party)
                        if abs_amount > total_units:
                            warnings.append(
                                f"Transferring {abs_amount} {coin} but only {total_units} held"
                            )
                            abs_amount = total_units

                        # Skip if nothing to dispose (no holdings at all)
                        if abs_amount == Decimal("0"):
                            return warnings

                        proceeds = abs_amount * price_sek
                        cost_basis = abs_amount * current_gav
                        gain_loss = proceeds - cost_basis

                        tax_year = tx.timestamp_utc.year
                        create_disposal = filter_year is None or tax_year == filter_year

                        if create_disposal:
                            disposal = Disposal(
                                tax_year=tax_year,
                                coin=coin,
                                sell_timestamp=tx.timestamp_utc,
                                sell_amount=abs_amount,
                                proceeds_sek=proceeds,
                                cost_basis_sek=cost_basis,
                                gain_loss_sek=gain_loss,
                                gav_at_disposal=current_gav,
                            )
                            self.session.add(disposal)
                            self.session.commit()

                        total_units -= abs_amount
                        total_cost_sek -= cost_basis

                        if total_units == Decimal("0"):
                            total_cost_sek = Decimal("0")

                        self._holdings[coin] = (total_units, total_cost_sek)

                        self._create_gav_ledger_entry(
                            coin=coin,
                            timestamp=tx.timestamp_utc,
                            event_type=event_type,
                            amount_change=-abs_amount,
                            total_amount=total_units,
                            total_cost_sek=total_cost_sek,
                        )

        elif event_type == EventType.FEE:
            # Standalone fee - reduce cost basis
            fee_sek = Decimal("0")
            if tx.fee_coin == "SEK":
                fee_sek = fee_amount
            elif tx.fee_coin == coin and fee_amount > 0:
                fee_sek = fee_amount * price_sek

            if fee_sek > 0 and total_cost_sek > 0:
                # Deduct fee from cost basis
                total_cost_sek = max(Decimal("0"), total_cost_sek - fee_sek)
                self._holdings[coin] = (total_units, total_cost_sek)

                # Create GavLedger entry
                self._create_gav_ledger_entry(
                    coin=coin,
                    timestamp=tx.timestamp_utc,
                    event_type=event_type,
                    amount_change=Decimal("0"),
                    total_amount=total_units,
                    total_cost_sek=total_cost_sek,
                )

        return warnings

    def _create_gav_ledger_entry(
        self,
        coin: str,
        timestamp: datetime,
        event_type: str,
        amount_change: Decimal,
        total_amount: Decimal,
        total_cost_sek: Decimal,
    ) -> None:
        """Create a GavLedger entry for the current state."""
        # Calculate GAV per unit
        gav_per_unit = Decimal("0")
        if total_amount > 0:
            gav_per_unit = total_cost_sek / total_amount

        entry = GavLedger(
            coin=coin,
            timestamp=timestamp,
            event_type=event_type,
            amount_change=amount_change,
            total_amount=total_amount,
            total_cost_sek=total_cost_sek,
            gav_per_unit_sek=gav_per_unit,
        )
        self.session.add(entry)
        self.session.commit()
