"""Public read-only share view for accountants.

Accessed via a secret token (no login). Strictly GET/read-only: it renders the
K4 summary, the year-to-year GAV carryover and net positions for one tax year,
scoped to the account the link belongs to.
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from kryptoskatt.models.disposal import Disposal
from kryptoskatt.reports.gav_carryover import GavCarryoverReport
from kryptoskatt.reports.k4 import K4ReportGenerator
from kryptoskatt.reports.net_position import NetPositionReport
from kryptoskatt.web.deps import get_db
from kryptoskatt.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/share/{token}", response_class=HTMLResponse)
def share_view(
    request: Request,
    token: str,
    year: int | None = None,
    db: Session = Depends(get_db),
):
    """Render a read-only tax summary for a valid share token."""
    from kryptoskatt.services.share_links import resolve_share_link

    link = resolve_share_link(db, token)
    if link is None:
        # Do not distinguish "expired" from "never existed" to avoid leaking.
        return templates.TemplateResponse(
            request, "share_invalid.html", {}, status_code=404
        )

    account_id = link.account_id

    # Tax years the account actually has disposals for.
    years = sorted(
        {
            row[0]
            for row in db.execute(
                select(Disposal.tax_year).where(Disposal.user_id == account_id)
            ).all()
        },
        reverse=True,
    )
    selected_year = year if (year in years) else (years[0] if years else None)

    report = carryover = None
    net_position: list = []
    if selected_year is not None:
        report = K4ReportGenerator(db, account_id).generate(selected_year)
        carryover = GavCarryoverReport(db, account_id).generate(selected_year)
        net_position = NetPositionReport(db, account_id).generate(selected_year)

    return templates.TemplateResponse(
        request,
        "share_view.html",
        {
            "token": token,
            "label": link.label,
            "years": years,
            "year": selected_year,
            "report": report,
            "carryover": carryover,
            "net_position": net_position,
            "expires_at": link.expires_at,
        },
    )
