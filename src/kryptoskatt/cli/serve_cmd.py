"""CLI serve command for starting the web server."""

import logging

import uvicorn

from kryptoskatt.config import settings


def setup_logging() -> None:
    """Apply LOG_LEVEL from settings to the root logger."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def run_serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Start the KryptoSkatt web report server."""
    import typer

    setup_logging()
    typer.echo(f"Starting KryptoSkatt web server at http://{host}:{port}")
    typer.echo("Press Ctrl+C to stop.")
    uvicorn.run(
        "kryptoskatt.web.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )
