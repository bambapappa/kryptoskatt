"""FastAPI web application for KryptoSkatt."""

import io
import logging
import tempfile
from collections.abc import Generator
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Integer, case, extract, func, select, text
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from kryptoskatt.api.v1 import api_v1_router
from kryptoskatt.chains import get_registry_for_user
from kryptoskatt.cli.fetch_cmd import create_import_batch_for_fetch, save_fetched_transactions
from kryptoskatt.cli.import_cmd import (
    SUPPORTED_PLATFORMS,
    create_import_batch,
    detect_platform,
    parse_file,
    save_transactions,
)
from kryptoskatt.config import settings
from kryptoskatt.db import get_session
from kryptoskatt.engine.dedup import DeduplicationEngine
from kryptoskatt.engine.gav import GavEngine
from kryptoskatt.engine.price_enrichment import PriceEnrichmentEngine
from kryptoskatt.engine.transfers import TransferMatcher
from kryptoskatt.enums import Chain
from kryptoskatt.models.account import Account
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.wallet import Wallet
from kryptoskatt.reports.audit import AuditExport
from kryptoskatt.reports.gav_history import GavHistoryReport
from kryptoskatt.reports.issues import FlaggedIssuesGenerator
from kryptoskatt.reports.k4 import K4ReportGenerator
from kryptoskatt.reports.net_position import NetPositionReport
from kryptoskatt.reports.t2 import T2IncomeReport
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.auth import AuthService
from kryptoskatt.services.price import PriceService
from kryptoskatt.services.price_history_importer import PriceHistoryImporter
from kryptoskatt.services.wallet import WalletService
from kryptoskatt.web.auth import (
    clear_session_cookie,
    get_optional_account,
    set_session_cookie,
)

# Chains that require an API key: maps chain → (key_name, key_value)
# Chains NOT in this dict are assumed to need no API key (e.g. Bitcoin/Blockstream)
_CHAIN_API_KEYS: dict[Chain, tuple[str, str]] = {
    Chain.ETHEREUM: ("ETHERSCAN_API_KEY", settings.etherscan_api_key),
    Chain.POLYGON:  ("ETHERSCAN_API_KEY", settings.etherscan_api_key),
    Chain.BNB:      ("ETHERSCAN_API_KEY", settings.etherscan_api_key),
    Chain.BASE:     ("ETHERSCAN_API_KEY", settings.etherscan_api_key),
    Chain.ARBITRUM: ("ETHERSCAN_API_KEY", settings.etherscan_api_key),
    Chain.SOLANA:   ("HELIUS_API_KEY",    settings.helius_api_key),
    Chain.PEAQ:     ("SUBSCAN_API_KEY",   settings.subscan_api_key),
    Chain.TRON:     ("TRONSCAN_API_KEY",    settings.tronscan_api_key),
    Chain.VECHAIN:  ("VECHAINSTATS_API_KEY", settings.vechainstats_api_key),
}

logger = logging.getLogger(__name__)


# Templates path: relative to this file
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Expose package version to all templates (read from source, not installed metadata)
from datetime import UTC  # noqa: E402

from kryptoskatt import __version__ as app_version  # noqa: E402

templates.env.globals["app_version"] = app_version


# Add custom Jinja2 filter for absolute value
def _abs_filter(value):
    """Jinja2 filter for absolute value."""
    if value is None:
        return None
    return abs(value)


templates.env.filters["abs"] = _abs_filter

app = FastAPI(
    title="KryptoSkatt API",
    description="Swedish crypto tax calculation service. Anonymous accounts, no registration required.",
    version="0.4.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


class APIVersionMiddleware(BaseHTTPMiddleware):
    """Inject X-API-Version header on all /api/ responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["X-API-Version"] = "1"
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers on HTML responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(APIVersionMiddleware)

app.include_router(api_v1_router, prefix="/api/v1")

# Debug router — only mounted when DEBUG_MODE=true.
# Must never be enabled in production: exposes raw DB data and destructive endpoints.
from fastapi import APIRouter as _APIRouter  # noqa: E402

_debug_router = _APIRouter(prefix="/debug", tags=["debug"])


def get_db() -> Generator[Session, None, None]:
    """Database session dependency."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_current_account_for_html(
    request: Request,
    db: Session = Depends(get_db),
    account: Account | None = Depends(get_optional_account),
) -> Account:
    """Dependency for HTML routes: redirect to /auth/login instead of raising 401."""
    if account is None:
        # Return a redirect response by raising it as an exception
        raise HTTPException(
            status_code=302,
            detail="Redirect",
            headers={"Location": "/auth/login"},
        )
    return account



@app.get("/health")
def health_check():
    """Health check endpoint."""
    return JSONResponse({"status": "ok"})


# ── Auth web routes ────────────────────────────────────────────────────────────

@app.get("/auth/login", response_class=HTMLResponse)
def auth_login_get(request: Request, error: str = ""):
    """Show login form."""
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": error},
    )


@app.post("/auth/login")
async def auth_login_post(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Process login with account_id."""
    from kryptoskatt.services.rate_limiter import login_limiter
    from kryptoskatt.web.auth import client_ip

    if not login_limiter.is_allowed(client_ip(request)):
        return RedirectResponse(
            "/auth/login?error=För+många+försök+—+försök+igen+senare", status_code=303
        )

    form = await request.form()
    account_id = (form.get("account_id") or "").strip()

    if not account_id:
        return RedirectResponse("/auth/login?error=Konto-ID+saknas", status_code=303)

    auth_service = AuthService(db)
    account = auth_service.get_account_by_id(account_id)
    if not account:
        return RedirectResponse("/auth/login?error=Ogiltigt+konto-ID", status_code=303)

    user_session = auth_service.create_session(account)
    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, user_session.session_token, request)
    return resp


@app.post("/auth/create")
def auth_create(request: Request, response: Response, db: Session = Depends(get_db)):
    """Create a new anonymous account."""
    account, token = AuthService(db).create_account()
    resp = RedirectResponse(f"/auth/created?account_id={account.account_id}", status_code=303)
    set_session_cookie(resp, token, request)
    return resp


@app.get("/auth/created", response_class=HTMLResponse)
def auth_created(request: Request, account_id: str = ""):
    """Show the new account ID (one-time display)."""
    return templates.TemplateResponse(
        request,
        "auth/create.html",
        {"account_id": account_id},
    )


@app.post("/auth/logout")
def auth_logout(
    response: Response,
    db: Session = Depends(get_db),
    account: Account | None = Depends(get_optional_account),
):
    """Log out current user."""
    if account:
        from kryptoskatt.models.user_session import UserSession
        db.query(UserSession).filter(UserSession.account_id == account.id).delete()
        db.commit()
    resp = RedirectResponse("/auth/login", status_code=303)
    clear_session_cookie(resp)
    return resp


@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Account settings: show account info, sessions, and custom chains."""
    from kryptoskatt.models.custom_chain_config import CustomChainConfig
    from kryptoskatt.models.user_session import UserSession
    from kryptoskatt.services.auth import COOKIE_NAME

    current_token = request.cookies.get(COOKIE_NAME)
    sessions = (
        db.query(UserSession)
        .filter(UserSession.account_id == account.id)
        .order_by(UserSession.last_used_at.desc())
        .all()
    )
    custom_chains = (
        db.query(CustomChainConfig)
        .filter(CustomChainConfig.account_id == account.id)
        .order_by(CustomChainConfig.chain_name)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "account": account,
            "sessions": sessions,
            "current_token": current_token,
            "custom_chains": custom_chains,
        },
    )


