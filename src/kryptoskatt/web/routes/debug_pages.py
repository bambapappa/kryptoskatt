"""Debug routes - only mounted when DEBUG_MODE=true. Never enable in production."""

import logging
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from kryptoskatt.config import settings
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.wallet import Wallet
from kryptoskatt.web.deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/coin/{coin}/transfers")
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


@router.get("/t2/{year}")
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


@router.get("/tx/{signature}")
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


@router.get("/swap-analysis")
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


@router.get("/disposals/{coin}/{year}")
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


@router.get("/cross-chain-dupes")
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


@router.delete("/transactions/{tx_id}")
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


@router.get("/multi-chain-wallets")
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

