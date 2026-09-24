"""Public legal and information pages: terms, privacy policy, calculation method."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from kryptoskatt.config import settings
from kryptoskatt.models.account import Account
from kryptoskatt.web.auth import get_optional_account
from kryptoskatt.web.templating import templates

router = APIRouter()


def _ctx(account: Account | None) -> dict:
    return {
        "account": account,
        "operator_name": settings.operator_name,
        "operator_contact": settings.operator_contact,
        "inactive_months": settings.inactive_account_months,
    }


@router.get("/villkor", response_class=HTMLResponse)
def terms(request: Request, account: Account | None = Depends(get_optional_account)):
    return templates.TemplateResponse(request, "legal/terms.html", _ctx(account))


@router.get("/integritet", response_class=HTMLResponse)
def privacy(request: Request, account: Account | None = Depends(get_optional_account)):
    return templates.TemplateResponse(request, "legal/privacy.html", _ctx(account))


@router.get("/om-berakningen", response_class=HTMLResponse)
def method(request: Request, account: Account | None = Depends(get_optional_account)):
    return templates.TemplateResponse(request, "legal/method.html", _ctx(account))
