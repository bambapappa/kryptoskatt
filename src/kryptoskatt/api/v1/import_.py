"""Import endpoint for API v1 — accepts multipart/form-data file uploads."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from kryptoskatt.cli.import_cmd import (
    create_import_batch,
    detect_platform,
    parse_file,
    save_transactions,
)
from kryptoskatt.db import get_db
from kryptoskatt.engine.dedup import DeduplicationEngine
from kryptoskatt.models.account import Account
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


_get_db = get_db


@router.post("")
async def import_file(
    file: UploadFile = File(...),
    platform: str | None = Form(default=None),
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """Import a transaction CSV/TSV file.

    Accepts multipart/form-data with:
    - file: the CSV or TSV file
    - platform (optional): coinbase | crypto_com | ledger | mexc
                           Auto-detected from file content when omitted.

    Returns saved/skipped counts and any parse errors.
    """
    raw = await file.read()

    # Write to a named temp file so parsers can read it by path
    suffix = Path(file.filename or "upload").suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)

    try:
        resolved_platform = platform

        if not resolved_platform:
            try:
                lines = raw.decode("utf-8", errors="replace").splitlines()[:10]
                resolved_platform = detect_platform(tmp_path, lines)
            except Exception as exc:
                raise HTTPException(
                    status_code=422, detail=f"Could not auto-detect platform: {exc}"
                ) from exc

        resolved_platform = resolved_platform.lower()

        try:
            transactions, errors = parse_file(tmp_path, resolved_platform)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Parse error: {exc}") from exc

        batch = create_import_batch(
            session=db,
            platform=resolved_platform,
            filename=file.filename or tmp_path.name,
            row_count=len(transactions),
            error_count=len(errors),
            user_id=account.id,
        )

        saved = save_transactions(db, transactions, batch, user_id=account.id)
        skipped = len(transactions) - saved

        # Run deduplication so any cross-platform duplicates are flagged immediately
        dedup = DeduplicationEngine(db, account.id)
        dedup.deduplicate_all()

        return {
            "saved": saved,
            "skipped": skipped,
            "errors": errors,
        }
    finally:
        tmp_path.unlink(missing_ok=True)
