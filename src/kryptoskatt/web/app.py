"""FastAPI web application for KryptoSkatt."""

import io
import json
import logging
import tempfile
from pathlib import Path
from typing import Generator

from fastapi import FastAPI, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from kryptoskatt.chains import get_registry
from kryptoskatt.cli.fetch_cmd import create_import_batch_for_fetch, save_fetched_transactions
from kryptoskatt.cli.import_cmd import detect_platform, parse_file, create_import_batch, save_transactions
from kryptoskatt.config import settings
from kryptoskatt.db import get_session
from kryptoskatt.services.price import PriceService
from kryptoskatt.engine.dedup import DeduplicationEngine
from kryptoskatt.engine.gav import GavEngine
from kryptoskatt.engine.price_enrichment import PriceEnrichmentEngine
from kryptoskatt.engine.transfers import TransferMatcher
from kryptoskatt.enums import Chain
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.wallet import Wallet
from kryptoskatt.reports.k4 import K4ReportGenerator
from kryptoskatt.reports.gav_history import GavHistoryReport
from kryptoskatt.reports.issues import FlaggedIssuesGenerator
from kryptoskatt.reports.audit import AuditExport
from kryptoskatt.reports.net_position import NetPositionReport
from kryptoskatt.reports.t2 import T2IncomeReport
from kryptoskatt.services.price_history_importer import PriceHistoryImporter
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.wallet import WalletService

# Which API key is required per chain
_CHAIN_API_KEY_NAMES: dict[Chain, str] = {
    Chain.ETHEREUM: "ETHERSCAN_API_KEY",
    Chain.POLYGON: "ETHERSCAN_API_KEY",
    Chain.BNB: "ETHERSCAN_API_KEY",
    Chain.SOLANA: "HELIUS_API_KEY",
}

_CHAIN_API_KEYS: dict[Chain, str] = {
    Chain.ETHEREUM: settings.etherscan_api_key,
    Chain.POLYGON: settings.etherscan_api_key,
    Chain.BNB: settings.etherscan_api_key,
    Chain.SOLANA: settings.helius_api_key,
}

logger = logging.getLogger(__name__)


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

    net_position = NetPositionReport(db).generate(year)

    return templates.TemplateResponse(
        request,
        "year_summary.html",
        {"year": year, "report": report, "net_position": net_position},
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


@app.get("/year/{year}/audit", response_class=HTMLResponse)
def audit_view(request: Request, year: int, db: Session = Depends(get_db)):
    """Full transaction audit trail for a year — HTML view with clickable explorer links."""
    exporter = AuditExport(db)
    rows = exporter.generate(year)
    return templates.TemplateResponse(
        request,
        "audit.html",
        {"year": year, "rows": rows},
    )


@app.get("/year/{year}/download/audit")
def download_audit(year: int, db: Session = Depends(get_db)):
    """Download full transaction audit trail as CSV."""
    exporter = AuditExport(db)
    content = exporter.export_csv(year)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="transaktioner_{year}.csv"'},
    )


@app.get("/year/{year}/t2", response_class=HTMLResponse)
def t2_report(request: Request, year: int, db: Session = Depends(get_db)):
    """Bilaga T2 income report (mining, DePIN rewards) for a given year."""
    report = T2IncomeReport(db).generate(year)
    return templates.TemplateResponse(request, "t2.html", {"year": year, "report": report})


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


