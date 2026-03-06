"""Flagged Issues Report - identifies data quality issues for manual review."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.transfer_link import TransferLink


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

    year: Optional[int]
    issues: list[Issue]
    total_errors: int
    total_warnings: int
    total_info: int

    model_config = {"from_attributes": True}


class FlaggedIssuesGenerator:
    """Generates FlaggedIssuesReport to identify data quality issues."""

    def __init__(self, session: Session):
        """Initialize with a database session.

        Args:
            session: SQLAlchemy session for database queries.
        """
        self._session = session

    def generate(self, year: Optional[int] = None) -> FlaggedIssuesReport:
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

    def _detect_missing_prices(self, year: Optional[int]) -> list[Issue]:
        """Detect transactions where price_sek is None.

        These are typically BUY, SELL, SWAP_IN, SWAP_OUT transactions where
        CoinGecko didn't have a price at the time.
        """
        issues: list[Issue] = []

        # Query transactions with missing prices (exclude fees and transfers)
        stmt = (
            select(Transaction)
            .where(Transaction.price_sek.is_(None))
            .where(Transaction.event_type.in_(["BUY", "SELL", "SWAP_IN", "SWAP_OUT"]))
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

    def _detect_unknown_cost_basis(self, year: Optional[int]) -> list[Issue]:
        """Detect disposals where cost_basis_sek is 0.

        This means no prior acquisition was found to match against.
        """
        issues: list[Issue] = []

        # Query disposals with zero cost basis
        stmt = (
            select(Disposal).where(Disposal.cost_basis_sek == 0).order_by(Disposal.sell_timestamp)
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

    def _detect_unmatched_transfers(self, year: Optional[int]) -> list[Issue]:
        """Detect TRANSFER_OUT transactions without a TransferLink.

        This could indicate an external withdrawal (not tracked) or
        a transfer that wasn't matched to an incoming transaction.
        """
        issues: list[Issue] = []

        # Get all TRANSFER_OUT transactions
        stmt = (
            select(Transaction)
            .where(Transaction.event_type == "TRANSFER_OUT")
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

    def _detect_heuristic_dedup(self, year: Optional[int]) -> list[Issue]:
        """Detect transactions flagged as duplicates by heuristic deduplication.

        These are transactions that look like duplicates but weren't auto-merged.
        """
        issues: list[Issue] = []

        # Query transactions marked as duplicates
        stmt = (
            select(Transaction)
            .where(Transaction.is_duplicate == True)  # noqa: E712
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

    def _detect_sell_exceeds_hold(self, year: Optional[int]) -> list[Issue]:
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
            .where(Disposal.cost_basis_sek > Disposal.proceeds_sek * 10)
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
