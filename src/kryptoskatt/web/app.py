"""FastAPI web application for KryptoSkatt.

App factory, middleware and router wiring. The actual HTML routes live
in ``kryptoskatt.web.routes.*`` and the REST API in ``kryptoskatt.api.v1``.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from kryptoskatt import __version__ as app_version
from kryptoskatt.api.v1 import api_v1_router
from kryptoskatt.config import settings
from kryptoskatt.web.deps import (  # noqa: F401  (re-exported: tests and external code override these)
    get_current_account_for_html,
    get_db,
)
from kryptoskatt.web.routes import (
    action_pages,
    address_pages,
    auth_pages,
    dashboard_pages,
    debug_pages,
    onboarding_pages,
    price_pages,
    settings_pages,
    year_pages,
)
from kryptoskatt.web.templating import (
    templates,  # noqa: F401  (re-exported for backwards compatibility)
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="KryptoSkatt API",
    description="Swedish crypto tax calculation service. Anonymous accounts, no registration required.",
    version=app_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


class APIVersionMiddleware(BaseHTTPMiddleware):
    """Inject X-API-Version header on all /api/ responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["X-API-Version"] = "1"
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers on all responses (extra headers on HTML)."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # HSTS only makes sense once the request already travels over HTTPS
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if proto == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "script-src 'self' 'unsafe-inline'; "
                "frame-ancestors 'none'"
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(APIVersionMiddleware)


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return JSONResponse({"status": "ok"})


app.include_router(api_v1_router, prefix="/api/v1")

app.include_router(auth_pages.router)
app.include_router(settings_pages.router)
app.include_router(dashboard_pages.router)
app.include_router(year_pages.router)
app.include_router(address_pages.router)
app.include_router(action_pages.router)
app.include_router(price_pages.router)
app.include_router(onboarding_pages.router)

# Debug routes — only mounted when DEBUG_MODE=true.
# Must never be enabled in production: exposes raw DB data and destructive endpoints.
if settings.debug_mode:
    app.include_router(debug_pages.router)
    logger.warning("Debug routes enabled — ensure DEBUG_MODE=false in production")