@app.get("/addresses", response_class=HTMLResponse)
def unknown_addresses(request: Request, result: str = "", db: Session = Depends(get_db)):
    """List unknown TRANSFER_IN senders and TRANSFER_OUT recipients."""
    # Known addresses (registered wallets)
    known = {w.address for w in db.query(Wallet).all()}

    # Helper to aggregate address stats from a query result
    def _aggregate(rows):
        agg: dict[str, dict] = {}
        for address, coin, ts in rows:
            if not address or address in known:
                continue
            if address not in agg:
                agg[address] = {"coins": set(), "tx_count": 0, "latest": ts}
            agg[address]["coins"].add(coin)
            agg[address]["tx_count"] += 1
            if ts and (agg[address]["latest"] is None or ts > agg[address]["latest"]):
                agg[address]["latest"] = ts
        result = []
        for addr, data in sorted(agg.items(), key=lambda x: -x[1]["tx_count"]):
            result.append({
                "address": addr,
                "coins": ", ".join(sorted(data["coins"])),
                "tx_count": data["tx_count"],
                "latest_date": data["latest"].date() if data["latest"] else "",
            })
        return result

    from kryptoskatt.enums import EventType

    sender_rows = (
        db.query(Transaction.from_address, Transaction.base_coin, Transaction.timestamp_utc)
        .filter(
            Transaction.event_type == EventType.TRANSFER_IN.value,
            Transaction.is_duplicate.is_(False),
            Transaction.from_address.isnot(None),
        )
        .all()
    )
    recipient_rows = (
        db.query(Transaction.to_address, Transaction.base_coin, Transaction.timestamp_utc)
        .filter(
            Transaction.event_type == EventType.TRANSFER_OUT.value,
            Transaction.is_duplicate.is_(False),
            Transaction.to_address.isnot(None),
        )
        .all()
    )

    chains = [c.value for c in Chain if c != Chain.UNKNOWN]

    return templates.TemplateResponse(
        request,
        "addresses.html",
        {
            "result": result,
            "unknown_senders": _aggregate(sender_rows),
            "unknown_recipients": _aggregate(recipient_rows),
            "chains": chains,
        },
    )


@app.post("/addresses/register")
def register_address(
    address: str = Form(...),
    chain: str = Form(...),
    label: str = Form(""),
    category: str = Form("own"),
    result_url: str = Form("/addresses"),
    db: Session = Depends(get_db),
):
    """Register an unknown address as a wallet."""
    try:
        service = WalletService(db)
        wallet = service.add_wallet(
            WalletCreate(address=address, chain=chain, label=label, is_mine=(category == "own"), category=category)
        )
        msg = f"ok:Registrerade {wallet.address[:20]}... som {category}"
    except ValueError as e:
        msg = f"error:{e}"
    except Exception as e:
        logger.exception("Address register failed")
        msg = f"error:Fel: {e}"

    return RedirectResponse(f"{result_url}?result={msg}", status_code=303)


@app.get("/actions", response_class=HTMLResponse)
def actions_dashboard(request: Request, result: str = "", db: Session = Depends(get_db)):
    """Actions dashboard for import, fetch, calculate, and wallet management."""
    wallet_service = WalletService(db)
    wallets = wallet_service.list_wallets()
    chains = [c.value for c in Chain if c != Chain.UNKNOWN]
    return templates.TemplateResponse(
        request,
        "actions.html",
        {"result": result, "wallets": wallets, "chains": chains},
    )


@app.post("/actions/import")
async def actions_import(
    file: UploadFile = File(...),
    platform: str = Form("auto"),
    db: Session = Depends(get_db),
):
    """Import transactions from uploaded file."""
    try:
        suffix = Path(file.filename or "upload.csv").suffix or ".csv"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = Path(tmp.name)

        try:
            # Auto-detect platform if requested
            resolved_platform = platform
            if platform == "auto":
                with open(tmp_path, encoding="utf-8") as f:
                    lines = [f.readline() for _ in range(10)]
                resolved_platform = detect_platform(tmp_path, lines)

            transactions, errors = parse_file(tmp_path, resolved_platform)
        finally:
            tmp_path.unlink(missing_ok=True)

        batch = create_import_batch(
            db, resolved_platform, file.filename or "upload", len(transactions), len(errors)
        )
        saved = save_transactions(db, transactions, batch)
        msg = f"ok:Importerade {saved} transaktioner från {file.filename} (plattform: {resolved_platform})"
        if errors:
            msg += f" — {len(errors)} fel"
    except Exception as e:
        logger.exception("Import failed")
        msg = f"error:Importfel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/fetch")
