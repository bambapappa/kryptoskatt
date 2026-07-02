"""Shared Jinja2 template environment for web routes."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from kryptoskatt import __version__ as app_version

# Templates path: relative to this file
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Expose package version to all templates (read from source, not installed metadata)
templates.env.globals["app_version"] = app_version


def _abs_filter(value):
    """Jinja2 filter for absolute value."""
    if value is None:
        return None
    return abs(value)


templates.env.filters["abs"] = _abs_filter
