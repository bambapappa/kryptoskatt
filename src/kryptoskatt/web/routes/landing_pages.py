"""Public landing page for logged-out visitors."""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from kryptoskatt.models.account import Account
from kryptoskatt.web.auth import get_optional_account
from kryptoskatt.web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/välkommen", response_class=HTMLResponse)
def landing(
    request: Request,
    account: Account | None = Depends(get_optional_account),
):
    """Public landing page describing the service, with links to log in or sign up."""
    if account is not None:
        return RedirectResponse("/översikt", status_code=303)
    return templates.TemplateResponse(request, "landing.html", {"account": None})


@router.get("/", response_class=HTMLResponse)
def root(account: Account | None = Depends(get_optional_account)):
    """/ leads to the landing page for visitors, the overview for logged-in users."""
    return RedirectResponse("/översikt" if account is not None else "/välkommen", status_code=303)