def actions_fetch(
    address: str = Form(...),
    chain: str = Form(...),
    db: Session = Depends(get_db),
):
    """Fetch transactions from blockchain for a given address."""
    try:
        chain_enum = Chain(chain.upper())

        # Check API key before attempting fetch
        api_key = _CHAIN_API_KEYS.get(chain_enum, "")
        if not api_key:
            key_name = _CHAIN_API_KEY_NAMES.get(chain_enum, "API-nyckel")
            return RedirectResponse(
                f"/actions?result=error:Saknar {key_name} i .env — lägg till den och starta om",
                status_code=303,
            )

        registry = get_registry()
        adapter = registry.get_adapter(chain_enum)
        if adapter is None:
            return RedirectResponse(f"/actions?result=error:Ingen adapter för {chain}", status_code=303)

        txs = adapter.fetch_transactions(address, chain_enum)
        if not txs:
            msg = f"error:Inga transaktioner hittades för {address[:20]}... på {chain} — kontrollera adressen"
        else:
            batch = create_import_batch_for_fetch(db, 1, len(txs))
            saved, skipped = save_fetched_transactions(db, txs, batch)
            msg = f"ok:Hämtade {saved} nya transaktioner för {address[:20]}... på {chain}"
            if skipped:
                msg += f" ({skipped} redan importerade hoppades över)"
    except ValueError:
        msg = f"error:Okänd kedja: {chain}"
    except Exception as e:
        logger.exception("Fetch failed")
        msg = f"error:Hämtningsfel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/refetch")
def actions_refetch(
    address: str = Form(...),
    chain: str = Form(...),
    db: Session = Depends(get_db),
):
    """Delete all existing transactions fetched from an address, then re-fetch.

    Useful when the chain adapter has been improved and old records were parsed
    incorrectly (wrong from/to addresses, wrong event_type, etc.).
    Deletes rows where from_address OR to_address matches the given address
    and source_platform matches the chain adapter.
    """
    try:
        chain_enum = Chain(chain.upper())
        api_key = _CHAIN_API_KEYS.get(chain_enum, "")
        if not api_key:
            key_name = _CHAIN_API_KEY_NAMES.get(chain_enum, "API-nyckel")
            return RedirectResponse(
                f"/actions?result=error:Saknar {key_name} i .env",
                status_code=303,
            )

        registry = get_registry()
        adapter = registry.get_adapter(chain_enum)
        if adapter is None:
            return RedirectResponse(f"/actions?result=error:Ingen adapter för {chain}", status_code=303)

        # Determine which source_platform tags were used for this chain
        platform_tags = {"helius", "solscan"} if chain_enum == Chain.SOLANA else {"etherscan"}

        # Find transactions to delete
        tx_ids_to_delete = [
            row.id for row in db.query(Transaction.id).filter(
                Transaction.source_platform.in_(platform_tags),
                (Transaction.from_address == address) | (Transaction.to_address == address),
            ).all()
        ]

        if tx_ids_to_delete:
            from kryptoskatt.models.transfer_link import TransferLink
            # Remove transfer_links referencing these transactions first (FK constraint)
            db.query(TransferLink).filter(
                (TransferLink.tx_out_id.in_(tx_ids_to_delete)) |
                (TransferLink.tx_in_id.in_(tx_ids_to_delete))
            ).delete(synchronize_session=False)
            deleted = db.query(Transaction).filter(
                Transaction.id.in_(tx_ids_to_delete)
            ).delete(synchronize_session=False)
        else:
            deleted = 0

        db.commit()

        txs = adapter.fetch_transactions(address, chain_enum)
        if not txs:
            msg = f"ok:Raderade {deleted} gamla rader. Inga nya transaktioner hittades."
        else:
            batch = create_import_batch_for_fetch(db, 1, len(txs))
            saved, skipped = save_fetched_transactions(db, txs, batch)
            msg = (
                f"ok:Rensade {deleted} gamla rader och importerade {saved} nya "
                f"transaktioner för {address[:20]}… på {chain}"
            )
            if skipped:
                msg += f" ({skipped} dubbletter hoppades över)"
    except ValueError:
        msg = f"error:Okänd kedja: {chain}"
    except Exception as e:
        logger.exception("Refetch failed")
        msg = f"error:Hämtningsfel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/fetch-all")
