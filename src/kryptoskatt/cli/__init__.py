"""KryptoSkatt CLI - Swedish Crypto Tax Calculator."""

import typer

from kryptoskatt.cli.wallet import wallet_app
from kryptoskatt.cli.import_cmd import import_file
from kryptoskatt.cli.fetch_cmd import fetch

app = typer.Typer(
    name="kryptoskatt",
    help="KryptoSkatt - Swedish Crypto Tax Calculator",
    add_completion=False,
)


# Import command - named "import" since "import" is a Python keyword
@app.command(name="import")
def import_cmd(
    file: str = typer.Option(..., "--file", help="Path to the transaction file to import"),
    platform: str = typer.Option(
        None,
        "--platform",
        help="Platform (coinbase, crypto_com, mexc). Auto-detected if not provided.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview transactions without saving to database"
    ),
) -> None:
    """Import transaction data from exchange export files."""
    from pathlib import Path

    import_file(file=Path(file), platform=platform, dry_run=dry_run)


# Fetch command
@app.command(name="fetch")
def fetch_cmd(
    address: str = typer.Option(None, "--address", help="Wallet address to fetch transactions for"),
    chain: str = typer.Option(None, "--chain", help="Blockchain (ethereum, solana, etc.)"),
    all_wallets: bool = typer.Option(
        False, "--all", help="Fetch transactions for all registered wallets"
    ),
) -> None:
    """Fetch transactions from blockchain explorers."""
    fetch(address=address, chain=chain, all_wallets=all_wallets)


app.add_typer(wallet_app, name="wallet", help="Manage tracked wallets.")


@app.command()
def calculate(
    year: int = typer.Argument(..., help="Tax year to calculate for"),
) -> None:
    """Calculate capital gains/losses for a tax year."""
    typer.echo("Not implemented yet")


@app.command()
def report(
    year: int = typer.Argument(..., help="Tax year to generate report for"),
    output: str = typer.Option("-", help="Output file path (- for stdout)"),
) -> None:
    """Generate tax report for a specific year."""
    typer.echo("Not implemented yet")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
) -> None:
    """Start the web server for viewing reports."""
    typer.echo("Not implemented yet")


if __name__ == "__main__":
    app()
