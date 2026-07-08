"""Per-tax-year pages: K4 summary, transactions, T2, transfers, downloads."""

import io
import logging
import tempfile
from datetime import UTC
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.reports.audit import AuditExport
from kryptoskatt.reports.gav_history import GavHistoryReport
from kryptoskatt.reports.issues import FlaggedIssuesGenerator
from kryptoskatt.reports.k4 import K4ReportGenerator
from kryptoskatt.reports.net_position import NetPositionReport
from kryptoskatt.reports.t2 import T2IncomeReport
from kryptoskatt.web.deps import get_current_account_for_html, get_db
from kryptoskatt.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/year/{year}", response_class=HTMLResponse)
def year_summary(
    request: Request,
    year: int,
    show_hidden: int = 0,
    blacklisted: str = "",
    sru_error: str = "",
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """K4 summary for a given year."""
    from kryptoskatt.models.coin_blacklist import CoinBlacklist
    user_id = account.id

    report_generator = K4ReportGenerator(db, user_id)
    report = report_generator.generate(year)

    # Blacklist symbols stored uppercase; compare case-insensitively
    blacklist_symbols = {
        row.coin_symbol.upper()
        for row in db.query(CoinBlacklist).filter(CoinBlacklist.user_id == user_id).all()
    }

    all_net = NetPositionReport(db, user_id).generate(year)
    if show_hidden:
        net_position = all_net
    else:
        net_position = [row for row in all_net if row.coin.upper() not in blacklist_symbols]
    hidden_count = len([r for r in all_net if r.coin.upper() in blacklist_symbols])

    # Map the SRU error code (never user input) to a display message
    _sru_error_messages = {
        "pnr": "Personnummer måste anges med 12 siffror (ÅÅÅÅMMDDNNNN).",
        "empty": f"Inga avyttringar att redovisa för {year}.",
    }
    sru_error_message = _sru_error_messages.get(sru_error, "")

    return templates.TemplateResponse(
        request,
        "year_summary.html",
        {
            "year": year,
            "report": report,
            "net_position": net_position,
            "blacklist_symbols": blacklist_symbols,
            "show_hidden": bool(show_hidden),
            "hidden_count": hidden_count,
            "flash": blacklisted,
            "sru_error": sru_error_message,
            "account": account,
        },
    )


@router.get("/year/{year}/net-position", response_class=HTMLResponse)
def net_position_page(
    request: Request,
    year: int,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Dedicated net position page: GAV holdings + unpriced coins for a year."""
    from sqlalchemy import text as sa_text

    from kryptoskatt.models.gav_ledger import GavLedger

    user_id = account.id

    # Latest GavLedger entry per coin for this user where holdings are non-zero.
    # Using a correlated subquery for portability (SQLite + PostgreSQL).
    latest_ids = db.execute(
        sa_text(
            "SELECT id FROM gav_ledger g1"
            " WHERE user_id = :uid"
            "   AND total_amount > 0"
            "   AND id = ("
            "       SELECT id FROM gav_ledger g2"
            "       WHERE g2.user_id = g1.user_id AND g2.coin = g1.coin"
            "       ORDER BY timestamp DESC, id DESC LIMIT 1"
            "   )"
        ),
        {"uid": user_id},
    ).fetchall()

    gav_row_ids = [row[0] for row in latest_ids]
    gav_rows = (
        db.query(GavLedger)
        .filter(GavLedger.id.in_(gav_row_ids))
        .order_by(GavLedger.coin)
        .all()
    ) if gav_row_ids else []

    net_position = NetPositionReport(db, user_id).generate(year)

    return templates.TemplateResponse(
        request,
        "net_position.html",
        {
            "year": year,
            "gav_rows": gav_rows,
            "net_position": net_position,
            "account": account,
        },
    )


@router.get("/year/{year}/carryover", response_class=HTMLResponse)
def carryover_page(
    request: Request,
    year: int,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Year-to-year GAV carryover: opening vs closing holdings per coin."""
    from kryptoskatt.reports.gav_carryover import GavCarryoverReport

    report = GavCarryoverReport(db, account.id).generate(year)
    return templates.TemplateResponse(
        request,
        "carryover.html",
        {"year": year, "report": report, "account": account},
    )


@router.get("/year/{year}/download/carryover")
def download_carryover(
    year: int,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Download the GAV carryover table as CSV."""
    from kryptoskatt.reports.gav_carryover import GavCarryoverReport

    report = GavCarryoverReport(db, account.id).generate(year)
    headers = [
        "Tillgång", "Ingående antal", "Ingående omkostnad SEK", "Ingående GAV SEK",
        "Utgående antal", "Utgående omkostnad SEK", "Utgående GAV SEK",
        "Förändring antal", "Förändring omkostnad SEK",
    ]
    lines = [",".join(headers)]
    for r in report.rows:
        lines.append(
            f"{r.coin},{r.opening_units},{r.opening_cost_sek},{r.opening_gav_sek},"
            f"{r.closing_units},{r.closing_cost_sek},{r.closing_gav_sek},"
            f"{r.units_delta},{r.cost_delta_sek}"
        )
    lines.append(f"TOTALT,,{report.opening_total_cost_sek},,,{report.closing_total_cost_sek},,,")
    content = "\n".join(lines)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="gav_carryover_{year}.csv"'},
    )


@router.get("/year/{year}/transactions", response_class=HTMLResponse)
def transactions(
    request: Request,
    year: int,
    page: int = 1,
    coin: str = "",
    event_type: str = "",
    platform: str = "",
    duplicates: str = "all",  # "all" | "yes" | "no"
    sort: str = "date_desc",  # date_desc | date_asc | amount_desc | amount_asc | coin_asc | coin_desc
    q: str = "",
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Paginated raw transaction list for a given year with filtering and sorting."""
    from sqlalchemy import extract, or_

    from kryptoskatt.enums import EventType

    user_id = account.id
    page_size = 100

    base_filter = [
        Transaction.user_id == user_id,
        extract("year", Transaction.timestamp_utc) == year,
    ]
    if coin:
        base_filter.append(Transaction.base_coin == coin.upper())
    if event_type:
        base_filter.append(Transaction.event_type == event_type.upper())
    if platform:
        base_filter.append(Transaction.source_platform == platform)
    if duplicates == "yes":
        base_filter.append(Transaction.is_duplicate.is_(True))
    elif duplicates == "no":
        base_filter.append(Transaction.is_duplicate.is_(False))
    if q.strip():
        term = f"%{q.strip()}%"
        base_filter.append(or_(
            Transaction.tx_hash.ilike(term),
            Transaction.from_address.ilike(term),
            Transaction.to_address.ilike(term),
            Transaction.base_coin.ilike(term),
        ))

    _sort_map = {
        "date_desc": Transaction.timestamp_utc.desc(),
        "date_asc": Transaction.timestamp_utc.asc(),
        "amount_desc": Transaction.base_amount.desc(),
        "amount_asc": Transaction.base_amount.asc(),
        "coin_asc": Transaction.base_coin.asc(),
        "coin_desc": Transaction.base_coin.desc(),
    }
    order_col = _sort_map.get(sort, Transaction.timestamp_utc.desc())

    count_stmt = select(func.count(Transaction.id)).where(*base_filter)
    total_count = db.execute(count_stmt).scalar() or 0

    offset = (page - 1) * page_size
    stmt = (
        select(Transaction)
        .where(*base_filter)
        .order_by(order_col)
        .offset(offset)
        .limit(page_size)
    )
    txs = db.execute(stmt).scalars().all()

    has_next = (offset + page_size) < total_count

    year_filter = [
        Transaction.user_id == user_id,
        extract("year", Transaction.timestamp_utc) == year,
    ]

    # Distinct coins for the filter dropdown
    available_coins = (
        db.execute(
            select(Transaction.base_coin).where(*year_filter).distinct().order_by(Transaction.base_coin)
        )
        .scalars()
        .all()
    )

    # Distinct platforms for the filter dropdown
    available_platforms = (
        db.execute(
            select(Transaction.source_platform)
            .where(*year_filter, Transaction.source_platform.isnot(None))
            .distinct()
            .order_by(Transaction.source_platform)
        )
        .scalars()
        .all()
    )

    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "year": year,
            "coin": coin,
            "event_type": event_type,
            "platform": platform,
            "duplicates": duplicates,
            "sort": sort,
            "q": q,
            "transactions": txs,
            "total_count": total_count,
            "page": page,
            "has_next": has_next,
            "account": account,
            "available_coins": available_coins,
            "available_platforms": available_platforms,
            "event_types": [e.value for e in EventType],
        },
    )


@router.get("/year/{year}/download/csv")
def download_csv(year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Download K4 report as CSV."""
    report_generator = K4ReportGenerator(db, account.id)
    report = report_generator.generate(year)

    # Write to a private temporary file (unique per request, not guessable)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        K4ReportGenerator.export_csv(report, temp_path)
        content = temp_path.read_text(encoding="utf-8-sig")
    finally:
        temp_path.unlink(missing_ok=True)

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="k4_{year}.csv"'},
    )


@router.get("/year/{year}/download/json")
def download_json(year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Download K4 report as JSON."""
    report_generator = K4ReportGenerator(db, account.id)
    report = report_generator.generate(year)

    # Write to a private temporary file (unique per request, not guessable)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        K4ReportGenerator.export_json(report, temp_path)
        content = temp_path.read_text(encoding="utf-8")
    finally:
        temp_path.unlink(missing_ok=True)

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="k4_{year}.json"'},
    )


@router.post("/year/{year}/download/sru")
def download_sru(
    year: int,
    personnummer: str = Form(...),
    namn: str = Form(...),
    postnummer: str = Form(""),
    postort: str = Form(""),
    adress: str = Form(""),
    epost: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Download K4 as Skatteverket SRU files (INFO.SRU + BLANKETTER.SRU) in a ZIP."""
    import zipfile

    from kryptoskatt.reports.sru import SRU_ENCODING, K4SruGenerator, SruTaxpayer

    taxpayer = SruTaxpayer(
        personnummer=personnummer.strip(),
        namn=namn.strip(),
        postnummer=postnummer.strip(),
        postort=postort.strip(),
        adress=adress.strip(),
        epost=epost.strip(),
    )
    try:
        export = K4SruGenerator(db, account.id).generate(year, taxpayer)
    except ValueError as e:
        # Redirect with a fixed error CODE only — never reflect the submitted
        # personnummer/name into the URL (open-redirect surface + it would leak
        # personal data into browser history and server logs). year is a
        # validated int path param; re-cast to int as a belt-and-braces sanitizer.
        code = "pnr" if "Personnummer" in str(e) else "empty"
        return RedirectResponse(f"/year/{int(year)}?sru_error={code}", status_code=303)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("INFO.SRU", export.info_sru.encode(SRU_ENCODING))
        zf.writestr("BLANKETTER.SRU", export.blanketter_sru.encode(SRU_ENCODING))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="k4_sru_{year}.zip"'},
    )


@router.get("/year/{year}/audit", response_class=HTMLResponse)
def audit_view(request: Request, year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Full transaction audit trail for a year — HTML view with clickable explorer links."""
    exporter = AuditExport(db, account.id)
    rows = exporter.generate(year)
    return templates.TemplateResponse(
        request,
        "audit.html",
        {"year": year, "rows": rows, "account": account},
    )


@router.get("/year/{year}/download/audit")
def download_audit(year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Download full transaction audit trail as CSV."""
    exporter = AuditExport(db, account.id)
    content = exporter.export_csv(year)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="transaktioner_{year}.csv"'},
    )


@router.get("/year/{year}/download/k4-html")
def download_k4_html(request: Request, year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Download K4 summary + K4-Avyttring transaction log as self-contained HTML."""
    from datetime import datetime

    uid = account.id
    k4_report = K4ReportGenerator(db, uid).generate(year)
    all_audit = AuditExport(db, uid).generate(year)
    disposal_rows = [r for r in all_audit if r.rapport == "K4-Avyttring"]
    acquisition_rows = [r for r in all_audit if r.rapport == "K4-Anskaffning"]

    from decimal import Decimal
    total_proceeds = sum((r.proceeds_sek for r in k4_report.rows), Decimal("0"))
    total_cost = sum((r.cost_basis_sek for r in k4_report.rows), Decimal("0"))
    net = total_proceeds - total_cost

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    html = templates.get_template("export_k4.html").render(
        year=year,
        k4_rows=k4_report.rows,
        disposal_rows=disposal_rows,
        acquisition_rows=acquisition_rows,
        total_proceeds=total_proceeds.quantize(Decimal("0.01")),
        total_cost=total_cost.quantize(Decimal("0.01")),
        net=net.quantize(Decimal("0.01")),
        generated_at=generated_at,
    )
    return StreamingResponse(
        io.BytesIO(html.encode("utf-8")),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="k4_underlag_{year}.html"'},
    )


@router.get("/year/{year}/download/t2-html")
def download_t2_html(request: Request, year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Download T2 summary + per-transaction detail as self-contained HTML."""
    from datetime import datetime

    uid = account.id
    t2_report = T2IncomeReport(db, uid).generate(year)
    all_audit = AuditExport(db, uid).generate(year)
    income_detail = [r for r in all_audit if r.rapport == "T2-Intäkt"]
    cost_detail = [r for r in all_audit if r.rapport == "T2-Kostnad"]

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    html = templates.get_template("export_t2.html").render(
        year=year,
        report=t2_report,
        income_detail=income_detail,
        cost_detail=cost_detail,
        generated_at=generated_at,
    )
    return StreamingResponse(
        io.BytesIO(html.encode("utf-8")),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="t2_underlag_{year}.html"'},
    )


@router.post("/year/{year}/t2/manual-cost/add")
async def t2_manual_cost_add(
    year: int,
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Add a manual fiat cost entry to Bilaga T2."""
    from datetime import date as date_type

    from kryptoskatt.models.t2_manual_entry import T2ManualEntry

    form = await request.form()
    description = (form.get("description") or "").strip()
    amount_str = (form.get("amount_sek") or "").strip().replace(",", ".")
    vendor = (form.get("vendor") or "").strip()
    date_str = (form.get("entry_date") or "").strip()

    if not description or not amount_str:
        return RedirectResponse(f"/year/{year}/t2?error=Beskrivning+och+belopp+krävs", status_code=303)

    try:
        from decimal import Decimal
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError("amount must be positive")
    except Exception:
        return RedirectResponse(f"/year/{year}/t2?error=Ogiltigt+belopp", status_code=303)

    entry_date = None
    if date_str:
        try:
            entry_date = date_type.fromisoformat(date_str)
        except ValueError:
            pass

    db.add(T2ManualEntry(
        user_id=account.id,
        tax_year=year,
        entry_date=entry_date,
        description=description,
        amount_sek=amount,
        vendor=vendor or None,
    ))
    db.commit()
    return RedirectResponse(f"/year/{year}/t2", status_code=303)


@router.post("/year/{year}/t2/manual-cost/delete")
async def t2_manual_cost_delete(
    year: int,
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Delete a manual fiat cost entry from Bilaga T2."""
    from kryptoskatt.models.t2_manual_entry import T2ManualEntry

    form = await request.form()
    entry_id = int(form.get("entry_id") or 0)
    entry = db.query(T2ManualEntry).filter(
        T2ManualEntry.id == entry_id,
        T2ManualEntry.tax_year == year,
        T2ManualEntry.user_id == account.id,
    ).first()
    if entry:
        db.delete(entry)
        db.commit()
    return RedirectResponse(f"/year/{year}/t2", status_code=303)


@router.post("/year/{year}/blacklist-coin")
def blacklist_coin_from_year(
    year: int,
    coin: str = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Blacklist a coin directly from the year summary page."""
    from sqlalchemy import func as sqlfunc

    from kryptoskatt.models.coin_blacklist import CoinBlacklist

    symbol = coin.strip()
    symbol_upper = symbol.upper()
    existing = db.query(CoinBlacklist).filter(
        CoinBlacklist.user_id == account.id,
        sqlfunc.upper(CoinBlacklist.coin_symbol) == symbol_upper,
    ).first()
    if not existing:
        db.add(CoinBlacklist(user_id=account.id, coin_symbol=symbol, reason="Markerad som spam från årsvy"))
        db.commit()
    return RedirectResponse(f"/year/{year}?blacklisted={symbol[:30]}", status_code=303)


@router.post("/year/{year}/unblacklist-coin")
def unblacklist_coin_from_year(
    year: int,
    coin: str = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Remove a coin from the blacklist from the year summary page."""
    from sqlalchemy import func as sqlfunc

    from kryptoskatt.models.coin_blacklist import CoinBlacklist

    symbol_upper = coin.strip().upper()
    entry = db.query(CoinBlacklist).filter(
        CoinBlacklist.user_id == account.id,
        sqlfunc.upper(CoinBlacklist.coin_symbol) == symbol_upper,
    ).first()
    if entry:
        db.delete(entry)
        db.commit()
    return RedirectResponse(f"/year/{year}?show_hidden=1", status_code=303)


@router.get("/year/{year}/t2", response_class=HTMLResponse)
def t2_report(
    request: Request,
    year: int,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
    result: str = "",
):
    """Bilaga T2 income report (mining, DePIN rewards) for a given year."""
    from kryptoskatt.models.t2_manual_income_entry import T2_INCOME_CATEGORIES, T2ManualIncomeEntry

    report = T2IncomeReport(db, account.id).generate(year)
    manual_income = (
        db.query(T2ManualIncomeEntry)
        .filter(T2ManualIncomeEntry.user_id == account.id, T2ManualIncomeEntry.tax_year == year)
        .order_by(T2ManualIncomeEntry.entry_date, T2ManualIncomeEntry.id)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "t2.html",
        {
            "year": year,
            "report": report,
            "manual_income": manual_income,
            "income_categories": T2_INCOME_CATEGORIES,
            "account": account,
            "result": result,
        },
    )


@router.post("/year/{year}/t2/manual-income/add")
async def t2_manual_income_add(
    year: int,
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Add a manual income entry to Bilaga T2."""
    from datetime import date as date_type

    from kryptoskatt.models.t2_manual_income_entry import T2ManualIncomeEntry

    form = await request.form()
    description = (form.get("description") or "").strip()
    amount_str = (form.get("amount_sek") or "").strip().replace(",", ".")
    category = (form.get("category") or "REWARD").strip().upper()
    source = (form.get("source") or "").strip()
    date_str = (form.get("entry_date") or "").strip()

    if not description or not amount_str:
        return RedirectResponse(
            f"/year/{year}/t2?result=error:Beskrivning+och+belopp+krävs", status_code=303
        )

    try:
        from decimal import Decimal

        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError("amount must be positive")
    except Exception:
        return RedirectResponse(f"/year/{year}/t2?result=error:Ogiltigt+belopp", status_code=303)

    entry_date = None
    if date_str:
        try:
            entry_date = date_type.fromisoformat(date_str)
        except ValueError:
            pass

    db.add(
        T2ManualIncomeEntry(
            user_id=account.id,
            tax_year=year,
            entry_date=entry_date,
            category=category,
            description=description,
            amount_sek=amount,
            source=source or None,
        )
    )
    db.commit()
    return RedirectResponse(f"/year/{year}/t2", status_code=303)


@router.post("/year/{year}/t2/manual-income/delete")
async def t2_manual_income_delete(
    year: int,
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Delete a manual T2 income entry."""
    from kryptoskatt.models.t2_manual_income_entry import T2ManualIncomeEntry

    form = await request.form()
    entry_id = int(form.get("entry_id") or 0)
    entry = db.query(T2ManualIncomeEntry).filter(
        T2ManualIncomeEntry.id == entry_id,
        T2ManualIncomeEntry.tax_year == year,
        T2ManualIncomeEntry.user_id == account.id,
    ).first()
    if entry:
        db.delete(entry)
        db.commit()
    return RedirectResponse(f"/year/{year}/t2", status_code=303)


@router.get("/year/{year}/gav/{coin}", response_class=HTMLResponse)
def gav_history(request: Request, year: int, coin: str, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """GAV history for a specific coin."""
    report_generator = GavHistoryReport(db, account.id)
    snapshots = report_generator.generate(coin=coin, year=year)
    return templates.TemplateResponse(
        request,
        "gav_history.html",
        {"request": request, "year": year, "coin": coin, "snapshots": snapshots, "account": account},
    )


@router.get("/year/{year}/issues", response_class=HTMLResponse)
def issues(request: Request, year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Flagged issues for a given year."""
    report_generator = FlaggedIssuesGenerator(db, account.id)
    issues_report = report_generator.generate(year=year)
    return templates.TemplateResponse(
        request,
        "issues.html",
        {"year": year, "issues_report": issues_report, "account": account},
    )


@router.get("/year/{year}/transfers", response_class=HTMLResponse)
def transfers_page(
    request: Request,
    year: int,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Show matched and unmatched transfers for a given year."""
    from dataclasses import dataclass

    from kryptoskatt.enums import EventType
    from kryptoskatt.models.transfer_link import TransferLink

    user_id = account.id

    # All TRANSFER_OUT for the year (non-duplicate)
    transfer_outs = (
        db.query(Transaction)
        .filter(
            Transaction.user_id == user_id,
            Transaction.event_type == EventType.TRANSFER_OUT,
            Transaction.is_duplicate == False,  # noqa: E712
            extract("year", Transaction.timestamp_utc) == year,
        )
        .order_by(Transaction.timestamp_utc)
        .all()
    )

    tx_out_ids = {tx.id for tx in transfer_outs}

    # Links whose tx_out is among these transactions
    links_by_tx_out: dict[int, TransferLink] = {}
    if tx_out_ids:
        for link in db.query(TransferLink).filter(TransferLink.tx_out_id.in_(tx_out_ids)).all():
            links_by_tx_out[link.tx_out_id] = link

    @dataclass
    class TransferPair:
        tx_out: Transaction
        link: TransferLink

    matched_pairs = [
        TransferPair(tx_out=tx, link=links_by_tx_out[tx.id])
        for tx in transfer_outs
        if tx.id in links_by_tx_out
    ]
    unmatched_outs = [tx for tx in transfer_outs if tx.id not in links_by_tx_out]

    return templates.TemplateResponse(
        request,
        "transfers.html",
        {
            "year": year,
            "matched_pairs": matched_pairs,
            "unmatched_outs": unmatched_outs,
            "account": account,
        },
    )


@router.post("/year/{year}/transfers/match", response_class=HTMLResponse)
def match_transfer_manually(
    year: int,
    tx_out_id: int = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Manually mark a TRANSFER_OUT as matched (creates an address-registry link)."""
    from kryptoskatt.enums import EventType
    from kryptoskatt.models.transfer_link import TransferLink

    user_id = account.id
    tx_out = (
        db.query(Transaction)
        .filter(
            Transaction.id == tx_out_id,
            Transaction.user_id == user_id,
            Transaction.event_type == EventType.TRANSFER_OUT,
        )
        .first()
    )
    if tx_out is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Idempotent: only create link if not already linked
    existing = db.query(TransferLink).filter(TransferLink.tx_out_id == tx_out_id).first()
    if not existing:
        link = TransferLink(
            tx_out_id=tx_out_id,
            tx_in_id=None,
            match_method="MANUAL",
            confidence=None,
        )
        db.add(link)
        db.commit()

    return RedirectResponse(url=f"/year/{year}/transfers", status_code=303)

