"""Price import endpoints for API v1."""

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from kryptoskatt.db import get_db
from kryptoskatt.models.account import Account
from kryptoskatt.services.price import PriceService
from kryptoskatt.utils.uploads import read_upload
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


_get_db = get_db


@router.post("/upload-manual")
async def upload_manual_prices(
    file: UploadFile,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Upload the account's own manual prices from CSV (coin_id, date, price_sek).

    Expected CSV format (comma-separated, with header):
        coin_id,date,price_sek
        BTC,2024-01-15,450000.00

    coin_id is the coin symbol as it appears on your transactions (e.g. BTC).
    Prices are private to the account and override public price sources.
    price_sek is the SEK price directly (no USD conversion needed).
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = (await read_upload(file)).decode("utf-8-sig").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    reader = csv.DictReader(StringIO(content))
    fields = set(reader.fieldnames or [])
    required_fields = {"coin_id", "date", "price_sek"}
    if not ({"date", "price_sek"} <= fields and fields & {"coin", "coin_id"}):
        raise HTTPException(
            status_code=422,
            detail=f"CSV must have headers: {', '.join(sorted(required_fields))}",
        )

    service = PriceService(db)
    imported = 0
    errors: list[str] = []

    for i, row in enumerate(reader, start=2):
        try:
            symbol = (row.get("coin") or row.get("coin_id") or "").strip().upper()
            price_date = date.fromisoformat(row["date"].strip())
            price_sek = Decimal(row["price_sek"].strip())
            if not symbol or price_sek <= 0:
                raise ValueError("coin_id required and price_sek must be positive")
        except (ValueError, InvalidOperation, KeyError) as exc:
            errors.append(f"Row {i}: {exc}")
            continue
        service.save_manual_price(symbol, price_date, price_sek, account.id, commit=False)
        imported += 1

    db.commit()
    return {"imported": imported, "errors": errors}
