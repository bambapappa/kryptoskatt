"""Report endpoints for API v1."""

import io
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kryptoskatt.engine.price_enrichment import PriceEnrichmentEngine
from kryptoskatt.models.account import Account
from kryptoskatt.reports.audit import AuditExport
from kryptoskatt.reports.gav_history import GavHistoryReport
from kryptoskatt.reports.k4 import K4ReportGenerator
from kryptoskatt.reports.net_position import NetPositionReport
from kryptoskatt.reports.t2 import T2IncomeReport
from kryptoskatt.web.auth import get_current_account

router = APIRouter()

# In-memory job store for async enrichment runs.
# Keyed by short job_id (8 hex chars). Entries are never evicted — this is
# intentional for a single-tenant tool where the job count stays tiny.
_enrichment_jobs: dict[str, dict[str, Any]] = {}


class EnrichPricesRequest(BaseModel):
    year: int | None = None


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


@router.get("/t2/{year}")
def t2_report(
    year: int,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Bilaga T2 income/cost report for a tax year."""
    report = T2IncomeReport(db, account.id).generate(year)
    return {
        "tax_year": report.tax_year,
        "total_income_sek": str(report.total_income_sek),
        "total_cost_sek": str(report.total_cost_sek),
        "net_sek": str(report.net_sek),
        "income_rows": [
            {
                "coin": r.coin,
                "category": r.category,
                "label": r.label,
                "event_count": r.event_count,
                "total_units": str(r.total_units),
                "total_sek": str(r.total_sek),
                "unpriced_units": str(r.unpriced_units),
            }
            for r in report.income_rows
        ],
        "cost_rows": [
            {
                "coin": r.coin,
                "category": r.category,
                "label": r.label,
                "event_count": r.event_count,
                "total_units": str(r.total_units),
                "total_sek": str(r.total_sek),
                "unpriced_units": str(r.unpriced_units),
            }
            for r in report.cost_rows
        ],
        "manual_cost_rows": [
            {
                "id": r.id,
                "entry_date": r.entry_date.isoformat() if r.entry_date else None,
                "description": r.description,
                "amount_sek": str(r.amount_sek),
                "vendor": r.vendor,
            }
            for r in report.manual_cost_rows
        ],
    }


@router.post("/enrich-prices/async")
def enrich_prices_async(
    body: EnrichPricesRequest,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Start price enrichment in background. Poll /enrich-prices/status/{job_id}.

    Returns immediately with a job_id. The enrichment runs in a daemon thread
    so it does not block the request. Use the status endpoint to poll for
    completion.
    """
    job_id = uuid.uuid4().hex[:8]
    _enrichment_jobs[job_id] = {"status": "running", "result": None}

    def _run() -> None:
        try:
            engine = PriceEnrichmentEngine(db, account.id)
            report = engine.enrich()
            _enrichment_jobs[job_id] = {
                "status": "done",
                "result": {
                    "enriched": report.enriched + report.swap_implied,
                    "skipped": report.skipped_api_miss,
                    "total": report.total,
                    "swap_implied": report.swap_implied,
                    "skipped_unknown_coin": report.skipped_unknown_coin,
                },
            }
        except Exception as exc:
            _enrichment_jobs[job_id] = {"status": "error", "error": str(exc)}

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "running"}


@router.get("/enrich-prices/status/{job_id}")
def enrich_prices_status(
    job_id: str,
    account: Account = Depends(get_current_account),
):
    """Return the current status of an async enrichment job."""
    job = _enrichment_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/enrich-prices")
def enrich_prices(
    body: EnrichPricesRequest,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Fill in missing price_sek for transactions via CoinGecko and swap pairs.

    The optional 'year' field is accepted for API compatibility but enrichment
    runs across all years (transactions are filtered by what is missing a price).
    """
    engine = PriceEnrichmentEngine(db, account.id)
    report = engine.enrich()
    return {
        "enriched": report.enriched + report.swap_implied,
        "skipped": report.skipped_api_miss,
        "total": report.total,
        "swap_implied": report.swap_implied,
        "skipped_unknown_coin": report.skipped_unknown_coin,
    }
