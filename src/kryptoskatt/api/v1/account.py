"""Account-level endpoints: GDPR data export and account deletion."""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kryptoskatt.db import get_db
from kryptoskatt.models.account import Account
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


_get_db = get_db


class DeleteAccountRequest(BaseModel):
    confirm: str


@router.get("/export")
def export_account_data(
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Export all account data as JSON for GDPR data portability."""
    from kryptoskatt.services.account_deletion import export_account_data as _export

    data = _export(db, account)

    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"kryptoskatt-export-{account.account_id[:8]}.json"
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("")
def delete_account(
    body: DeleteAccountRequest,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Permanently delete the account and all associated data (GDPR right to erasure)."""
    if body.confirm != "DELETE MY ACCOUNT":
        raise HTTPException(
            status_code=400,
            detail="Confirmation string does not match. Send {\"confirm\": \"DELETE MY ACCOUNT\"}.",
        )

    from kryptoskatt.services.account_deletion import delete_account_data

    delete_account_data(db, account.id)

    return {"ok": True}