def actions_fetch_all(db: Session = Depends(get_db)):
    """Fetch transactions for all registered wallets across all networks."""
    wallet_service = WalletService(db)
    wallets = wallet_service.list_wallets(mine_only=True)

    if not wallets:
        return RedirectResponse(
            "/actions?result=error:Inga plånböcker registrerade — lägg till adresser först",
            status_code=303,
        )

    registry = get_registry()
    total_saved = 0
    total_skipped = 0
    errors: list[str] = []

    for wallet in wallets:
        try:
            chain_enum = Chain(wallet.chain)
        except ValueError:
            errors.append(f"{wallet.address[:12]}…: okänd kedja {wallet.chain}")
            continue

        api_key = _CHAIN_API_KEYS.get(chain_enum, "")
        if not api_key:
            key_name = _CHAIN_API_KEY_NAMES.get(chain_enum, "API-nyckel")
            errors.append(f"{wallet.chain}: saknar {key_name}")
            continue

        adapter = registry.get_adapter(chain_enum)
        if adapter is None:
            errors.append(f"{wallet.chain}: ingen adapter")
            continue

        try:
            txs = adapter.fetch_transactions(wallet.address, chain_enum)
            if txs:
                batch = create_import_batch_for_fetch(db, 1, len(txs))
                saved, skipped = save_fetched_transactions(db, txs, batch)
                total_saved += saved
                total_skipped += skipped
                logger.info(
                    "Fetched %s on %s: %d new, %d skipped",
                    wallet.address[:20], wallet.chain, saved, skipped,
                )
        except Exception as e:
            logger.exception("Fetch failed for %s on %s", wallet.address, wallet.chain)
            errors.append(f"{wallet.address[:12]}… på {wallet.chain}: {e}")

    msg = f"ok:Hämtade {total_saved} nya transaktioner från {len(wallets)} plånböcker"
    if total_skipped:
        msg += f" ({total_skipped} redan importerade hoppades över)"
    if errors:
        msg += " — fel: " + "; ".join(errors[:3])
        if len(errors) > 3:
            msg += f" (+{len(errors) - 3} till)"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/calculate")
def actions_calculate(
    year: int = Form(...),
    db: Session = Depends(get_db),
):
    """Run dedup + transfer matching + GAV calculation for a year."""
    try:
        dedup_engine = DeduplicationEngine(db)
        dedup_engine.deduplicate_all()

        enrich = PriceEnrichmentEngine(db)
        enrich_report = enrich.enrich()

        wallet_service = WalletService(db)
        my_addresses = wallet_service.get_my_addresses()
        transfer_matcher = TransferMatcher(db, my_addresses)
        transfer_matcher.match_all()

        gav_engine = GavEngine(db)
        result = gav_engine.calculate(year=year)
        db.commit()

        msg = f"ok:Beräknade {len(result.disposals)} avyttringar för {year} ({enrich_report.enriched} priser hämtade)"
    except Exception as e:
        db.rollback()
        logger.exception("Calculate failed")
        msg = f"error:Beräkningsfel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/wallets/add")
def actions_wallet_add(
    address: str = Form(...),
    chain: str = Form(...),
    label: str = Form(""),
    category: str = Form("own"),
    db: Session = Depends(get_db),
):
    """Add a wallet via web form."""
    try:
        service = WalletService(db)
        # Only "own" wallets are mine — all other categories are external addresses
        is_mine = category == "own"
        wallet = service.add_wallet(
            WalletCreate(address=address, chain=chain, label=label, is_mine=is_mine, category=category)
        )
        msg = f"ok:Plånbok tillagd: {wallet.address[:20]}... på {wallet.chain}"
    except ValueError as e:
        msg = f"error:{e}"
    except Exception as e:
        logger.exception("Wallet add failed")
        msg = f"error:Fel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/wallets/bulk-add")
def actions_wallet_bulk_add(
    addresses: str = Form(...),
    chain: str = Form("ETHEREUM"),
    category: str = Form("own"),
    db: Session = Depends(get_db),
):
    """Add multiple wallets at once from a newline-separated list."""
    service = WalletService(db)
    is_mine = category == "own"
    added, skipped = 0, 0
    for line in addresses.splitlines():
        addr = line.strip()
        if not addr:
            continue
        try:
            service.add_wallet(WalletCreate(address=addr, chain=chain, label="", is_mine=is_mine, category=category))
            added += 1
        except Exception:
            skipped += 1
    msg = f"ok:Lade till {added} plånböcker" + (f", hoppade över {skipped} (redan finns?)" if skipped else "")
    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/wallets/remove")
def actions_wallet_remove(
    address: str = Form(...),
    chain: str = Form(""),
    db: Session = Depends(get_db),
):
    """Remove a wallet via web form."""
    try:
        service = WalletService(db)
        removed = service.remove_wallet(address, chain or None)
        if removed:
            msg = f"ok:Plånbok borttagen: {address[:20]}..."
        else:
            msg = f"error:Plånbok hittades inte: {address[:20]}..."
    except Exception as e:
        logger.exception("Wallet remove failed")
        msg = f"error:Fel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/prices/import-history")
