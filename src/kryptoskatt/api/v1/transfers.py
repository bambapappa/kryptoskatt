"""Transfer link API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.transfer_link import TransferLink
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


def _get_db():
    from kryptoskatt.db import get_session

    s = get_session()
    try:
        yield s
    finally:
        s.close()


class ManualTransferLinkCreate(BaseModel):
    tx_out_id: int
    tx_in_id: int


@router.get("")
def list_transfers(
    year: int | None = None,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """List transfer links for the authenticated user, optionally filtered by year."""
    query = db.query(TransferLink).join(
        Transaction, Transaction.id == TransferLink.tx_out_id
    ).filter(Transaction.user_id == account.id)

    if year is not None:
        from sqlalchemy import extract

        query = query.filter(extract("year", Transaction.timestamp_utc) == year)

    links = query.all()
    return {
        "links": [
            {
                "id": link.id,
                "tx_out_id": link.tx_out_id,
                "tx_in_id": link.tx_in_id,
                "match_method": link.match_method,
                "confidence": str(link.confidence) if link.confidence is not None else None,
                "is_manual": link.match_method == "manual",
            }
            for link in links
        ]
    }


@router.post("/manual", status_code=201)
def create_manual_transfer(
    body: ManualTransferLinkCreate,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Create a manual transfer link between two transactions."""
    # Verify both transactions belong to the authenticated user
    tx_out = db.query(Transaction).filter(
        Transaction.id == body.tx_out_id,
        Transaction.user_id == account.id,
    ).first()
    if tx_out is None:
        raise HTTPException(status_code=404, detail="tx_out not found")

    tx_in = db.query(Transaction).filter(
        Transaction.id == body.tx_in_id,
        Transaction.user_id == account.id,
    ).first()
    if tx_in is None:
        raise HTTPException(status_code=404, detail="tx_in not found")

    # Check for duplicate link
    existing = db.query(TransferLink).filter(
        TransferLink.tx_out_id == body.tx_out_id,
        TransferLink.tx_in_id == body.tx_in_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Transfer link already exists")

    link = TransferLink(
        tx_out_id=body.tx_out_id,
        tx_in_id=body.tx_in_id,
        match_method="manual",
        confidence=None,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    return {
        "id": link.id,
        "tx_out_id": link.tx_out_id,
        "tx_in_id": link.tx_in_id,
        "match_method": link.match_method,
        "confidence": None,
        "is_manual": True,
    }


@router.delete("/{link_id}", status_code=204)
def delete_transfer(
    link_id: int,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Delete a transfer link by ID (must belong to authenticated user's transactions)."""
    link = db.query(TransferLink).join(
        Transaction, Transaction.id == TransferLink.tx_out_id
    ).filter(
        TransferLink.id == link_id,
        Transaction.user_id == account.id,
    ).first()

    if link is None:
        raise HTTPException(status_code=404, detail="Transfer link not found")

    db.delete(link)
    db.commit()
