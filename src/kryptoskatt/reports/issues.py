"""Flagged Issues Report - identifies data quality issues for manual review."""

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.transfer_link import TransferLink

# Maximum time window to look for a matching SWAP_OUT when we find a SWAP_IN
_SWAP_PAIR_WINDOW = timedelta(minutes=30)


class Issue(BaseModel):
    """A single flagged issue that needs manual review."""

    severity: str  # ERROR, WARNING, INFO
    category: str  # missing_price, unknown_cost_basis, unmatched_transfer, heuristic_dedup, sell_exceeds_hold
    coin: str
    timestamp_utc: datetime
    amount: Decimal
    description: str

    model_config = {"from_attributes": True}


class FlaggedIssuesReport(BaseModel):
    """Report containing all flagged issues for a tax year."""

    year: int | None
    issues: list[Issue]
    total_errors: int
    total_warnings: int
    total_info: int

    model_config = {"from_attributes": True}


class FlaggedIssuesGenerator:
    """Generates FlaggedIssuesReport to identify data quality issues."""

    def __init__(self, session: Session, user_id: int):
        """Initialize with a database session and user_id.

        Args:
            session: SQLAlchemy session for database queries.
            user_id: Account DB id to scope queries to.
        """
        self._session = session
        self._user_id = user_id

    def generate(self, year: int | None = None) -> FlaggedIssuesReport:
        """Generate flagged issues report.

        Args:
            year: Optional tax year to filter issues. If None, reports on all years.

        Returns:
            FlaggedIssuesReport with all flagged issues.
        """
        issues: list[Issue] = []

        # 1. Detect missing prices (transactions where price_sek is None)
        issues.extend(self._detect_missing_prices(year))

        # 2. Detect unknown cost basis (disposals where cost_basis_sek = 0)
        issues.extend(self._detect_unknown_cost_basis(year))

        # 3. Detect unmatched transfers (TRANSFER_OUT without TransferLink)
        issues.extend(self._detect_unmatched_transfers(year))

        # 4. Detect heuristic duplicates (transactions flagged as duplicates)
        issues.extend(self._detect_heuristic_dedup(year))

        # 5. Detect sells exceeding holdings (from GAV engine checks)
        issues.extend(self._detect_sell_exceeds_hold(year))

        # 6. Detect unbalanced SWAPs (SWAP_IN without a matching SWAP_OUT)
        issues.extend(self._detect_unbalanced_swaps(year))

        # Calculate totals
        total_errors = sum(1 for i in issues if i.severity == "ERROR")
        total_warnings = sum(1 for i in issues if i.severity == "WARNING")
        total_info = sum(1 for i in issues if i.severity == "INFO")

        return FlaggedIssuesReport(
            year=year,
            issues=issues,
            total_errors=total_errors,
            total_warnings=total_warnings,
            total_info=total_info,
        )

    def _detect_missing_prices(self, year: int | None) -> list[Issue]:
        """Detect transactions where price_sek is None.

        These are typically BUY, SELL, SWAP_IN, SWAP_OUT transactions where
        CoinGecko didn't have a price at the time.
        """
        issues: list[Issue] = []

        # Query transactions with missing prices (exclude fees and transfers)
        stmt = (
            select(Transaction)
            .where(
                Transaction.user_id == self._user_id,
                Transaction.price_sek.is_(None),
                Transaction.event_type.in_(["BUY", "SELL", "SWAP_IN", "SWAP_OUT"]),
            )
            .order_by(Transaction.timestamp_utc)
        )

        if year:
            # Filter by year
            year_start = datetime(year, 1, 1, 0, 0, 0)
            year_end = datetime(year, 12, 31, 23, 59, 59)
            stmt = stmt.where(Transaction.timestamp_utc >= year_start)
            stmt = stmt.where(Transaction.timestamp_utc <= year_end)

        transactions = self._session.execute(stmt).scalars().all()

        for tx in transactions:
            issues.append(
                Issue(
                    severity="ERROR",
                    category="missing_price",
                    coin=tx.base_coin,
                    timestamp_utc=tx.timestamp_utc,
                    amount=tx.base_amount,
                    description=f"{tx.event_type} transaction without SEK price (CoinGecko lacked rate)",
                )
            )

        return issues

    def _detect_unknown_cost_basis(self, year: int | None) -> list[Issue]:
        """Detect disposals where cost_basis_sek is 0.

        This means no prior acquisition was found to match against.
        """
        issues: list[Issue] = []

        # Query disposals with zero cost basis
        stmt = (
            select(Disposal)
            .where(Disposal.user_id == self._user_id, Disposal.cost_basis_sek == 0)
            .order_by(Disposal.sell_timestamp)
        )

        if year:
            stmt = stmt.where(Disposal.tax_year == year)

        disposals = self._session.execute(stmt).scalars().all()

        for disposal in disposals:
            issues.append(
                Issue(
                    severity="ERROR",
                    category="unknown_cost_basis",
                    coin=disposal.coin,
                    timestamp_utc=disposal.sell_timestamp,
                    amount=disposal.sell_amount,
                    description="Disposal has zero cost basis - no matching acquisition found",
                )
            )

        return issues

    def _detect_unmatched_transfers(self, year: int | None) -> list[Issue]:
        """Detect TRANSFER_OUT transactions without a TransferLink.

        This could indicate an external withdrawal (not tracked) or
        a transfer that wasn't matched to an incoming transaction.
        """
        issues: list[Issue] = []

        # Get all TRANSFER_OUT transactions
        stmt = (
            select(Transaction)
            .where(
                Transaction.user_id == self._user_id,
                Transaction.event_type == "TRANSFER_OUT",
            )
            .order_by(Transaction.timestamp_utc)
        )

        if year:
            year_start = datetime(year, 1, 1, 0, 0, 0)
            year_end = datetime(year, 12, 31, 23, 59, 59)
            stmt = stmt.where(Transaction.timestamp_utc >= year_start)
            stmt = stmt.where(Transaction.timestamp_utc <= year_end)

        transfer_outs = self._session.execute(stmt).scalars().all()

        # Get all transfer link IDs
        linked_tx_out_ids = self._session.execute(select(TransferLink.tx_out_id)).scalars().all()
        linked_ids_set = set(linked_tx_out_ids)

        for tx in transfer_outs:
            if tx.id not in linked_ids_set:
                issues.append(
                    Issue(
                        severity="WARNING",
                        category="unmatched_transfer",
                        coin=tx.base_coin,
                        timestamp_utc=tx.timestamp_utc,
                        amount=tx.base_amount,
                        description="TRANSFER_OUT without matching transfer (possible external withdrawal)",
                    )
                )

        return issues

    def _detect_heuristic_dedup(self, year: int | None) -> list[Issue]:
        """Detect transactions flagged as duplicates by heuristic deduplication.

        These are transactions that look like duplicates but weren't auto-merged.
        """
        issues: list[Issue] = []

        # Query transactions marked as duplicates
        stmt = (
            select(Transaction)
            .where(
                Transaction.user_id == self._user_id,
                Transaction.is_duplicate == True,  # noqa: E712
            )
            .order_by(Transaction.timestamp_utc)
        )

        if year:
            year_start = datetime(year, 1, 1, 0, 0, 0)
            year_end = datetime(year, 12, 31, 23, 59, 59)
            stmt = stmt.where(Transaction.timestamp_utc >= year_start)
            stmt = stmt.where(Transaction.timestamp_utc <= year_end)

        duplicates = self._session.execute(stmt).scalars().all()

        for tx in duplicates:
            issues.append(
                Issue(
                    severity="INFO",
                    category="heuristic_dedup",
                    coin=tx.base_coin,
                    timestamp_utc=tx.timestamp_utc,
                    amount=tx.base_amount,
                    description="Transaction flagged as potential duplicate by heuristic dedup",
                )
            )

        return issues

    def _detect_sell_exceeds_hold(self, year: int | None) -> list[Issue]:
        """Detect sells where amount exceeded known holdings.

        This is checked in the GAV engine - disposals with negative holdings
        indicate sold more than was owned.
        """
        issues: list[Issue] = []

        # Look for disposals with extremely high cost basis relative to proceeds
        # that indicate the GAV engine couldn't track enough holdings
        # A cost_basis > proceeds * 10 is a strong indicator
        stmt = (
            select(Disposal)
            .where(
                Disposal.user_id == self._user_id,
                Disposal.cost_basis_sek > Disposal.proceeds_sek * 10,
            )
            .order_by(Disposal.sell_timestamp)
        )

        if year:
            stmt = stmt.where(Disposal.tax_year == year)

        suspicious_disposals = self._session.execute(stmt).scalars().all()

        for disposal in suspicious_disposals:
            issues.append(
                Issue(
                    severity="WARNING",
                    category="sell_exceeds_hold",
                    coin=disposal.coin,
                    timestamp_utc=disposal.sell_timestamp,
                    amount=disposal.sell_amount,
                    description="Cost basis significantly exceeds proceeds - possible oversell detected",
                )
            )

        return issues

    def _detect_unbalanced_swaps(self, year: int | None) -> list[Issue]:
        """Detect SWAP_IN transactions without a matching SWAP_OUT within 30 minutes.

        In Swedish tax law a DEX swap is a taxable disposal. When only one side
        of the swap is imported (e.g. data from a single chain) the SWAP_IN has
        no corresponding SWAP_OUT, meaning the taxable disposal leg is missing
        from the books. Flag these so the user can add the missing transactions.
        """
        issues: list[Issue] = []

        # Fetch all non-duplicate SWAP_IN and SWAP_OUT transactions (optionally year-filtered)
        def _year_filtered_stmt(event_type: str):
            stmt = select(Transaction).where(
                Transaction.user_id == self._user_id,
                Transaction.event_type == event_type,
                Transaction.is_duplicate.is_(False),
            )
            if year:
                year_start = datetime(year, 1, 1, 0, 0, 0)
                year_end = datetime(year, 12, 31, 23, 59, 59)
                stmt = stmt.where(Transaction.timestamp_utc >= year_start)
                stmt = stmt.where(Transaction.timestamp_utc <= year_end)
            return stmt

        swap_ins = self._session.execute(_year_filtered_stmt("SWAP_IN")).scalars().all()
        swap_outs = self._session.execute(_year_filtered_stmt("SWAP_OUT")).scalars().all()

        # Group SWAP_OUTs by coin so we can search quickly
        outs_by_coin: dict[str, list[Transaction]] = defaultdict(list)
        for tx in swap_outs:
            outs_by_coin[tx.base_coin].append(tx)

        for swap_in in swap_ins:
            ts = swap_in.timestamp_utc
            window_start = ts - _SWAP_PAIR_WINDOW
            window_end = ts + _SWAP_PAIR_WINDOW

            # A SWAP_IN for coin X should pair with a SWAP_OUT for a *different* coin
            # within the time window. We check all SWAP_OUTs (any coin) within ±30 min.
            has_paired_out = any(
                window_start <= out_tx.timestamp_utc <= window_end
                and out_tx.base_coin != swap_in.base_coin
                for out_txs in outs_by_coin.values()
                for out_tx in out_txs
            )

            if not has_paired_out:
                issues.append(
                    Issue(
                        severity="WARNING",
                        category="unbalanced_swap",
                        coin=swap_in.base_coin,
                        timestamp_utc=swap_in.timestamp_utc,
                        amount=Decimal(str(swap_in.base_amount)),
                        description=(
                            f"SWAP_IN for {swap_in.base_coin} has no matching SWAP_OUT "
                            "within 30 minutes — the taxable disposal leg may be missing"
                        ),
                    )
                )

        return issues