@app.post("/settings/custom-chains/add")
def settings_custom_chain_add(
    chain_name: str = Form(...),
    adapter_type: str = Form(...),
    explorer_url: str = Form(...),
    api_key: str = Form(""),
    native_coin: str = Form(...),
    chain_id: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Add a custom chain configuration."""
    from kryptoskatt.models.custom_chain_config import CustomChainConfig

    name = chain_name.strip().upper()
    if not name:
        return RedirectResponse("/settings?error=Kedjenamn+saknas", status_code=303)

    # SSRF guard: a Blockscout explorer_url is fetched server-side. Reject URLs
    # that resolve to internal/non-public addresses before storing them.
    if adapter_type == "blockscout":
        from kryptoskatt.utils.url_guard import UnsafeURLError, validate_outbound_url

        try:
            validate_outbound_url(explorer_url.strip())
        except UnsafeURLError:
            return RedirectResponse(
                "/settings?error=Ogiltig+eller+icke-publik+explorer-URL", status_code=303
            )

    existing = db.query(CustomChainConfig).filter(
        CustomChainConfig.account_id == account.id,
        CustomChainConfig.chain_name == name,
    ).first()
    if existing:
        return RedirectResponse(f"/settings?error=Kedjan+{name}+finns+redan", status_code=303)

    chain_id_int: int | None = None
    if chain_id.strip():
        try:
            chain_id_int = int(chain_id.strip())
        except ValueError:
            return RedirectResponse("/settings?error=Ogiltigt+chain+ID", status_code=303)

    db.add(CustomChainConfig(
        account_id=account.id,
        chain_name=name,
        adapter_type=adapter_type,
        explorer_url=explorer_url.strip().rstrip("/"),
        api_key=api_key.strip() or None,
        native_coin=native_coin.strip().upper(),
        chain_id=chain_id_int,
    ))
    db.commit()
    return RedirectResponse(f"/settings?ok=Kedjan+{name}+lades+till", status_code=303)


@app.post("/settings/custom-chains/delete")
def settings_custom_chain_delete(
    chain_id_pk: int = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Delete a custom chain configuration."""
    from kryptoskatt.models.custom_chain_config import CustomChainConfig

    entry = db.query(CustomChainConfig).filter(
        CustomChainConfig.id == chain_id_pk,
        CustomChainConfig.account_id == account.id,
    ).first()
    if entry:
        db.delete(entry)
        db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/sessions/revoke-all")
def settings_revoke_all_sessions(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Revoke all sessions except the current one."""
    from kryptoskatt.models.user_session import UserSession
    from kryptoskatt.services.auth import COOKIE_NAME

    current_token = request.cookies.get(COOKIE_NAME)
    query = db.query(UserSession).filter(UserSession.account_id == account.id)
    if current_token:
        query = query.filter(UserSession.session_token != current_token)
    query.delete(synchronize_session=False)
    db.commit()
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/delete-account")
def settings_delete_account(
    request: Request,
    confirm: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Delete the account and all data, then redirect to login."""
    if confirm != "DELETE MY ACCOUNT":
        return RedirectResponse("/settings?error=bad_confirm", status_code=303)

    from kryptoskatt.models.custom_chain_config import CustomChainConfig
    from kryptoskatt.models.disposal import Disposal
    from kryptoskatt.models.gav_ledger import GavLedger
    from kryptoskatt.models.t2_manual_entry import T2ManualEntry
    from kryptoskatt.models.t2_manual_income_entry import T2ManualIncomeEntry
    from kryptoskatt.models.transaction import ImportBatch, Transaction
    from kryptoskatt.models.transfer_link import TransferLink
    from kryptoskatt.models.user_session import UserSession
    from kryptoskatt.models.wallet import Wallet

    uid = account.id
    tx_ids = [row[0] for row in db.query(Transaction.id).filter(Transaction.user_id == uid).all()]
    if tx_ids:
        db.query(TransferLink).filter(
            (TransferLink.tx_out_id.in_(tx_ids)) | (TransferLink.tx_in_id.in_(tx_ids))
        ).delete(synchronize_session=False)

    db.query(Transaction).filter(Transaction.user_id == uid).delete(synchronize_session=False)
    db.query(ImportBatch).filter(ImportBatch.user_id == uid).delete(synchronize_session=False)
    db.query(Wallet).filter(Wallet.user_id == uid).delete(synchronize_session=False)
    db.query(Disposal).filter(Disposal.user_id == uid).delete(synchronize_session=False)
    db.query(GavLedger).filter(GavLedger.user_id == uid).delete(synchronize_session=False)
    db.query(T2ManualEntry).filter(T2ManualEntry.user_id == uid).delete(synchronize_session=False)
    db.query(T2ManualIncomeEntry).filter(T2ManualIncomeEntry.user_id == uid).delete(synchronize_session=False)
    db.query(CustomChainConfig).filter(CustomChainConfig.account_id == uid).delete(synchronize_session=False)
    db.query(UserSession).filter(UserSession.account_id == uid).delete(synchronize_session=False)
    db.query(Account).filter(Account.id == uid).delete(synchronize_session=False)
    db.commit()

    response = RedirectResponse("/auth/login", status_code=303)
    clear_session_cookie(response)
    return response


@app.get("/wallets", response_class=HTMLResponse)
def wallets_page(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Wallet management page."""
    from kryptoskatt.services.wallet import WalletService

    service = WalletService(db, account.id)
    wallets = service.list_wallets()
    chains = [c.value for c in Chain if c != Chain.UNKNOWN]
    registry = get_registry_for_user(db, account.id)
    supported = set(registry.supported_chains())
    return templates.TemplateResponse(
        request,
        "wallets.html",
        {
            "account": account,
            "wallets": wallets,
            "chains": chains,
            "supported_chains": supported,
        },
    )


@app.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Dashboard listing available tax years with Disposal records."""
    from decimal import Decimal

    from kryptoskatt.models.transaction import ImportBatch

    # Get distinct years with disposals (for K4 links)
    stmt = (
        select(Disposal.tax_year)
        .where(Disposal.user_id == account.id)
        .distinct()
        .order_by(Disposal.tax_year.desc())
    )
    years = db.execute(stmt).scalars().all()

    # Get distinct years with transactions (for T2/transfers links, available before calculation)
    _tx_year_col = extract("year", Transaction.timestamp_utc).cast(Integer)
    tx_years_stmt = (
        select(_tx_year_col)
        .where(Transaction.user_id == account.id)
        .distinct()
        .order_by(_tx_year_col.desc())
    )
    tx_years = db.execute(tx_years_stmt).scalars().all()

    # Per-year summary: count, total gain, total loss
    year_stats = {}
    for year in years:
        rows = (
            db.query(
                func.count(Disposal.id),
                func.sum(
                    case(
                        (Disposal.gain_loss_sek > 0, Disposal.gain_loss_sek),
                        else_=Decimal("0"),
                    )
                ),
                func.sum(
                    case(
                        (Disposal.gain_loss_sek < 0, Disposal.gain_loss_sek),
                        else_=Decimal("0"),
                    )
                ),
            )
            .filter(Disposal.user_id == account.id, Disposal.tax_year == year)
            .one()
        )
        year_stats[year] = {
            "count": rows[0] or 0,
            "total_gain": rows[1] or Decimal("0"),
            "total_loss": rows[2] or Decimal("0"),
        }

    # Wallet count for this account
    wallet_count = db.query(func.count(Wallet.id)).filter(Wallet.user_id == account.id).scalar() or 0

    # Most recent import timestamp
    last_import = (
        db.query(func.max(ImportBatch.imported_at))
        .filter(ImportBatch.user_id == account.id)
        .scalar()
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "years": years,
            "tx_years": tx_years,
            "year_stats": year_stats,
            "account": account,
            "wallet_count": wallet_count,
            "last_import": last_import,
        },
    )


@app.get("/year/{year}", response_class=HTMLResponse)
def year_summary(
    request: Request,
    year: int,
    show_hidden: int = 0,
    blacklisted: str = "",
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """K4 summary for a given year."""
    from kryptoskatt.models.coin_blacklist import CoinBlacklist
    user_id = account.id

    report_generator = K4ReportGenerator(db, user_id)
    report = report_generator.generate(year)

    # Blacklist symbols stored uppercase; compare case-insensitively.
    # Scoped to this account so other users' blacklists never affect this view.
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
            "account": account,
        },
    )


@app.get("/year/{year}/net-position", response_class=HTMLResponse)
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


@app.get("/year/{year}/transactions", response_class=HTMLResponse)
def transactions(
    request: Request,
    year: int,
    page: int = 1,
    coin: str = "",
    event_type: str = "",
    platform: str = "",
    duplicates: str = "all",  # "all" | "yes" | "no"
    sort: str = "date_desc",  # date_desc | date_asc | amount_desc | amount_asc | coin_asc | coin_desc
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Paginated raw transaction list for a given year with filtering and sorting."""
    from sqlalchemy import extract

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


@app.get("/year/{year}/download/csv")
def download_csv(year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Download K4 report as CSV."""
    report_generator = K4ReportGenerator(db, account.id)
    report = report_generator.generate(year)

    # Unique temp file per request — a predictable shared path (/tmp/k4_{year}.csv)
    # would let concurrent downloads from different accounts read each other's data.
    with tempfile.NamedTemporaryFile(prefix=f"k4_{year}_", suffix=".csv", delete=False) as tmp:
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


@app.get("/year/{year}/download/json")
def download_json(year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Download K4 report as JSON."""
    report_generator = K4ReportGenerator(db, account.id)
    report = report_generator.generate(year)

    # Unique temp file per request — a predictable shared path (/tmp/k4_{year}.json)
    # would let concurrent downloads from different accounts read each other's data.
    with tempfile.NamedTemporaryFile(prefix=f"k4_{year}_", suffix=".json", delete=False) as tmp:
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


@app.get("/year/{year}/audit", response_class=HTMLResponse)
def audit_view(request: Request, year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Full transaction audit trail for a year — HTML view with clickable explorer links."""
    exporter = AuditExport(db, account.id)
    rows = exporter.generate(year)
    return templates.TemplateResponse(
        request,
        "audit.html",
        {"year": year, "rows": rows, "account": account},
    )


@app.get("/year/{year}/download/audit")
def download_audit(year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Download full transaction audit trail as CSV."""
    exporter = AuditExport(db, account.id)
    content = exporter.export_csv(year)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8-sig")),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f'attachment; filename="transaktioner_{year}.csv"'},
    )


@app.get("/year/{year}/download/k4-html")
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


@app.get("/year/{year}/download/t2-html")
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


@app.post("/year/{year}/t2/manual-cost/add")
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


@app.post("/year/{year}/t2/manual-cost/delete")
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


@app.post("/year/{year}/blacklist-coin")
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
        db.add(CoinBlacklist(
            user_id=account.id, coin_symbol=symbol, reason="Markerad som spam från årsvy"
        ))
        db.commit()
    return RedirectResponse(f"/year/{year}?blacklisted={symbol[:30]}", status_code=303)


@app.post("/year/{year}/unblacklist-coin")
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


@app.get("/year/{year}/t2", response_class=HTMLResponse)
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


@app.post("/year/{year}/t2/manual-income/add")
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


@app.post("/year/{year}/t2/manual-income/delete")
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


@app.get("/year/{year}/gav/{coin}", response_class=HTMLResponse)
def gav_history(request: Request, year: int, coin: str, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """GAV history for a specific coin."""
    report_generator = GavHistoryReport(db, account.id)
    snapshots = report_generator.generate(coin=coin, year=year)
    return templates.TemplateResponse(
        request,
        "gav_history.html",
        {"request": request, "year": year, "coin": coin, "snapshots": snapshots, "account": account},
    )


@app.get("/year/{year}/issues", response_class=HTMLResponse)
def issues(request: Request, year: int, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Flagged issues for a given year."""
    report_generator = FlaggedIssuesGenerator(db, account.id)
    issues_report = report_generator.generate(year=year)
    return templates.TemplateResponse(
        request,
        "issues.html",
        {"year": year, "issues_report": issues_report, "account": account},
    )


@app.get("/year/{year}/transfers", response_class=HTMLResponse)
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


@app.post("/year/{year}/transfers/match", response_class=HTMLResponse)
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


@app.get("/addresses", response_class=HTMLResponse)
def unknown_addresses(
    request: Request,
    result: str = "",
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """List unknown TRANSFER_IN senders and TRANSFER_OUT recipients."""
    user_id = account.id
    # Known addresses (registered wallets) — normalised to lowercase for case-insensitive match
    known = {w.address.lower() for w in db.query(Wallet).filter(Wallet.user_id == user_id).all()}

    from decimal import Decimal as _Dec

    # Helper to aggregate address stats from a query result (includes amount totals)
    def _aggregate(rows, include_source: bool = False):
        # Key: (address_or_null, coin) — NULL-address rows are split per coin
        agg: dict[tuple, dict] = {}
        for row in rows:
            if include_source:
                address, coin, ts, amount, source_platform = row
            else:
                address, coin, ts, amount = row
                source_platform = None
            addr_lower = address.lower() if address else None
            if addr_lower and addr_lower in known:
                continue
            key = (addr_lower or "__null__", coin)
            if key not in agg:
                agg[key] = {"tx_count": 0, "latest": ts, "total_amount": _Dec("0"),
                            "address": address, "coin": coin, "sources": set()}
            agg[key]["tx_count"] += 1
            agg[key]["total_amount"] += _Dec(str(amount or 0))
            if ts and (agg[key]["latest"] is None or ts > agg[key]["latest"]):
                agg[key]["latest"] = ts
            if source_platform:
                # Strip chain suffix for display: ETHERSCAN_ETHEREUM → ETHERSCAN
                base = source_platform.split("_")[0]
                agg[key]["sources"].add(base)
        result = []
        for _key, data in sorted(agg.items(), key=lambda x: -abs(x[1]["total_amount"])):
            result.append({
                "address": data["address"] or None,
                "coin": data["coin"],
                "is_null_address": data["address"] is None,
                "tx_count": data["tx_count"],
                "total_amount": f"{data['total_amount']:,.4f}",
                "latest_date": data["latest"].date() if data["latest"] else "",
                "sources": ", ".join(sorted(data["sources"])),
            })
        return result

    from kryptoskatt.enums import EventType

    # Platforms set by blockchain scanners (not manually tagged by user)
    SCANNER_PLATFORMS = {"ETHERSCAN", "HELIUS", "SOLSCAN", "BLOCKSCOUT", "LEDGER", "TRONSCAN", "VECHAIN"}

    sender_rows = (
        db.query(Transaction.from_address, Transaction.base_coin, Transaction.timestamp_utc, Transaction.base_amount)
        .filter(
            Transaction.user_id == user_id,
            Transaction.event_type == EventType.TRANSFER_IN.value,
            Transaction.is_duplicate.is_(False),
            Transaction.from_address.isnot(None),
        )
        .all()
    )
    # Include all TRANSFER_OUTs with unknown recipients (NULL or unregistered to_address).
    # Exclude rows that have been manually tagged (source_platform not a scanner).
    recipient_rows = (
        db.query(Transaction.to_address, Transaction.base_coin, Transaction.timestamp_utc, Transaction.base_amount, Transaction.source_platform)
        .filter(
            Transaction.user_id == user_id,
            Transaction.event_type == EventType.TRANSFER_OUT.value,
            Transaction.is_duplicate.is_(False),
            Transaction.source_platform.in_(
                [p for p in SCANNER_PLATFORMS]
                + [f"{p}_{c}" for p in SCANNER_PLATFORMS for c in
                   ["ETHEREUM","POLYGON","BNB","BASE","ARBITRUM","SOLANA","TRON","BITCOIN","XRP","VECHAIN","KADENA","PEAQ","MXC_ZKEVM","ALEO","RIPPLE"]]
            ),
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
            "unknown_recipients": _aggregate(recipient_rows, include_source=True),
            "chains": chains,
            "account": account,
        },
    )


@app.post("/addresses/mark-spam")
def mark_address_as_spam(
    address: str = Form(...),
    coins: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Register an address as spam_source and blacklist all coins it sent.

    coins: comma-separated list of coin symbols to blacklist (from the address row).
    """
    from sqlalchemy import func as sqlfunc

    from kryptoskatt.models.coin_blacklist import CoinBlacklist

    try:
        service = WalletService(db, account.id)
        # Register with UNKNOWN chain — we never fetch from spam addresses
        try:
            service.add_wallet(
                WalletCreate(
                    address=address,
                    chain=Chain.UNKNOWN.value,
                    label="spam",
                    is_mine=False,
                    category="spam_source",
                )
            )
        except ValueError:
            pass  # Already registered — still proceed to blacklist coins

        blacklisted: list[str] = []
        for coin in coins.split(","):
            symbol = coin.strip()
            if not symbol:
                continue
            existing = db.query(CoinBlacklist).filter(
                CoinBlacklist.user_id == account.id,
                sqlfunc.upper(CoinBlacklist.coin_symbol) == symbol.upper(),
            ).first()
            if not existing:
                db.add(CoinBlacklist(user_id=account.id, coin_symbol=symbol, reason="Spam-airdrop"))
                blacklisted.append(symbol)
        db.commit()

        msg = f"ok:{address[:20]}… markerad som spam"
        if blacklisted:
            msg += f", blacklistar: {', '.join(blacklisted[:5])}"
    except Exception as e:
        logger.exception("Mark spam failed")
        msg = f"error:Fel: {e}"

    return RedirectResponse(f"/addresses?result={msg}", status_code=303)


@app.post("/addresses/tag-null-transfers")
def tag_null_address_transfers(
    coin: str = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Tag TRANSFER_OUT transactions with NULL to_address for a specific coin as TAGGED.

    This removes them from the unknown-recipients list while keeping them as
    TRANSFER_OUTs in the transaction history (they still become K4 disposals).
    """
    from kryptoskatt.enums import EventType

    try:
        updated = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == account.id,
                Transaction.event_type == EventType.TRANSFER_OUT.value,
                Transaction.to_address.is_(None),
                Transaction.base_coin == coin,
            )
            .update({"source_platform": "TAGGED"}, synchronize_session=False)
        )
        db.commit()
        msg = f"ok:{updated} {coin}-transaktioner dolda från okända mottagare"
    except Exception as e:
        logger.exception("Tag null transfers failed")
        msg = f"error:Fel: {e}"

    return RedirectResponse(f"/addresses?result={msg}", status_code=303)


@app.post("/addresses/register")
def register_address(
    address: str = Form(...),
    chain: str = Form(...),
    label: str = Form(""),
    category: str = Form("own"),
    result_url: str = Form("/addresses"),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Register an unknown address as a wallet."""
    try:
        service = WalletService(db, account.id)
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


@app.post("/addresses/bulk-register")
async def bulk_register_addresses(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Register multiple addresses at once from checkbox selection."""
    from kryptoskatt.schemas import WalletCreate
    from kryptoskatt.services.wallet import WalletService

    form = await request.form()
    addresses = form.getlist("address")
    chain = form.get("bulk_chain", "ETHEREUM")
    category = form.get("bulk_category", "exchange")
    label = form.get("bulk_label", "")

    if not addresses:
        return RedirectResponse("/addresses?result=error:Inga adresser valda", status_code=303)

    service = WalletService(db, account.id)
    registered = 0
    skipped = 0

    for addr in addresses:
        addr = addr.strip()
        if not addr:
            continue
        try:
            service.add_wallet(
                WalletCreate(address=addr, chain=chain, label=label, is_mine=(category == "own"), category=category)
            )
            registered += 1
        except ValueError:
            skipped += 1  # already registered

    msg = f"ok:Registrerade {registered} adresser som {category}"
    if skipped:
        msg += f" ({skipped} redan registrerade)"
    return RedirectResponse(f"/addresses?result={msg}", status_code=303)


@app.post("/addresses/auto-tag")
def addresses_auto_tag(
    chain: str = Form("ETHEREUM"),
    max_candidates: int = Form(50),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Auto-tag unknown recipient addresses using contract registry + Etherscan lookup."""
    from kryptoskatt.enums import EventType
    from kryptoskatt.services.address_tagger import AddressTagger

    try:
        user_id = account.id
        known = {w.address for w in db.query(Wallet).filter(Wallet.user_id == user_id).all()}

        recipient_rows = (
            db.query(Transaction.to_address)
            .filter(
                Transaction.user_id == user_id,
                Transaction.event_type == EventType.TRANSFER_OUT.value,
                Transaction.is_duplicate.is_(False),
                Transaction.to_address.isnot(None),
            )
            .distinct()
            .all()
        )
        sender_rows = (
            db.query(Transaction.from_address)
            .filter(
                Transaction.user_id == user_id,
                Transaction.event_type == EventType.TRANSFER_IN.value,
                Transaction.is_duplicate.is_(False),
                Transaction.from_address.isnot(None),
            )
            .distinct()
            .all()
        )

        # Collect unknown addresses from both sets (cap to avoid request timeout)
        candidates: list[str] = []
        seen: set[str] = set()
        for (addr,) in recipient_rows + sender_rows:
            if addr and addr not in known and addr not in seen:
                candidates.append(addr)
                seen.add(addr)

        candidates = candidates[:max(1, max_candidates)]
        tagger = AddressTagger(db, user_id=user_id, etherscan_api_key=settings.etherscan_api_key)
        summary = tagger.auto_tag_unknown(candidates, chain=chain)

        msg = f"ok:{summary['tagged']} adresser taggades, {summary['skipped']} hoppades över"
    except Exception as e:
        logger.exception("Auto-tag failed")
        msg = f"error:Fel: {e}"

    return RedirectResponse(f"/addresses?result={msg}", status_code=303)


@app.get("/actions", response_class=HTMLResponse)
def actions_dashboard(
    request: Request,
    result: str = "",
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Actions dashboard for import, fetch, calculate, and wallet management."""
    wallet_service = WalletService(db, account.id)
    wallets = wallet_service.list_wallets()
    chains = [c.value for c in Chain if c != Chain.UNKNOWN]
    return templates.TemplateResponse(
        request,
        "actions.html",
        {"result": result, "wallets": wallets, "chains": chains, "account": account},
    )


@app.post("/actions/import")
async def actions_import(
    file: UploadFile = File(...),
    platform: str = Form("auto"),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
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

        uid = account.id
        batch = create_import_batch(
            db, resolved_platform, file.filename or "upload", len(transactions), len(errors), user_id=uid
        )
        saved = save_transactions(db, transactions, batch, user_id=uid)
        msg = f"ok:Importerade {saved} transaktioner från {file.filename} (plattform: {resolved_platform})"
        if errors:
            msg += f" — {len(errors)} fel"
    except Exception as e:
        logger.exception("Import failed")
        msg = f"error:Importfel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


# ── Dedicated CSV import page ───────────────────────────────────────────────

@app.get("/import", response_class=HTMLResponse)
def import_page(
    request: Request,
    result: str = "",
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Dedicated CSV import page with file upload form."""
    return templates.TemplateResponse(
        request,
        "import.html",
        {
            "account": account,
            "platforms": SUPPORTED_PLATFORMS,
            "result": result,
        },
    )


@app.post("/import")
async def import_post(
    file: UploadFile = File(...),
    platform: str = Form("auto"),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Process CSV upload from the dedicated import page."""
    try:
        suffix = Path(file.filename or "upload.csv").suffix or ".csv"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = Path(tmp.name)

        try:
            resolved_platform = platform
            if platform == "auto":
                with open(tmp_path, encoding="utf-8") as f:
                    lines = [f.readline() for _ in range(10)]
                resolved_platform = detect_platform(tmp_path, lines)

            transactions, errors = parse_file(tmp_path, resolved_platform)
        finally:
            tmp_path.unlink(missing_ok=True)

        uid = account.id
        batch = create_import_batch(
            db, resolved_platform, file.filename or "upload",
            len(transactions), len(errors), user_id=uid,
        )
        saved = save_transactions(db, transactions, batch, user_id=uid)
        dup_count = batch.duplicate_count or 0
        msg = f"ok:Importerade {saved} transaktioner, {dup_count} duplikat hoppades över (plattform: {resolved_platform})"
        if errors:
            msg += f" — {len(errors)} fel"
    except Exception as e:
        logger.exception("Import failed")
        msg = f"error:Importfel: {e}"

    return RedirectResponse(f"/import?result={msg}", status_code=303)


@app.post("/actions/fetch")
def actions_fetch(
    address: str = Form(...),
    chain: str = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Fetch transactions from blockchain for a given address."""
    try:
        chain_upper = chain.upper()
        # Try to resolve as a built-in Chain enum; custom chains stay as raw string
        try:
            chain_key = Chain(chain_upper)
        except ValueError:
            chain_key = chain_upper  # type: ignore[assignment]

        # API key check only applies to known built-in chains
        if isinstance(chain_key, Chain) and chain_key in _CHAIN_API_KEYS:
            key_name, api_key = _CHAIN_API_KEYS[chain_key]
            if not api_key:
                return RedirectResponse(
                    f"/actions?result=error:Saknar {key_name} i .env — lägg till den och starta om",
                    status_code=303,
                )

        registry = get_registry_for_user(db, account.id)
        adapter = registry.get_adapter(chain_key)
        if adapter is None:
            return RedirectResponse(f"/actions?result=error:Ingen adapter för {chain}", status_code=303)

        uid = account.id
        txs = adapter.fetch_transactions(address, chain_key)
        if not txs:
            msg = f"error:Inga transaktioner hittades för {address[:20]}... på {chain} — kontrollera adressen"
        else:
            chain_tag = chain_key.value if isinstance(chain_key, Chain) else chain_upper
            wallet_record = db.query(Wallet).filter_by(address=address, chain=chain_tag).first()
            batch = create_import_batch_for_fetch(db, 1, len(txs), user_id=uid)
            saved, skipped = save_fetched_transactions(
                db, txs, batch, user_id=uid,
                wallet_id=wallet_record.id if wallet_record else None,
                chain_tag=chain_tag,
            )
            msg = f"ok:Hämtade {saved} nya transaktioner för {address[:20]}... på {chain}"
            if skipped:
                msg += f" ({skipped} redan importerade hoppades över)"
    except Exception as e:
        logger.exception("Fetch failed")
        msg = f"error:Hämtningsfel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/refetch")
def actions_refetch(
    address: str = Form(...),
    chain: str = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Delete all existing transactions fetched from an address, then re-fetch.

    Useful when the chain adapter has been improved and old records were parsed
    incorrectly (wrong from/to addresses, wrong event_type, etc.).
    Deletes rows where from_address OR to_address matches the given address
    and source_platform matches the chain adapter.
    """
    try:
        chain_upper = chain.upper()
        try:
            chain_key = Chain(chain_upper)
        except ValueError:
            chain_key = chain_upper  # type: ignore[assignment]

        if isinstance(chain_key, Chain) and chain_key in _CHAIN_API_KEYS:
            key_name, api_key = _CHAIN_API_KEYS[chain_key]
            if not api_key:
                return RedirectResponse(
                    f"/actions?result=error:Saknar {key_name} i .env",
                    status_code=303,
                )

        registry = get_registry_for_user(db, account.id)
        adapter = registry.get_adapter(chain_key)
        if adapter is None:
            return RedirectResponse(f"/actions?result=error:Ingen adapter för {chain}", status_code=303)

        chain_tag = chain_key.value if isinstance(chain_key, Chain) else chain_upper
        # Determine which source_platform tags were used for this chain
        if isinstance(chain_key, Chain) and chain_key == Chain.SOLANA:
            platform_tags = {"helius", "solscan"}
        else:
            platform_tags = {"etherscan", "blockscout", chain_tag.lower()}

        # Find transactions to delete — scoped to this account so one user can
        # never delete another account's transactions for a (public) address.
        tx_ids_to_delete = [
            row.id for row in db.query(Transaction.id).filter(
                Transaction.user_id == account.id,
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

        uid = account.id
        txs = adapter.fetch_transactions(address, chain_key)
        if not txs:
            msg = f"ok:Raderade {deleted} gamla rader. Inga nya transaktioner hittades."
        else:
            wallet_record = db.query(Wallet).filter_by(address=address, chain=chain_tag).first()
            batch = create_import_batch_for_fetch(db, 1, len(txs), user_id=uid)
            saved, skipped = save_fetched_transactions(
                db, txs, batch, user_id=uid,
                wallet_id=wallet_record.id if wallet_record else None,
                chain_tag=chain_tag,
            )
            msg = (
                f"ok:Rensade {deleted} gamla rader och importerade {saved} nya "
                f"transaktioner för {address[:20]}… på {chain}"
            )
            if skipped:
                msg += f" ({skipped} dubbletter hoppades över)"
    except Exception as e:
        logger.exception("Refetch failed")
        msg = f"error:Hämtningsfel: {e}"

    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@app.post("/actions/fetch-all")
def actions_fetch_all(db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Fetch transactions for all registered wallets across all networks."""
    uid = account.id
    wallet_service = WalletService(db, uid)
    wallets = wallet_service.list_wallets(mine_only=True)

    if not wallets:
        return RedirectResponse(
            "/actions?result=error:Inga plånböcker registrerade — lägg till adresser först",
            status_code=303,
        )

    registry = get_registry_for_user(db, uid)
    total_saved = 0
    total_skipped = 0
    errors: list[str] = []

    for wallet in wallets:
        # Resolve chain — may be a built-in Chain enum or a custom chain name string
        try:
            chain_key: Chain | str = Chain(wallet.chain)
        except ValueError:
            chain_key = wallet.chain.upper()

        if isinstance(chain_key, Chain) and chain_key in _CHAIN_API_KEYS:
            key_name, api_key = _CHAIN_API_KEYS[chain_key]
            if not api_key:
                errors.append(f"{wallet.chain}: saknar {key_name}")
                continue

        adapter = registry.get_adapter(chain_key)
        if adapter is None:
            errors.append(f"{wallet.chain}: ingen adapter")
            continue

        chain_tag = chain_key.value if isinstance(chain_key, Chain) else wallet.chain.upper()
        try:
            txs = adapter.fetch_transactions(wallet.address, chain_key)
            if txs:
                batch = create_import_batch_for_fetch(db, 1, len(txs), user_id=uid)
                saved, skipped = save_fetched_transactions(
                    db, txs, batch, user_id=uid,
                    wallet_id=wallet.id,
                    chain_tag=chain_tag,
                )
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
    account: Account = Depends(get_current_account_for_html),
):
    """Run dedup + transfer matching + GAV calculation for a year."""
    try:
        uid = account.id
        dedup_engine = DeduplicationEngine(db, uid)
        dedup_engine.deduplicate_all()

        enrich = PriceEnrichmentEngine(db, uid)
        enrich_report = enrich.enrich()

        wallet_service = WalletService(db, uid)
        my_addresses = wallet_service.get_my_addresses()
        transfer_matcher = TransferMatcher(db, my_addresses, uid)
        transfer_matcher.match_all()

        gav_engine = GavEngine(db, uid)
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
    account: Account = Depends(get_current_account_for_html),
):
    """Add a wallet via web form."""
    try:
        service = WalletService(db, account.id)
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
    account: Account = Depends(get_current_account_for_html),
):
    """Add multiple wallets at once from a newline-separated list."""
    service = WalletService(db, account.id)
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
    account: Account = Depends(get_current_account_for_html),
):
    """Remove a wallet via web form."""
    try:
        service = WalletService(db, account.id)
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
def actions_import_price_history(db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
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
    account: Account = Depends(get_current_account_for_html),
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
def prices_page(request: Request, db: Session = Depends(get_db), account: Account = Depends(get_current_account_for_html)):
    """Show manual prices, CoinGecko-cached prices, and coin blacklist."""
    from kryptoskatt.enums import PriceSource
    from kryptoskatt.models.coin_blacklist import CoinBlacklist
    from kryptoskatt.models.price_cache import PriceCache

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
    blacklist = (
        db.query(CoinBlacklist)
        .filter(CoinBlacklist.user_id == account.id)
        .order_by(CoinBlacklist.coin_symbol)
        .all()
    )

    return templates.TemplateResponse(
        "prices.html",
        {
            "request": request,
            "manual_prices": manual,
            "coingecko_summary": coingecko_summary,
            "blacklist": blacklist,
            "result": request.query_params.get("result"),
            "account": account,
        },
    )


@app.post("/prices/manual")
def prices_manual_add(
    coin: str = Form(...),
    price_date: str = Form(...),
    price_sek: str = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
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
    account: Account = Depends(get_current_account_for_html),
):
    """Delete a manual price entry.

    Restricted to MANUAL-source rows so this endpoint cannot be used to wipe the
    shared CoinGecko price cache. (price_cache is a shared market-data table.)
    """
    from kryptoskatt.enums import PriceSource
    from kryptoskatt.models.price_cache import PriceCache

    entry = db.query(PriceCache).filter(
        PriceCache.id == price_id,
        PriceCache.source == PriceSource.MANUAL.value,
    ).first()
    if entry:
        db.delete(entry)
        db.commit()
        msg = "ok:Pris borttaget"
    else:
        msg = "error:Posten hittades inte"
    return RedirectResponse(f"/prices?result={msg}", status_code=303)


@app.post("/prices/blacklist/add")
def prices_blacklist_add(
    coin_symbol: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Add a coin to the blacklist."""
    from kryptoskatt.models.coin_blacklist import CoinBlacklist

    symbol = coin_symbol.strip()
    if not symbol:
        return RedirectResponse("/prices?result=error:Tom symbol", status_code=303)
    existing = db.query(CoinBlacklist).filter(
        CoinBlacklist.user_id == account.id,
        CoinBlacklist.coin_symbol == symbol,
    ).first()
    if existing:
        msg = f"error:{symbol} finns redan i listan"
    else:
        db.add(CoinBlacklist(user_id=account.id, coin_symbol=symbol, reason=reason.strip() or None))
        db.commit()
        msg = f"ok:{symbol} ignoreras nu i beräkningar"
    return RedirectResponse(f"/prices?result={msg}", status_code=303)


@app.post("/prices/blacklist/delete")
def prices_blacklist_delete(
    entry_id: int = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Remove a coin from the blacklist."""
    from kryptoskatt.models.coin_blacklist import CoinBlacklist

    entry = db.query(CoinBlacklist).filter(
        CoinBlacklist.id == entry_id,
        CoinBlacklist.user_id == account.id,
    ).first()
    if entry:
        db.delete(entry)
        db.commit()
        msg = "ok:Coin borttagen från listan"
    else:
        msg = "error:Posten hittades inte"
    return RedirectResponse(f"/prices?result={msg}", status_code=303)


@app.post("/transactions/bulk-tag")
def transactions_bulk_tag(
    ids: str = Form(...),
    tag: str = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Set source_platform tag on a list of transaction IDs.

    Useful for labelling unlinked TRANSFER_OUTs as EXCHANGE, DEX, etc.
    Does not affect tax calculation — source_platform is metadata only.
    """
    try:
        id_list = [int(x.strip()) for x in ids.replace("\n", ",").split(",") if x.strip().isdigit()]
    except ValueError:
        return RedirectResponse("/actions?result=error:Ogiltiga ID:n", status_code=303)

    if not id_list:
        return RedirectResponse("/actions?result=error:Inga ID:n angivna", status_code=303)

    tag_clean = tag.strip().upper()
    # Scope to this account so a user cannot retag another account's transactions.
    updated = (
        db.query(Transaction)
        .filter(Transaction.id.in_(id_list), Transaction.user_id == account.id)
        .all()
    )
    for tx in updated:
        tx.source_platform = tag_clean
    db.commit()
    return RedirectResponse(f"/actions?result=ok:{len(updated)} transaktioner taggades som {tag_clean}", status_code=303)


@_debug_router.get("/coin/{coin}/transfers")
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


@_debug_router.get("/t2/{year}")
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


@_debug_router.get("/tx/{signature}")
def debug_tx(signature: str):
    """Fetch raw Helius data for a specific transaction signature.

    Shows all nativeTransfers and tokenTransfers regardless of address filtering.
    Example: /debug/tx/3kJCX2By7EFBs...
    """
    import httpx
    url = "https://api.helius.xyz/v0/transactions"
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


@_debug_router.get("/swap-analysis")
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


@_debug_router.get("/disposals/{coin}/{year}")
def debug_disposals(coin: str, year: int, db: Session = Depends(get_db)):
    """Show current disposals + transactions that would generate disposals for a coin/year.

    Example: /debug/disposals/ETH/2025
    """
    from datetime import datetime

    from kryptoskatt.models.disposal import Disposal as DisposalModel
    from kryptoskatt.models.transfer_link import TransferLink

    year_start = datetime(year, 1, 1, tzinfo=UTC)
    year_end = datetime(year + 1, 1, 1, tzinfo=UTC)

    # Current disposals in DB for this coin/year
    current = db.execute(
        select(DisposalModel).where(
            DisposalModel.coin == coin,
            DisposalModel.tax_year == year,
        ).order_by(DisposalModel.sell_timestamp)
    ).scalars().all()

    # Transactions that would produce disposals: SELL, SWAP_OUT, unlinked TRANSFER_OUT
    linked_tx_ids: set[int] = {
        row[0] for row in db.execute(
            select(TransferLink.tx_out_id).where(TransferLink.tx_out_id.isnot(None))
        ).all()
    }

    disposal_types = ("SELL", "SWAP_OUT", "TRANSFER_OUT")
    rows = db.execute(
        select(Transaction).where(
            Transaction.base_coin == coin,
            Transaction.event_type.in_(disposal_types),
            Transaction.is_duplicate.is_(False),
            Transaction.timestamp_utc >= year_start,
            Transaction.timestamp_utc < year_end,
        ).order_by(Transaction.timestamp_utc)
    ).scalars().all()

    from decimal import Decimal as _Dec
    disposal_txs = []
    for tx in rows:
        is_linked = tx.id in linked_tx_ids
        amount = _Dec(str(tx.base_amount or 0))
        price = _Dec(str(tx.price_sek or 0))
        disposal_txs.append({
            "id": tx.id,
            "date": str(tx.timestamp_utc.date()),
            "event_type": tx.event_type,
            "amount": str(amount),
            "proceeds_sek": str(amount * price),
            "tx_hash": tx.tx_hash,
            "from_address": tx.from_address,
            "to_address": tx.to_address,
            "wallet_id": tx.wallet_id,
            "source": tx.source_platform,
            "is_linked_transfer": is_linked,
        })

    return JSONResponse({
        "coin": coin,
        "year": year,
        "disposals_in_db": len(current),
        "total_proceeds_in_db": str(sum(d.proceeds_sek for d in current)),
        "disposal_transactions": len(disposal_txs),
        "transactions": disposal_txs,
    })


@_debug_router.get("/cross-chain-dupes")
def debug_cross_chain_dupes(db: Session = Depends(get_db)):
    """Find tx_hashes that exist with multiple base_coins — indicates cross-chain contamination.

    This happens when the same EVM address is registered for both ETH and POLYGON (or other EVM
    chains) and a bridge/swap transaction appears in Etherscan results for both chains with
    different native coins (ETH vs POL), inflating K4 totals.

    Example: /debug/cross-chain-dupes
    """
    from sqlalchemy import text as sa_text

    # Find tx_hashes that have rows with more than one distinct base_coin
    dupe_hashes = db.execute(sa_text("""
        SELECT tx_hash, COUNT(DISTINCT base_coin) AS coin_count,
               string_agg(DISTINCT base_coin, ',') AS coins
        FROM transactions
        WHERE tx_hash IS NOT NULL
        GROUP BY tx_hash
        HAVING COUNT(DISTINCT base_coin) > 1
        ORDER BY coin_count DESC
    """)).fetchall()

    result = []
    for row in dupe_hashes:
        tx_hash, coin_count, coins = row
        rows = db.execute(
            select(Transaction).where(Transaction.tx_hash == tx_hash)
        ).scalars().all()
        result.append({
            "tx_hash": tx_hash,
            "coins": coins,
            "rows": [
                {
                    "id": t.id,
                    "base_coin": t.base_coin,
                    "base_amount": str(t.base_amount),
                    "event_type": t.event_type,
                    "source": t.source_platform,
                    "wallet_id": t.wallet_id,
                    "from_address": t.from_address,
                    "is_duplicate": t.is_duplicate,
                }
                for t in rows
            ],
        })

    return JSONResponse({
        "cross_chain_dupes": len(result),
        "note": "These tx_hashes have rows with >1 base_coin. The wrong-chain version inflates K4.",
        "items": result,
    })


@_debug_router.delete("/transactions/{tx_id}")
def debug_delete_transaction(tx_id: int, db: Session = Depends(get_db)):
    """Delete a single transaction by ID. Use to remove cross-chain contamination.

    Example: DELETE /debug/transactions/1412
    """
    from kryptoskatt.models.transfer_link import TransferLink
    tx = db.get(Transaction, tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail=f"Transaction {tx_id} not found")
    # Remove any transfer links first
    db.query(TransferLink).filter(
        (TransferLink.tx_out_id == tx_id) | (TransferLink.tx_in_id == tx_id)
    ).delete(synchronize_session=False)
    db.delete(tx)
    db.commit()
    return JSONResponse({"deleted": tx_id})


@_debug_router.get("/multi-chain-wallets")
def debug_multi_chain_wallets(db: Session = Depends(get_db)):
    """Show wallets registered on multiple EVM chains with the same address.

    EVM chains (ETH/POLYGON/BNB/BASE/ARBITRUM) share the same address format.
    Registering the same address on multiple chains causes tx_hashes to be stored
    with wrong base_coins (e.g. a POL tx stored as ETH), inflating K4 totals.

    Returns which chains each duplicated address is registered on, and how many
    transactions exist per chain so you can decide which one to keep.

    Example: /debug/multi-chain-wallets
    """
    from collections import defaultdict

    from kryptoskatt.services.wallet import EVM_CHAINS

    all_evm_wallets = db.query(Wallet).filter(Wallet.chain.in_(list(EVM_CHAINS))).all()

    by_address: dict[str, list[Wallet]] = defaultdict(list)
    for w in all_evm_wallets:
        by_address[w.address.lower()].append(w)

    dupes = {addr: wallets for addr, wallets in by_address.items() if len(wallets) > 1}

    result = []
    for addr, wallets in sorted(dupes.items()):
        chains_info = []
        for w in wallets:
            tx_count = db.query(Transaction).filter(
                Transaction.wallet_id == w.id
            ).count()
            # Also count by from_address since older fetches didn't set wallet_id
            addr_tx_count = db.query(Transaction).filter(
                Transaction.from_address.ilike(addr),
                Transaction.source_platform.ilike(f"%{w.chain[:3]}%"),
            ).count()
            chains_info.append({
                "wallet_id": w.id,
                "chain": w.chain,
                "label": w.label,
                "category": w.category,
                "tx_count_by_wallet_id": tx_count,
                "tx_count_by_source": addr_tx_count,
            })
        result.append({
            "address": addr,
            "chains": chains_info,
            "recommendation": "Ta bort alla utom EN kedja. Håll kvar den kedja du faktiskt vill tracka.",
        })

    return JSONResponse({
        "evm_multi_chain_wallets": len(dupes),
        "note": "Samma adress på >1 EVM-kedja → dubbla transaktioner med fel native coin",
        "wallets": result,
    })


# Mount the debug router only when explicitly enabled.
if settings.debug_mode:
    app.include_router(_debug_router)
    logger.warning("Debug routes enabled — ensure DEBUG_MODE=false in production")


# ── Onboarding routes ──────────────────────────────────────────────────────────

_BASE58_ALPHABET = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def _is_base58(s: str) -> bool:
    return all(c in _BASE58_ALPHABET for c in s)


def _detect_chain_for_address(address: str) -> str:
    """Best-effort chain detection from address format.

    Returns a Chain value string (e.g. "ETHEREUM", "BITCOIN", "SOLANA").
    Falls back to "UNKNOWN" when the format is not recognised.
    """
    addr = address.strip()

    # 0x-prefixed: EVM addresses are 42 chars (0x + 40 hex), tx hashes are 66 chars
    if addr.startswith("0x"):
        if len(addr) == 42:
            return "ETHEREUM"
        # 66-char 0x string is a tx hash — not an address, skip
        return "UNKNOWN"

    # Kadena k: and w: accounts
    if addr.startswith("k:") or addr.startswith("w:"):
        return "KADENA"

    # TRON: T + 33 base58 chars = 34 total
    if addr.startswith("T") and len(addr) == 34 and _is_base58(addr):
        return "TRON"

    # XRP/Ripple: r + 24–34 base58 chars
    if addr.startswith("r") and 25 <= len(addr) <= 35 and _is_base58(addr):
        return "RIPPLE"

    # Bitcoin bech32 (native SegWit)
    if addr.startswith("bc1"):
        return "BITCOIN"

    # Bitcoin legacy / P2SH
    if addr[0] in "13" and 25 <= len(addr) <= 34 and _is_base58(addr):
        return "BITCOIN"

    # Solana: base58, length 43–44
    if len(addr) in (43, 44) and _is_base58(addr):
        return "SOLANA"

    return "UNKNOWN"


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding_step1(
    request: Request,
    error: str = "",
    account: Account = Depends(get_current_account_for_html),
):
    """Onboarding step 1: paste addresses."""
    return templates.TemplateResponse(
        request,
        "onboarding/step1.html",
        {"error": error, "account": account},
    )


# EVM-kompatibla kedjor som delar adressformat (0x..., 42 tecken)
_EVM_CHAINS = ["ETHEREUM", "BASE", "POLYGON", "ARBITRUM", "BNB"]


@app.post("/onboarding/addresses", response_class=HTMLResponse)
async def onboarding_addresses(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Parse pasted addresses and show review step."""
    form = await request.form()
    raw = (form.get("addresses") or "").strip()
    if not raw:
        return RedirectResponse("/onboarding?error=Inga+adresser+angivna", status_code=303)

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return RedirectResponse("/onboarding?error=Inga+adresser+hittades", status_code=303)

    parsed = []
    for addr in lines:
        chain = _detect_chain_for_address(addr)
        is_evm = chain == "ETHEREUM"
        parsed.append({"address": addr, "chain": chain, "is_evm": is_evm})

    non_evm_chains = [c.value for c in Chain if c != Chain.UNKNOWN and c.value not in _EVM_CHAINS]
    from kryptoskatt.models.custom_chain_config import CustomChainConfig
    user_custom_chains = (
        db.query(CustomChainConfig)
        .filter(CustomChainConfig.account_id == account.id)
        .order_by(CustomChainConfig.chain_name)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "onboarding/step2.html",
        {
            "addresses": parsed,
            "evm_chains": _EVM_CHAINS,
            "non_evm_chains": non_evm_chains,
            "custom_chains": user_custom_chains,
            "account": account,
        },
    )


@app.post("/onboarding/confirm")
async def onboarding_confirm(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Save confirmed wallets and redirect to status page."""
    form = await request.form()
    count = int(form.get("count") or 0)

    service = WalletService(db, account.id)
    saved = 0
    skipped = 0
    failed = 0

    for i in range(count):
        address = (form.get(f"address_{i}") or "").strip()
        label = (form.get(f"label_{i}") or "").strip()
        is_evm = form.get(f"is_evm_{i}") == "1"

        if not address:
            continue

        if is_evm:
            # Save one wallet per checked EVM chain
            for chain in _EVM_CHAINS:
                if form.get(f"evm_{chain}_{i}"):
                    try:
                        service.add_wallet(WalletCreate(
                            address=address, chain=chain,
                            label=label, is_mine=True, category="own",
                        ), strict_validation=False)
                        saved += 1
                    except Exception as exc:
                        db.rollback()
                        if "already exists" in str(exc):
                            skipped += 1
                        else:
                            logger.warning("add_wallet failed for %s/%s: %s", address, chain, exc)
                            failed += 1
        else:
            chain = (form.get(f"chain_{i}") or "ETHEREUM").strip()
            try:
                service.add_wallet(WalletCreate(
                    address=address, chain=chain,
                    label=label, is_mine=True, category="own",
                ), strict_validation=False)
                saved += 1
            except Exception as exc:
                db.rollback()
                if "already exists" in str(exc):
                    skipped += 1
                else:
                    logger.warning("add_wallet failed for %s/%s: %s", address, chain, exc)
                    failed += 1

    from urllib.parse import urlencode
    params: dict = {"saved": saved, "skipped": skipped, "failed": failed}
    return RedirectResponse(f"/onboarding/status?{urlencode(params)}", status_code=303)


@app.get("/onboarding/status", response_class=HTMLResponse)
def onboarding_status(
    request: Request,
    saved: int = 0,
    skipped: int = 0,
    failed: int = 0,
    account: Account = Depends(get_current_account_for_html),
):
    """Onboarding step 3: show import status."""
    return templates.TemplateResponse(
        request,
        "onboarding/step3.html",
        {"saved": saved, "skipped": skipped, "failed": failed, "account": account},
    )
