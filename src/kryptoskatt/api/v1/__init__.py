"""API v1 router aggregation."""

from fastapi import APIRouter

from kryptoskatt.api.v1 import (
    auth,
    calculate,
    custom_chains,
    fetch,
    issues,
    prices,
    reports,
    transactions,
    wallets,
)

api_v1_router = APIRouter()
api_v1_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_v1_router.include_router(wallets.router, prefix="/wallets", tags=["wallets"])
api_v1_router.include_router(calculate.router, tags=["calculate"])
api_v1_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_v1_router.include_router(custom_chains.router, prefix="/custom-chains", tags=["custom-chains"])
api_v1_router.include_router(transactions.router, prefix="/transactions", tags=["transactions"])
api_v1_router.include_router(fetch.router, prefix="/fetch", tags=["fetch"])
api_v1_router.include_router(issues.router, prefix="/issues", tags=["issues"])
api_v1_router.include_router(prices.router, prefix="/prices", tags=["prices"])
