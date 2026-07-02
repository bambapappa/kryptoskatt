"""T2 manual cost entry endpoints for API v1."""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kryptoskatt.db import get_db
from kryptoskatt.models.account import Account
from kryptoskatt.models.t2_manual_entry import T2ManualEntry
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


_get_db = get_db


class T2EntryCreate(BaseModel):
    year: int
    description: str
    amount_sek: Decimal
    entry_date: date | None = None
    vendor: str | None = None


@router.get("")
def list_t2_entries(
    year: int | None = None,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """List manual T2 cost entries, optionally filtered by year."""
    q = db.query(T2ManualEntry).filter(T2ManualEntry.user_id == account.id)
    if year is not None:
        q = q.filter(T2ManualEntry.tax_year == year)
    entries = q.order_by(T2ManualEntry.tax_year, T2ManualEntry.entry_date, T2ManualEntry.id).all()
    return {
        "entries": [
            {
                "id": e.id,
                "year": e.tax_year,
                "entry_date": e.entry_date.isoformat() if e.entry_date else None,
                "description": e.description,
                "amount_sek": str(e.amount_sek),
                "vendor": e.vendor,
            }
            for e in entries
        ]
    }


@router.post("", status_code=201)
def create_t2_entry(
    body: T2EntryCreate,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Create a new manual T2 cost entry."""
    if not body.description.strip():
        raise HTTPException(status_code=422, detail="description must not be empty")
    if body.amount_sek <= 0:
        raise HTTPException(status_code=422, detail="amount_sek must be positive")

    entry = T2ManualEntry(
        user_id=account.id,
        tax_year=body.year,
        entry_date=body.entry_date,
        description=body.description.strip(),
        amount_sek=body.amount_sek,
        vendor=body.vendor,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    return {
        "id": entry.id,
        "year": entry.tax_year,
        "entry_date": entry.entry_date.isoformat() if entry.entry_date else None,
        "description": entry.description,
        "amount_sek": str(entry.amount_sek),
        "vendor": entry.vendor,
    }


@router.delete("/{entry_id}")
def delete_t2_entry(
    entry_id: int,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Delete a manual T2 cost entry by id."""
    entry = db.query(T2ManualEntry).filter(
        T2ManualEntry.id == entry_id,
        T2ManualEntry.user_id == account.id,
    ).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    db.delete(entry)
    db.commit()
    return {"ok": True, "deleted_id": entry_id}
