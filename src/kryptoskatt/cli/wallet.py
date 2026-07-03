"""Wallet CLI commands for managing tracked wallets."""

import typer

from kryptoskatt.chains import get_registry
from kryptoskatt.db import get_session
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.auth import get_legacy_user_id
from kryptoskatt.services.wallet import WalletService

wallet_app = typer.Typer(
    name="wallet",
    help="Manage tracked cryptocurrency wallets.",
    add_completion=False,
)


def _wallet_service(session) -> WalletService:
    """WalletService scoped to the CLI's single-user (legacy) account."""
    return WalletService(session, get_legacy_user_id(session))


@wallet_app.command()
def add(
    address: str = typer.Option(..., "--address", help="Wallet address"),
    chain: str = typer.Option(..., "--chain", help="Blockchain (ethereum, solana, etc.)"),
    label: str = typer.Option("", "--label", help="Optional label for the wallet"),
    mine: bool = typer.Option(True, "--mine/--no-mine", help="Mark wallet as mine"),
) -> None:
    """Add a new wallet to track."""
    session = get_session()
    service = _wallet_service(session)

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


@wallet_app.command(name="add-xpub")
def add_xpub(
    xpub: str = typer.Argument(..., help="Extended public key (xpub/ypub/zpub)"),
    label: str = typer.Option("", "--label", help="Optional label prefix"),
    gap: int = typer.Option(20, "--gap", help="Gap limit for the address scan"),
    no_scan: bool = typer.Option(
        False, "--no-scan", help="Skip the on-chain usage scan; derive exactly --gap addresses"
    ),
) -> None:
    """Derive and register Bitcoin addresses from an xpub/ypub/zpub."""
    session = get_session()
    service = _wallet_service(session)
    try:
        summary = service.import_xpub(
            xpub, label=label, gap_limit=gap, use_network=not no_scan
        )
        typer.echo(
            f"Registered {summary['added']} Bitcoin addresses "
            f"({summary['skipped']} already existed) from {len(summary['addresses'])} derived."
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from e
    finally:
        session.close()


@wallet_app.command()
def list(
    chain: str | None = typer.Option(None, "--chain", help="Filter by chain"),
    mine_only: bool = typer.Option(False, "--mine-only", help="Show only my wallets"),
) -> None:
    """List tracked wallets."""
    session = get_session()
    service = _wallet_service(session)

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
def status() -> None:
    """Show which chains have registered adapters."""
    registry = get_registry()
    chains = sorted(registry.supported_chains())

    if not chains:
        typer.echo("No chain adapters registered.")
        return

    typer.echo(f"{'Chain':<20} {'Adapter':<30}")
    typer.echo("-" * 52)
    for chain in chains:
        adapter = registry.get_adapter(chain)
        adapter_name = type(adapter).__name__ if adapter else "—"
        typer.echo(f"{chain:<20} {adapter_name:<30}")

    typer.echo(f"\nTotal: {len(chains)} chain(s) with adapters")


@wallet_app.command()
def remove(
    address: str = typer.Option(..., "--address", help="Wallet address to remove"),
    chain: str | None = typer.Option(None, "--chain", help="Blockchain (optional)"),
) -> None:
    """Remove a tracked wallet."""
    session = get_session()
    service = _wallet_service(session)

    try:
        removed = service.remove_wallet(address, chain)
        if removed:
            typer.echo(f"Removed wallet {address}")
        else:
            typer.echo(f"Wallet {address} not found.", err=True)
            raise typer.Exit(code=1)
    finally:
        session.close()
