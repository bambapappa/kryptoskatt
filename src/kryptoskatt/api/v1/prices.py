"""Price import endpoints for API v1."""

import csv
import logging
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from kryptoskatt.db import get_db
from kryptoskatt.enums import PriceSource
from kryptoskatt.models.account import Account
from kryptoskatt.models.price_cache import PriceCache
from kryptoskatt.services.price_history_importer import PriceHistoryImporter
from kryptoskatt.web.auth import get_current_account

logger = logging.getLogger(__name__)

router = APIRouter()


_get_db = get_db


@router.post("/import-history")
async def import_price_history(
    file: UploadFile,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Import historical price data from a CoinGecko or CoinMarketCap CSV file.

    The filename is used to detect which coin the prices belong to.
    Prices are converted from USD to SEK via Riksbanken historical rates.
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / file.filename
        tmp_path.write_bytes(content)

        importer = PriceHistoryImporter(db)
        result = importer.import_directory(Path(tmpdir))

    if result.errors and result.rows_inserted == 0:
        raise HTTPException(status_code=422, detail="; ".join(result.errors))

    return {"imported": result.rows_inserted, "skipped": result.rows_skipped, "errors": result.errors}


@router.post("/upload-manual")
async def upload_manual_prices(
    file: UploadFile,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Upload a manual price CSV (coin_id, date, price_sek) and store with MANUAL source.

    Expected CSV format (comma-separated, with header):
        coin_id,date,price_sek
        BTC,2024-01-15,450000.00

    coin_id is the cache key (CoinGecko coin_id or uppercase symbol).
    price_sek is the SEK price directly (no USD conversion needed).
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = (await file.read()).decode("utf-8-sig").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    reader = csv.DictReader(StringIO(content))
    required_fields = {"coin_id", "date", "price_sek"}
    if not reader.fieldnames or not required_fields.issubset(set(reader.fieldnames)):
        raise HTTPException(
            status_code=422,
            detail=f"CSV must have headers: {', '.join(sorted(required_fields))}",
        )

    existing = {
        (r.coin_id, r.date)
        for r in db.query(PriceCache.coin_id, PriceCache.date).all()
    }

    imported = 0
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):
        try:
            coin_id = row["coin_id"].strip()
            price_date = date.fromisoformat(row["date"].strip())
            price_sek = Decimal(row["price_sek"].strip())
            if price_sek <= 0:
                raise ValueError("price_sek must be positive")
        except (ValueError, InvalidOperation, KeyError) as exc:
            errors.append(f"Row {i}: {exc}")
            continue

        if (coin_id, price_date) in existing:
            continue

        db.add(PriceCache(
            coin_id=coin_id,
            date=price_date,
            price_sek=price_sek,
            source=PriceSource.MANUAL.value,
        ))
        existing.add((coin_id, price_date))
        imported += 1

    db.commit()
    return {"imported": imported, "errors": errors}
