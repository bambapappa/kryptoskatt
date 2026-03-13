"""Transaction/disposal listing endpoint for API v1."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.web.auth import get_current_account

router = APIRouter()


def _get_db():
    from kryptoskatt.db import get_session
    s = get_session()
    try:
        yield s
    finally:
        s.close()


@router.get("")
def list_transactions(
    year: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    """List disposals for the authenticated user, optionally filtered by tax year."""
    filters = [Disposal.user_id == account.id]
    if year is not None:
        filters.append(Disposal.tax_year == year)

    count_stmt = select(func.count(Disposal.id)).where(*filters)
    total = db.execute(count_stmt).scalar() or 0

    offset = (page - 1) * page_size
    stmt = (
        select(Disposal)
        .where(*filters)
        .order_by(Disposal.sell_timestamp)
        .offset(offset)
        .limit(page_size)
    )
    disposals = db.execute(stmt).scalars().all()

    return {
        "transactions": [
            {
                "id": d.id,
                "tax_year": d.tax_year,
                "coin": d.coin,
                "sell_timestamp": d.sell_timestamp,
                "sell_amount": str(d.sell_amount),
                "proceeds_sek": str(d.proceeds_sek),
                "cost_basis_sek": str(d.cost_basis_sek),
                "gain_loss_sek": str(d.proceeds_sek - d.cost_basis_sek),
            }
            for d in disposals
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
