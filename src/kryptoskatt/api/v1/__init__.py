"""API v1 router aggregation."""

from fastapi import APIRouter

from kryptoskatt import __version__
from kryptoskatt.api.v1 import (
    account as account_module,
)
from kryptoskatt.api.v1 import (
    auth,
    calculate,
    custom_chains,
    fetch,
    issues,
    prices,
    reports,
    t2_entries,
    transactions,
    transfers,
    wallets,
)
from kryptoskatt.api.v1 import (
    import_ as import_module,
)

api_v1_router = APIRouter()


@api_v1_router.get("/health", tags=["meta"])
def health() -> dict:
    """Health check — no auth required."""
    return {"status": "ok", "version": __version__}


@api_v1_router.get("/info", tags=["meta"])
def info() -> dict:
    """Service info — no auth required."""
    from kryptoskatt.chains import get_registry

    registry = get_registry()
    return {
        "version": __version__,
        "supported_chains": sorted(registry.supported_chains()),
        "adapter_types": ["blockscout", "etherscan"],
    }


api_v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_v1_router.include_router(wallets.router, prefix="/wallets", tags=["wallets"])
api_v1_router.include_router(calculate.router, tags=["calculate"])
api_v1_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_v1_router.include_router(custom_chains.router, prefix="/custom-chains", tags=["custom-chains"])
api_v1_router.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
api_v1_router.include_router(transfers.router, prefix="/transfers", tags=["transfers"])
api_v1_router.include_router(fetch.router, prefix="/fetch", tags=["fetch"])
api_v1_router.include_router(issues.router, prefix="/issues", tags=["issues"])
api_v1_router.include_router(prices.router, prefix="/prices", tags=["prices"])
api_v1_router.include_router(import_module.router, prefix="/import", tags=["import"])
api_v1_router.include_router(t2_entries.router, prefix="/t2-entries", tags=["t2-entries"])
api_v1_router.include_router(account_module.router, prefix="/account", tags=["account"])
