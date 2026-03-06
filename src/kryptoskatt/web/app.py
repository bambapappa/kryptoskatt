"""FastAPI web application for KryptoSkatt."""

import io
import json
from pathlib import Path
from typing import Generator

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from kryptoskatt.db import get_session
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.reports.k4 import K4ReportGenerator
from kryptoskatt.reports.gav_history import GavHistoryReport
from kryptoskatt.reports.issues import FlaggedIssuesGenerator


# Templates path: relative to this file
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


# Add custom Jinja2 filter for absolute value
def _abs_filter(value):
    """Jinja2 filter for absolute value."""
    if value is None:
        return None
    return abs(value)


templates.env.filters["abs"] = _abs_filter

app = FastAPI(title="KryptoSkatt", description="Swedish Crypto Tax Reports")


def get_db() -> Generator[Session, None, None]:
    """Database session dependency."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    """Dashboard listing available tax years with Disposal records."""
    # Get distinct years with disposals
    stmt = select(func.distinct(Disposal.tax_year)).order_by(Disposal.tax_year.desc())
    years = db.execute(stmt).scalars().all()

    return templates.TemplateResponse(request, "dashboard.html", {"years": years})


@app.get("/year/{year}", response_class=HTMLResponse)
def year_summary(request: Request, year: int, db: Session = Depends(get_db)):
    """K4 summary for a given year."""
    report_generator = K4ReportGenerator(db)
    report = report_generator.generate(year)

    return templates.TemplateResponse(
        request,
        "year_summary.html",
        {"year": year, "report": report},
    )


@app.get("/year/{year}/transactions", response_class=HTMLResponse)
def transactions(request: Request, year: int, page: int = 1, db: Session = Depends(get_db)):
    """Paginated transaction list for a given year."""
    page_size = 20

    # Get total count
    count_stmt = select(func.count(Disposal.id)).where(Disposal.tax_year == year)
    total_count = db.execute(count_stmt).scalar() or 0

    # Get paginated results
    offset = (page - 1) * page_size
    stmt = (
        select(Disposal)
        .where(Disposal.tax_year == year)
        .order_by(Disposal.sell_timestamp)
        .offset(offset)
        .limit(page_size)
    )
    disposals = db.execute(stmt).scalars().all()

    has_next = (offset + page_size) < total_count

    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "year": year,
            "disposals": disposals,
            "total_count": total_count,
            "page": page,
            "has_next": has_next,
        },
    )


@app.get("/year/{year}/download/csv")
def download_csv(year: int, db: Session = Depends(get_db)):
    """Download K4 report as CSV."""
    report_generator = K4ReportGenerator(db)
    report = report_generator.generate(year)

    # Write to temporary file
    with io.StringIO() as f:
        temp_path = Path(f"/tmp/k4_{year}.csv")
        K4ReportGenerator.export_csv(report, temp_path)

        # Read content back
        content = temp_path.read_text(encoding="utf-8-sig")
        temp_path.unlink()

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="k4_{year}.csv"'},
    )


@app.get("/year/{year}/download/json")
def download_json(year: int, db: Session = Depends(get_db)):
    """Download K4 report as JSON."""
    report_generator = K4ReportGenerator(db)
    report = report_generator.generate(year)

    # Write to temporary file
    with io.StringIO() as f:
        temp_path = Path(f"/tmp/k4_{year}.json")
        K4ReportGenerator.export_json(report, temp_path)

        # Read content back
        content = temp_path.read_text(encoding="utf-8")
        temp_path.unlink()

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="k4_{year}.json"'},
    )


@app.get("/year/{year}/gav/{coin}", response_class=HTMLResponse)
def gav_history(request: Request, year: int, coin: str, db: Session = Depends(get_db)):
    """GAV history for a specific coin."""
    report_generator = GavHistoryReport(db)
    snapshots = report_generator.generate(coin=coin, year=year)
    return templates.TemplateResponse(
        request,
        "gav_history.html",
        {"request": request, "year": year, "coin": coin, "snapshots": snapshots},
    )


@app.get("/year/{year}/issues", response_class=HTMLResponse)
def issues(request: Request, year: int, db: Session = Depends(get_db)):
    """Flagged issues for a given year."""
    report_generator = FlaggedIssuesGenerator(db)
    issues_report = report_generator.generate(year=year)
    return templates.TemplateResponse(
        request,
        "issues.html",
        {"year": year, "issues_report": issues_report},
    )
