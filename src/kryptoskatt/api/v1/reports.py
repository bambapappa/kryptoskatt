"""Report endpoints for API v1."""

import io
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.reports.audit import AuditExport
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


@router.get("/k4/{year}/csv")
def k4_report_csv(
    year: int,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    gen = K4ReportGenerator(db, account.id)
    report = gen.generate(year)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    K4ReportGenerator.export_csv(report, tmp_path)
    content = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)

    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="k4_{year}.csv"'},
    )


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


@router.get("/audit/{year}")
def audit_report(
    year: int,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    gen = AuditExport(db, account.id)
    rows = gen.generate(year)
    return {"rows": [
        {
            "rapport": r.rapport,
            "datum": r.datum.isoformat(),
            "tid": r.tid,
            "typ": r.typ,
            "tillgang": r.tillgang,
            "antal": str(r.antal),
            "pris_sek": str(r.pris_sek) if r.pris_sek is not None else None,
            "belopp_sek": str(r.belopp_sek) if r.belopp_sek is not None else None,
            "tx_hash": r.tx_hash,
            "explorer_url": r.explorer_url,
            "kalla": r.kalla,
            "fran_adress": r.fran_adress,
            "till_adress": r.till_adress,
        }
        for r in rows
    ]}