def actions_import_price_history(db: Session = Depends(get_db)):
    """Import all CSV files from the configured PriceHistory directory."""
    from pathlib import Path
    history_dir = Path(settings.price_history_dir)
    if not history_dir.is_absolute():
        history_dir = Path.cwd() / history_dir

    if not history_dir.exists():
        return RedirectResponse(
            f"/actions?result=error:Katalogen {history_dir} hittades inte",
            status_code=303,
        )

    try:
        importer = PriceHistoryImporter(db)
        result = importer.import_directory(history_dir)
        msg = (
            f"ok:Importerade {result.rows_inserted} priser från {result.files_processed} filer"
            f" ({result.rows_skipped} redan i databasen, {result.usd_sek_dates_fetched} USD/SEK-kurser hämtade)"
        )
        if result.rows_failed:
            msg += f" — {result.rows_failed} rader saknade valutakurs"
        if result.errors:
            msg += " — " + "; ".join(result.errors[:2])
    except Exception as e:
        logger.exception("Price history import failed")
        msg = f"error:Importfel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/prices/upload")
async def actions_prices_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a CSV of manual prices: coin,date,price_sek.

    Format (with header row):
        coin,date,price_sek
        GEOD,2025-07-12,0.054
        BONO,2025-10-20,0.001

    Dates: YYYY-MM-DD. Price: SEK per unit (decimal point, not comma).
    """
    import csv
    from datetime import date as date_type
    from decimal import Decimal, InvalidOperation

    price_service = PriceService(db)
    saved = 0
    errors: list[str] = []

    try:
        content = (await file.read()).decode("utf-8-sig")
        reader = csv.DictReader(content.splitlines())

        for lineno, row in enumerate(reader, start=2):
            coin = (row.get("coin") or "").strip().upper()
            date_str = (row.get("date") or "").strip()
            price_str = (row.get("price_sek") or "").strip().replace(",", ".")

            if not coin or not date_str or not price_str:
                errors.append(f"Rad {lineno}: saknar coin/date/price_sek")
                continue

            try:
                price_date = date_type.fromisoformat(date_str)
            except ValueError:
                errors.append(f"Rad {lineno}: ogiltigt datum '{date_str}' (använd YYYY-MM-DD)")
                continue

            try:
                price = Decimal(price_str)
                if price < 0:
                    raise ValueError("negativt pris")
            except (InvalidOperation, ValueError):
                errors.append(f"Rad {lineno}: ogiltigt pris '{price_str}'")
                continue

            price_service.save_manual_price(coin, price_date, price)
            saved += 1

        msg = f"ok:Sparade {saved} manuella priser"
        if errors:
            msg += f" — {len(errors)} fel: " + "; ".join(errors[:3])
            if len(errors) > 3:
                msg += f" (+{len(errors) - 3} till)"
    except Exception as e:
        logger.exception("Price upload failed")
        msg = f"error:Uppladdningsfel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.get("/prices", response_class=HTMLResponse)
def prices_page(request: Request, db: Session = Depends(get_db)):
    """Show manual prices, CoinGecko-cached prices, and coin blacklist."""
    from kryptoskatt.models.price_cache import PriceCache
    from kryptoskatt.models.coin_blacklist import CoinBlacklist
    from kryptoskatt.enums import PriceSource

    manual = (
        db.query(PriceCache)
        .filter(PriceCache.source == PriceSource.MANUAL.value)
        .order_by(PriceCache.coin_id, PriceCache.date.desc())
        .all()
    )
    coingecko_summary = db.execute(
        text(
            "SELECT coin_id, COUNT(*) as cnt, MIN(date) as first_date, MAX(date) as last_date"
            " FROM price_cache WHERE source = 'COINGECKO'"
            " GROUP BY coin_id ORDER BY coin_id"
        )
    ).fetchall()
    blacklist = db.query(CoinBlacklist).order_by(CoinBlacklist.coin_symbol).all()

    return templates.TemplateResponse(
        "prices.html",
        {
            "request": request,
            "manual_prices": manual,
            "coingecko_summary": coingecko_summary,
            "blacklist": blacklist,
            "result": request.query_params.get("result"),
        },
    )


@app.post("/prices/manual")
def prices_manual_add(
    coin: str = Form(...),
    price_date: str = Form(...),
    price_sek: str = Form(...),
    db: Session = Depends(get_db),
):
    """Add or update a single manual price."""
    from datetime import date as date_type
    from decimal import Decimal, InvalidOperation

    try:
        d = date_type.fromisoformat(price_date.strip())
        p = Decimal(price_sek.strip().replace(",", "."))
        if p < 0:
            raise ValueError("negativt pris")
        PriceService(db).save_manual_price(coin.strip().upper(), d, p)
        msg = f"ok:Sparade pris för {coin.upper()} {d}: {p} SEK"
    except (ValueError, InvalidOperation) as e:
        msg = f"error:Ogiltigt värde: {e}"
    except Exception as e:
        logger.exception("Manual price save failed")
        msg = f"error:Fel: {e}"

    return RedirectResponse(f"/prices?result={msg}", status_code=303)


@app.post("/prices/manual/delete")
def prices_manual_delete(
    price_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Delete a manual price entry."""
    from kryptoskatt.models.price_cache import PriceCache

    entry = db.query(PriceCache).filter(PriceCache.id == price_id).first()
    if entry:
        db.delete(entry)
        db.commit()
        msg = f"ok:Pris borttaget"
    else:
        msg = "error:Posten hittades inte"
    return RedirectResponse(f"/prices?result={msg}", status_code=303)


