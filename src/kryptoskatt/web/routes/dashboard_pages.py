"""Dashboard and wallet overview pages."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import Integer, case, extract, func, select
from sqlalchemy.orm import Session

from kryptoskatt.chains import get_registry_for_user
from kryptoskatt.enums import Chain
from kryptoskatt.models.account import Account
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.wallet import Wallet
from kryptoskatt.web.deps import get_current_account_for_html, get_db
from kryptoskatt.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/wallets", response_class=HTMLResponse)
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


@router.get("/", response_class=HTMLResponse)
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

