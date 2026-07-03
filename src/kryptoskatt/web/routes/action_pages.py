"""Actions dashboard: import, on-chain fetch, calculation and wallet management."""

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

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
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.wallet import Wallet
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.price import PriceService
from kryptoskatt.services.price_history_importer import PriceHistoryImporter
from kryptoskatt.services.wallet import WalletService
from kryptoskatt.web.deps import get_current_account_for_html, get_db
from kryptoskatt.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()

# Chains that require an API key: maps chain -> (key_name, key_value)
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


@router.get("/actions", response_class=HTMLResponse)
def actions_dashboard(
    request: Request,
    result: str = "",
    job: str = "",
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
        {"result": result, "job_id": job, "wallets": wallets, "chains": chains, "account": account},
    )


@router.get("/actions/jobs/{job_id}")
def actions_job_status(
    job_id: str,
    account: Account = Depends(get_current_account_for_html),
):
    """Poll status for a background job owned by the current account."""
    from kryptoskatt.services.jobs import job_manager

    job = job_manager.get(job_id, account.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse({
        "id": job.id,
        "name": job.name,
        "status": job.status,
        "message": job.message,
    })


@router.post("/actions/import")
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

@router.get("/import", response_class=HTMLResponse)
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


@router.post("/import")
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


@router.post("/actions/fetch")
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


@router.post("/actions/refetch")
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


def _run_fetch_all_job(job, uid: int) -> str:
    """Fetch all wallets — runs in a background thread with its own DB session."""
    db = get_session()
    try:
        wallet_service = WalletService(db, uid)
        wallets = wallet_service.list_wallets(mine_only=True)
        if not wallets:
            raise RuntimeError("Inga plånböcker registrerade — lägg till adresser först")

        registry = get_registry_for_user(db, uid)
        total_saved = 0
        total_skipped = 0
        errors: list[str] = []

        for i, wallet in enumerate(wallets, start=1):
            job.message = f"Hämtar plånbok {i}/{len(wallets)}: {wallet.address[:16]}… på {wallet.chain}"

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

        msg = f"Hämtade {total_saved} nya transaktioner från {len(wallets)} plånböcker"
        if total_skipped:
            msg += f" ({total_skipped} redan importerade hoppades över)"
        if errors:
            msg += " — fel: " + "; ".join(errors[:3])
            if len(errors) > 3:
                msg += f" (+{len(errors) - 3} till)"
        return msg
    finally:
        db.close()


@router.post("/actions/fetch-all")
def actions_fetch_all(account: Account = Depends(get_current_account_for_html)):
    """Start a background job fetching transactions for all registered wallets."""
    from kryptoskatt.services.jobs import job_manager

    uid = account.id
    job = job_manager.start(uid, "fetch-all", lambda j: _run_fetch_all_job(j, uid))
    if job is None:
        return RedirectResponse(
            "/actions?result=error:Ett jobb kör redan — vänta tills det är klart",
            status_code=303,
        )
    return RedirectResponse(f"/actions?job={job.id}", status_code=303)


def _run_calculate_job(job, uid: int, year: int) -> str:
    """Dedup + price enrichment + transfer matching + GAV — background thread, own DB session."""
    db = get_session()
    try:
        job.message = "Avduplicerar transaktioner…"
        DeduplicationEngine(db, uid).deduplicate_all()

        job.message = "Hämtar priser…"
        enrich_report = PriceEnrichmentEngine(db, uid).enrich()

        job.message = "Matchar överföringar…"
        my_addresses = WalletService(db, uid).get_my_addresses()
        TransferMatcher(db, my_addresses, uid).match_all()

        job.message = f"Beräknar GAV för {year}…"
        result = GavEngine(db, uid).calculate(year=year)
        db.commit()

        return (
            f"Beräknade {len(result.disposals)} avyttringar för {year} "
            f"({enrich_report.enriched} priser hämtade)"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/actions/calculate")
def actions_calculate(
    year: int = Form(...),
    account: Account = Depends(get_current_account_for_html),
):
    """Start a background job running dedup + transfer matching + GAV calculation."""
    from kryptoskatt.services.jobs import job_manager

    uid = account.id
    job = job_manager.start(uid, "calculate", lambda j: _run_calculate_job(j, uid, year))
    if job is None:
        return RedirectResponse(
            "/actions?result=error:Ett jobb kör redan — vänta tills det är klart",
            status_code=303,
        )
    return RedirectResponse(f"/actions?job={job.id}", status_code=303)


@router.post("/actions/wallets/add")
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


@router.post("/actions/wallets/bulk-add")
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


@router.post("/actions/wallets/add-xpub")
def actions_wallet_add_xpub(
    xpub: str = Form(...),
    label: str = Form(""),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Derive and register Bitcoin addresses from an xpub/ypub/zpub (gap-limit scan)."""
    service = WalletService(db, account.id)
    try:
        summary = service.import_xpub(xpub.strip(), label=label.strip(), use_network=True)
        msg = (
            f"ok:Registrerade {summary['added']} Bitcoin-adresser från xpub "
            f"({summary['skipped']} fanns redan)"
        )
    except ValueError as e:
        msg = f"error:Ogiltig xpub: {e}"
    except Exception as e:
        logger.exception("xpub import failed")
        msg = f"error:Fel vid xpub-import: {e}"
    return RedirectResponse(f"/actions?result={msg}", status_code=303)


@router.post("/actions/wallets/remove")
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


@router.post("/actions/prices/import-history")
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


@router.post("/actions/prices/upload")
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

@router.post("/transactions/bulk-tag")
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
    updated = (
        db.query(Transaction)
        .filter(Transaction.id.in_(id_list), Transaction.user_id == account.id)
        .all()
    )
    for tx in updated:
        tx.source_platform = tag_clean
    db.commit()
    return RedirectResponse(f"/actions?result=ok:{len(updated)} transaktioner taggades som {tag_clean}", status_code=303)


@router.post("/transactions/classify-reward")
def transactions_classify_reward(
    ids: str = Form(...),
    reward_type: str = Form(...),
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Set reward_type (staking/mining/airdrop/interest/other) on REWARD transactions.

    Feeds the T2 income breakdown so e.g. staking rewards are reported
    separately from mining. Only affects the current account's REWARD rows.
    """
    from kryptoskatt.enums import EventType, RewardType

    rtype = reward_type.strip().lower()
    valid = {r.value for r in RewardType}
    if rtype not in valid:
        return RedirectResponse(
            f"/actions?result=error:Ogiltig belöningstyp (välj: {', '.join(sorted(valid))})",
            status_code=303,
        )
    try:
        id_list = [int(x.strip()) for x in ids.replace("\n", ",").split(",") if x.strip().isdigit()]
    except ValueError:
        return RedirectResponse("/actions?result=error:Ogiltiga ID:n", status_code=303)
    if not id_list:
        return RedirectResponse("/actions?result=error:Inga ID:n angivna", status_code=303)

    updated = (
        db.query(Transaction)
        .filter(
            Transaction.id.in_(id_list),
            Transaction.user_id == account.id,
            Transaction.event_type == EventType.REWARD.value,
        )
        .update({"reward_type": rtype}, synchronize_session=False)
    )
    db.commit()
    return RedirectResponse(
        f"/actions?result=ok:{updated} belöningar klassades som {rtype}", status_code=303
    )

