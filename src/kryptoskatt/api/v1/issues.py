"""Issues endpoint for API v1."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.reports.issues import FlaggedIssuesGenerator
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


def _get_db():
    from kryptoskatt.db import get_session
    s = get_session()
    try:
        yield s
    finally:
        s.close()


def _issue_to_dict(issue) -> dict:
    return {
        "severity": issue.severity,
        "category": issue.category,
        "coin": issue.coin,
        "timestamp_utc": issue.timestamp_utc,
        "amount": str(issue.amount),
        "description": issue.description,
    }


@router.get("")
def list_issues(
    year: int | None = Query(default=None),
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Return flagged data-quality issues for the authenticated user."""
    gen = FlaggedIssuesGenerator(db, account.id)
    report = gen.generate(year=year)

    flagged_disposals = [i for i in report.issues if i.category in ("unknown_cost_basis", "sell_exceeds_hold")]
    flagged_transactions = [i for i in report.issues if i.category not in ("unknown_cost_basis", "sell_exceeds_hold")]

    return {
        "year": report.year,
        "total_errors": report.total_errors,
        "total_warnings": report.total_warnings,
        "total_info": report.total_info,
        "flagged_disposals": [_issue_to_dict(i) for i in flagged_disposals],
        "flagged_transactions": [_issue_to_dict(i) for i in flagged_transactions],
    }
