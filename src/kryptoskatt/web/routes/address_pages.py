"""Unknown address management: spam marking, registration, auto-tagging."""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from kryptoskatt.config import settings
from kryptoskatt.enums import Chain
from kryptoskatt.models.account import Account
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.wallet import Wallet
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.wallet import WalletService
from kryptoskatt.web.deps import get_current_account_for_html, get_db
from kryptoskatt.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/addresses", response_class=HTMLResponse)
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


@router.post("/addresses/mark-spam")
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


@router.post("/addresses/tag-null-transfers")
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


@router.post("/addresses/register")
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


@router.post("/addresses/bulk-register")
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


@router.post("/addresses/auto-tag")
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

