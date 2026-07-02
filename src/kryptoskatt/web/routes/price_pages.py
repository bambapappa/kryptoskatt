"""Price management pages: manual prices, CoinGecko cache, coin blacklist."""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.services.price import PriceService
from kryptoskatt.web.deps import get_current_account_for_html, get_db
from kryptoskatt.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/prices", response_class=HTMLResponse)
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
        request,
        "prices.html",
        {
            "manual_prices": manual,
            "coingecko_summary": coingecko_summary,
            "blacklist": blacklist,
            "result": request.query_params.get("result"),
            "account": account,
        },
    )


@router.post("/prices/manual")
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


@router.post("/prices/manual/delete")
def prices_manual_delete(
    price_id: int = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Delete a manual price entry."""
    from kryptoskatt.models.price_cache import PriceCache

    entry = db.query(PriceCache).filter(PriceCache.id == price_id).first()
    if entry:
        db.delete(entry)
        db.commit()
        msg = "ok:Pris borttaget"
    else:
        msg = "error:Posten hittades inte"
    return RedirectResponse(f"/prices?result={msg}", status_code=303)


@router.post("/prices/blacklist/add")
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
        CoinBlacklist.user_id == account.id, CoinBlacklist.coin_symbol == symbol
    ).first()
    if existing:
        msg = f"error:{symbol} finns redan i listan"
    else:
        db.add(CoinBlacklist(user_id=account.id, coin_symbol=symbol, reason=reason.strip() or None))
        db.commit()
        msg = f"ok:{symbol} ignoreras nu i beräkningar"
    return RedirectResponse(f"/prices?result={msg}", status_code=303)


@router.post("/prices/blacklist/delete")
def prices_blacklist_delete(
    entry_id: int = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Remove a coin from the blacklist."""
    from kryptoskatt.models.coin_blacklist import CoinBlacklist

    entry = db.query(CoinBlacklist).filter(
        CoinBlacklist.id == entry_id, CoinBlacklist.user_id == account.id
    ).first()
    if entry:
        db.delete(entry)
        db.commit()
        msg = "ok:Coin borttagen från listan"
    else:
        msg = "error:Posten hittades inte"
    return RedirectResponse(f"/prices?result={msg}", status_code=303)

