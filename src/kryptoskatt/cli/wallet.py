"""Wallet CLI commands for managing tracked wallets."""

import typer

from kryptoskatt.db import get_session
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.wallet import WalletService

wallet_app = typer.Typer(
    name="wallet",
    help="Manage tracked cryptocurrency wallets.",
    add_completion=False,
)


@wallet_app.command()
def add(
    address: str = typer.Option(..., "--address", help="Wallet address"),
    chain: str = typer.Option(..., "--chain", help="Blockchain (ethereum, solana, etc.)"),
    label: str = typer.Option("", "--label", help="Optional label for the wallet"),
    mine: bool = typer.Option(True, "--mine/--no-mine", help="Mark wallet as mine"),
) -> None:
    """Add a new wallet to track."""
    session = get_session()
    service = WalletService(session)

    try:
        data = WalletCreate(
            address=address,
            chain=chain,
            label=label,
            is_mine=mine,
        )
        wallet = service.add_wallet(data)
        typer.echo(f"Added wallet {wallet.address} on {wallet.chain} (ID: {wallet.id})")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)
    finally:
        session.close()


@wallet_app.command()
def list(
    chain: str | None = typer.Option(None, "--chain", help="Filter by chain"),
    mine_only: bool = typer.Option(False, "--mine-only", help="Show only my wallets"),
) -> None:
    """List tracked wallets."""
    session = get_session()
    service = WalletService(session)

    try:
        wallets = service.list_wallets(chain=chain, mine_only=mine_only)

        if not wallets:
            typer.echo("No wallets found.")
            return

        # Header
        typer.echo(f"{'ID':<5} {'Address':<44} {'Chain':<12} {'Label':<30} {'Mine':<5}")
        typer.echo("-" * 100)

        # Rows
        for w in wallets:
            label = w.label or ""
            address_short = w.address[:40] + "..." if len(w.address) > 40 else w.address
            typer.echo(
                f"{w.id:<5} {address_short:<44} {w.chain:<12} {label:<30} {'Yes' if w.is_mine else 'No':<5}"
            )
    finally:
        session.close()


@wallet_app.command()
def remove(
    address: str = typer.Option(..., "--address", help="Wallet address to remove"),
    chain: str | None = typer.Option(None, "--chain", help="Blockchain (optional)"),
) -> None:
    """Remove a tracked wallet."""
    session = get_session()
    service = WalletService(session)

    try:
        removed = service.remove_wallet(address, chain)
        if removed:
            typer.echo(f"Removed wallet {address}")
        else:
            typer.echo(f"Wallet {address} not found.", err=True)
            raise typer.Exit(code=1)
    finally:
        session.close()
