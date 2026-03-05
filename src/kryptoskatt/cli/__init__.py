"""KryptoSkatt CLI - Swedish Crypto Tax Calculator."""

import typer

app = typer.Typer(
    name="kryptoskatt",
    help="KryptoSkatt - Swedish Crypto Tax Calculator",
    add_completion=False,
)


@app.command()
def import_file(
    filepath: str = typer.Argument(..., help="Path to the transaction file to import"),
) -> None:
    """Import transaction data from exchange export files."""
    typer.echo("Not implemented yet")


@app.command()
def fetch(
    chain: str = typer.Argument(..., help="Blockchain to fetch (ethereum, solana, etc.)"),
    address: str = typer.Argument(..., help="Wallet address to fetch transactions for"),
) -> None:
    """Fetch transactions from blockchain explorers."""
    typer.echo("Not implemented yet")


@app.command()
def wallet(
    action: str = typer.Argument(..., help="Action: add, list, remove"),
    address: str = typer.Option(None, help="Wallet address"),
) -> None:
    """Manage tracked wallets."""
    typer.echo("Not implemented yet")


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
