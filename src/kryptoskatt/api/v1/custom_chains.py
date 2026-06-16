"""Custom chain config endpoints for API v1."""

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from kryptoskatt.api.schemas import CustomChainConfigCreate, CustomChainConfigRead
from kryptoskatt.models.account import Account
from kryptoskatt.models.custom_chain_config import CustomChainConfig
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
def list_custom_chains(
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    chains = db.query(CustomChainConfig).filter(CustomChainConfig.account_id == account.id).all()
    return {"chains": [CustomChainConfigRead.model_validate(c) for c in chains]}


@router.post("", response_model=CustomChainConfigRead, status_code=201)
def create_custom_chain(
    body: CustomChainConfigCreate,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    from datetime import datetime

    # SSRF guard: a Blockscout explorer_url is fetched server-side, so reject
    # URLs that resolve to internal/non-public addresses before storing them.
    if body.adapter_type == "blockscout":
        from kryptoskatt.utils.url_guard import UnsafeURLError, validate_outbound_url

        try:
            validate_outbound_url(body.explorer_url)
        except UnsafeURLError as exc:
            raise HTTPException(status_code=400, detail=f"Unsafe explorer_url: {exc}")

    existing = db.query(CustomChainConfig).filter(
        CustomChainConfig.account_id == account.id,
        CustomChainConfig.chain_name == body.chain_name,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Chain name already exists for this account")
    chain = CustomChainConfig(
        account_id=account.id,
        chain_name=body.chain_name,
        explorer_url=body.explorer_url,
        api_key=body.api_key,
        adapter_type=body.adapter_type,
        native_coin=body.native_coin,
        chain_id=body.chain_id,
        created_at=datetime.now(UTC),
    )
    db.add(chain)
    db.commit()
    db.refresh(chain)
    return CustomChainConfigRead.model_validate(chain)


@router.delete("/{chain_id}")
def delete_custom_chain(
    chain_id: int,
    db: Session = Depends(_get_db),
    account: Account = Depends(get_current_account),
):
    chain = db.query(CustomChainConfig).filter(
        CustomChainConfig.id == chain_id,
        CustomChainConfig.account_id == account.id,
    ).first()
    if not chain:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(chain)
    db.commit()
    return {"ok": True}
