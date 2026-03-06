"""CLI serve command for starting the web server."""

import uvicorn


def run_serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Start the KryptoSkatt web report server."""
    import typer

    typer.echo(f"Starting KryptoSkatt web server at http://{host}:{port}")
    typer.echo("Press Ctrl+C to stop.")
    uvicorn.run(
        "kryptoskatt.web.app:app",
        host=host,
        port=port,
        reload=reload,
    )
