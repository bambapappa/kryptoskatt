"""Report endpoints for API v1."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.reports.gav_history import GavHistoryReport
from kryptoskatt.reports.k4 import K4ReportGenerator
from kryptoskatt.reports.net_position import NetPositionReport
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


def _get_db():
    from kryptoskatt.db import get_session
    s = get_session()
    try:
        yield s
    finally:
        s.close()


@router.get("/k4/{year}")
def k4_report(
    year: int,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    gen = K4ReportGenerator(db, account.id)
    report = gen.generate(year)
    return {
        "year": year,
        "rows": [
            {
                "coin": r.coin,
                "proceeds_sek": str(r.proceeds_sek),
                "cost_basis_sek": str(r.cost_basis_sek),
                "gain_loss_sek": str(r.gain_loss_sek),
            }
            for r in report.rows
        ],
    }


@router.get("/gav-history")
def gav_history(
    coin: str | None = None,
    year: int | None = None,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    gen = GavHistoryReport(db, account.id)
    snapshots = gen.generate(coin=coin, year=year)
    return {"snapshots": [
        {
            "coin": s.coin,
            "timestamp": s.timestamp,
            "event_type": s.event_type,
            "amount_change": str(s.amount_change),
            "gav_per_unit": str(s.gav_per_unit),
            "total_units": str(s.total_units),
            "total_cost": str(s.total_cost),
        }
        for s in snapshots
    ]}


@router.get("/net-position/{year}")
def net_position(
    year: int,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    gen = NetPositionReport(db, account.id)
    rows = gen.generate(year)
    return {"rows": [
        {
            "coin": r.coin,
            "total_received": str(r.total_received),
            "total_sent": str(r.total_sent),
            "net_change": str(r.net_change),
        }
        for r in rows
    ]}