@app.post("/prices/blacklist/add")
def prices_blacklist_add(
    coin_symbol: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    """Add a coin to the blacklist."""
    from kryptoskatt.models.coin_blacklist import CoinBlacklist

    symbol = coin_symbol.strip()
    if not symbol:
        return RedirectResponse("/prices?result=error:Tom symbol", status_code=303)
    existing = db.query(CoinBlacklist).filter(CoinBlacklist.coin_symbol == symbol).first()
    if existing:
        msg = f"error:{symbol} finns redan i listan"
    else:
        db.add(CoinBlacklist(coin_symbol=symbol, reason=reason.strip() or None))
        db.commit()
        msg = f"ok:{symbol} ignoreras nu i beräkningar"
    return RedirectResponse(f"/prices?result={msg}", status_code=303)


@app.post("/prices/blacklist/delete")
def prices_blacklist_delete(
    entry_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Remove a coin from the blacklist."""
    from kryptoskatt.models.coin_blacklist import CoinBlacklist

    entry = db.query(CoinBlacklist).filter(CoinBlacklist.id == entry_id).first()
    if entry:
        db.delete(entry)
        db.commit()
        msg = "ok:Coin borttagen från listan"
    else:
        msg = "error:Posten hittades inte"
    return RedirectResponse(f"/prices?result={msg}", status_code=303)


@app.get("/debug/coin/{coin}/transfers")
def debug_coin_transfers(coin: str, db: Session = Depends(get_db)):
    """Show all TRANSFER_IN/OUT rows for a coin with their from/to addresses.

    Useful for diagnosing why a DePIN/mining payout address doesn't appear
    in the unknown-addresses view.

    Example: /debug/coin/GEOD/transfers
    """
    from kryptoskatt.enums import EventType as ET
    rows = (
        db.query(Transaction)
        .filter(
            Transaction.base_coin == coin.upper(),
            Transaction.event_type.in_([ET.TRANSFER_IN.value, ET.TRANSFER_OUT.value]),
            Transaction.is_duplicate.is_(False),
        )
        .order_by(Transaction.timestamp_utc.desc())
        .limit(100)
        .all()
    )
    return JSONResponse([
        {
            "id": r.id,
            "date": r.timestamp_utc.date().isoformat(),
            "event_type": r.event_type,
            "base_coin": r.base_coin,
            "base_amount": str(r.base_amount),
            "from_address": r.from_address,
            "to_address": r.to_address,
            "tx_hash": r.tx_hash,
            "source_platform": r.source_platform,
        }
        for r in rows
    ])


@app.get("/debug/t2/{year}")
def debug_t2(year: int, db: Session = Depends(get_db)):
    """Diagnose T2 income matching for a year.

    Shows: income-category wallets, matching TRANSFER_IN transactions,
    and all GEOD/mining TRANSFER_IN rows (duplicate or not).
    Example: /debug/t2/2025
    """
    from kryptoskatt.enums import EventType as ET

    # Wallets with income categories
    income_wallets = [
        {"address": w.address, "category": w.category, "label": w.label, "is_mine": w.is_mine}
        for w in db.query(Wallet).filter(Wallet.category.in_(["mining_pool", "depin"])).all()
    ]
    income_addresses = {w["address"] for w in income_wallets}

    # All TRANSFER_IN for the year (non-duplicate) that match income addresses
    matched_txs = (
        db.query(Transaction)
        .filter(
            Transaction.event_type == ET.TRANSFER_IN.value,
            Transaction.is_duplicate.is_(False),
            Transaction.from_address.in_(list(income_addresses)) if income_addresses else False,
        )
        .filter(Transaction.timestamp_utc.between(f"{year}-01-01", f"{year+1}-01-01"))
        .all()
    ) if income_addresses else []

    # All GEOD transfers (including duplicates) to see full picture
    all_geod = (
        db.query(Transaction)
        .filter(
            Transaction.base_coin == "GEOD",
            Transaction.event_type.in_([ET.TRANSFER_IN.value, ET.TRANSFER_OUT.value, ET.REWARD.value]),
        )
        .order_by(Transaction.timestamp_utc.desc())
        .limit(50)
        .all()
    )

    return JSONResponse({
        "income_wallets": income_wallets,
        "matched_income_txs_count": len(matched_txs),
        "matched_income_txs": [
            {
                "id": t.id, "date": t.timestamp_utc.date().isoformat(),
                "coin": t.base_coin, "amount": str(t.base_amount),
                "from_address": t.from_address, "source": t.source_platform,
                "is_duplicate": t.is_duplicate,
            }
            for t in matched_txs
        ],
        "all_geod_txs": [
            {
                "id": t.id, "date": t.timestamp_utc.date().isoformat(),
                "event_type": t.event_type, "amount": str(t.base_amount),
                "from_address": t.from_address, "to_address": t.to_address,
                "source": t.source_platform, "is_duplicate": t.is_duplicate,
                "tx_hash": t.tx_hash,
            }
            for t in all_geod
        ],
    })


@app.get("/debug/tx/{signature}")
def debug_tx(signature: str):
    """Fetch raw Helius data for a specific transaction signature.

    Shows all nativeTransfers and tokenTransfers regardless of address filtering.
    Example: /debug/tx/3kJCX2By7EFBs...
    """
    import httpx
    url = f"https://api.helius.xyz/v0/transactions"
    params = {"api-key": settings.helius_api_key}
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, params=params, json={"transactions": [signature]})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    if not data:
        return JSONResponse({"error": "No data returned"})

    tx = data[0]
    return JSONResponse({
        "signature": tx.get("signature"),
        "timestamp": tx.get("timestamp"),
        "type": tx.get("type"),
        "fee": tx.get("fee"),
        "feePayer": tx.get("feePayer"),
        "nativeTransfers": tx.get("nativeTransfers", []),
        "tokenTransfers": tx.get("tokenTransfers", []),
    })


@app.get("/debug/swap-analysis")
def debug_swap_analysis(coin: str = "GEOD", db: Session = Depends(get_db)):
    """Show tx_hashes for a coin and what other coins share those hashes.

    Diagnoses why swap-implied pricing isn't working.
    Example: /debug/swap-analysis?coin=GEOD
    """
    from sqlalchemy import text

    rows = db.execute(
        text("""
            SELECT t.tx_hash, t.base_coin, t.event_type,
                   t.base_amount, t.price_sek, t.timestamp_utc
            FROM transactions t
            WHERE t.tx_hash IN (
                SELECT tx_hash FROM transactions
                WHERE base_coin = :coin
                  AND tx_hash IS NOT NULL
                  AND tx_hash != ''
                  AND is_duplicate = false
            )
            AND t.is_duplicate = false
            ORDER BY t.tx_hash, t.base_coin
        """),
        {"coin": coin},
    ).fetchall()

    by_hash: dict = {}
    for row in rows:
        h = row.tx_hash
        if h not in by_hash:
            by_hash[h] = []
        by_hash[h].append({
            "coin": row.base_coin,
            "event_type": row.event_type,
            "amount": str(row.base_amount),
            "price_sek": str(row.price_sek) if row.price_sek is not None else None,
            "timestamp": str(row.timestamp_utc),
        })

    return JSONResponse({
        "coin": coin,
        "tx_hash_count": len(by_hash),
        "hashes": by_hash,
    })
