"""Onboarding flow: paste addresses, review, confirm."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from kryptoskatt.enums import Chain
from kryptoskatt.models.account import Account
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.wallet import WalletService
from kryptoskatt.web.deps import get_current_account_for_html, get_db
from kryptoskatt.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Onboarding routes ──────────────────────────────────────────────────────────

_BASE58_ALPHABET = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def _is_base58(s: str) -> bool:
    return all(c in _BASE58_ALPHABET for c in s)


def _detect_chain_for_address(address: str) -> str:
    """Best-effort chain detection from address format.

    Returns a Chain value string (e.g. "ETHEREUM", "BITCOIN", "SOLANA").
    Falls back to "UNKNOWN" when the format is not recognised.
    """
    addr = address.strip()

    # 0x-prefixed: EVM addresses are 42 chars (0x + 40 hex), tx hashes are 66 chars
    if addr.startswith("0x"):
        if len(addr) == 42:
            return "ETHEREUM"
        # 66-char 0x string is a tx hash — not an address, skip
        return "UNKNOWN"

    # Kadena k: and w: accounts
    if addr.startswith("k:") or addr.startswith("w:"):
        return "KADENA"

    # TRON: T + 33 base58 chars = 34 total
    if addr.startswith("T") and len(addr) == 34 and _is_base58(addr):
        return "TRON"

    # XRP/Ripple: r + 24–34 base58 chars
    if addr.startswith("r") and 25 <= len(addr) <= 35 and _is_base58(addr):
        return "RIPPLE"

    # Bitcoin bech32 (native SegWit)
    if addr.startswith("bc1"):
        return "BITCOIN"

    # Bitcoin legacy / P2SH
    if addr[0] in "13" and 25 <= len(addr) <= 34 and _is_base58(addr):
        return "BITCOIN"

    # Solana: base58, length 43–44
    if len(addr) in (43, 44) and _is_base58(addr):
        return "SOLANA"

    return "UNKNOWN"


@router.get("/onboarding", response_class=HTMLResponse)
def onboarding_step1(
    request: Request,
    error: str = "",
    account: Account = Depends(get_current_account_for_html),
):
    """Onboarding step 1: paste addresses."""
    return templates.TemplateResponse(
        request,
        "onboarding/step1.html",
        {"error": error, "account": account},
    )


# EVM-kompatibla kedjor som delar adressformat (0x..., 42 tecken)
_EVM_CHAINS = ["ETHEREUM", "BASE", "POLYGON", "ARBITRUM", "BNB"]


@router.post("/onboarding/addresses", response_class=HTMLResponse)
async def onboarding_addresses(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Parse pasted addresses and show review step."""
    form = await request.form()
    raw = (form.get("addresses") or "").strip()
    if not raw:
        return RedirectResponse("/onboarding?error=Inga+adresser+angivna", status_code=303)

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return RedirectResponse("/onboarding?error=Inga+adresser+hittades", status_code=303)

    parsed = []
    for addr in lines:
        chain = _detect_chain_for_address(addr)
        is_evm = chain == "ETHEREUM"
        parsed.append({"address": addr, "chain": chain, "is_evm": is_evm})

    non_evm_chains = [c.value for c in Chain if c != Chain.UNKNOWN and c.value not in _EVM_CHAINS]
    from kryptoskatt.models.custom_chain_config import CustomChainConfig
    user_custom_chains = (
        db.query(CustomChainConfig)
        .filter(CustomChainConfig.account_id == account.id)
        .order_by(CustomChainConfig.chain_name)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "onboarding/step2.html",
        {
            "addresses": parsed,
            "evm_chains": _EVM_CHAINS,
            "non_evm_chains": non_evm_chains,
            "custom_chains": user_custom_chains,
            "account": account,
        },
    )


@router.post("/onboarding/confirm")
async def onboarding_confirm(
    request: Request,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account_for_html),
):
    """Save confirmed wallets and redirect to status page."""
    form = await request.form()
    count = int(form.get("count") or 0)

    service = WalletService(db, account.id)
    saved = 0
    skipped = 0
    failed = 0

    for i in range(count):
        address = (form.get(f"address_{i}") or "").strip()
        label = (form.get(f"label_{i}") or "").strip()
        is_evm = form.get(f"is_evm_{i}") == "1"

        if not address:
            continue

        if is_evm:
            # Save one wallet per checked EVM chain
            for chain in _EVM_CHAINS:
                if form.get(f"evm_{chain}_{i}"):
                    try:
                        service.add_wallet(WalletCreate(
                            address=address, chain=chain,
                            label=label, is_mine=True, category="own",
                        ), strict_validation=False)
                        saved += 1
                    except Exception as exc:
                        db.rollback()
                        if "already exists" in str(exc):
                            skipped += 1
                        else:
                            logger.warning("add_wallet failed for %s/%s: %s", address, chain, exc)
                            failed += 1
        else:
            chain = (form.get(f"chain_{i}") or "ETHEREUM").strip()
            try:
                service.add_wallet(WalletCreate(
                    address=address, chain=chain,
                    label=label, is_mine=True, category="own",
                ), strict_validation=False)
                saved += 1
            except Exception as exc:
                db.rollback()
                if "already exists" in str(exc):
                    skipped += 1
                else:
                    logger.warning("add_wallet failed for %s/%s: %s", address, chain, exc)
                    failed += 1

    from urllib.parse import urlencode
    params: dict = {"saved": saved, "skipped": skipped, "failed": failed}
    return RedirectResponse(f"/onboarding/status?{urlencode(params)}", status_code=303)


@router.get("/onboarding/status", response_class=HTMLResponse)
def onboarding_status(
    request: Request,
    saved: int = 0,
    skipped: int = 0,
    failed: int = 0,
    account: Account = Depends(get_current_account_for_html),
):
    """Onboarding step 3: show import status."""
    return templates.TemplateResponse(
        request,
        "onboarding/step3.html",
        {"saved": saved, "skipped": skipped, "failed": failed, "account": account},
    )
