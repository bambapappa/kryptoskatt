"""CLI command for fetching on-chain transactions."""

import logging

import typer

from kryptoskatt.chains import get_registry, get_registry_for_user
from kryptoskatt.db import get_session
from kryptoskatt.enums import Chain
from kryptoskatt.models.transaction import ImportBatch, Transaction
from kryptoskatt.models.wallet import Wallet
from kryptoskatt.schemas import TransactionCreate
from kryptoskatt.services.auth import get_legacy_user_id
from kryptoskatt.services.wallet import WalletService

logger = logging.getLogger(__name__)


def create_import_batch_for_fetch(session, wallet_count: int, tx_count: int, user_id: int) -> ImportBatch:
    """Create an ImportBatch record for on-chain fetches.

    Args:
        session: Database session
        wallet_count: Number of wallets fetched
        tx_count: Number of transactions fetched
        user_id: Account DB id

    Returns:
        Created ImportBatch instance
    """
    batch = ImportBatch(
        user_id=user_id,
        platform="ON_CHAIN",
        filename=f"on_chain_fetch_{wallet_count}_wallets",
        row_count=tx_count,
        error_count=0,
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


def save_fetched_transactions(
    session,
    transactions: list[TransactionCreate],
    batch: ImportBatch,
    user_id: int,
    wallet_id: int | None = None,
    chain_tag: str | None = None,
) -> tuple[int, int]:
    """Save fetched transactions, skipping any already present by tx_hash.

    A transaction is a duplicate if (tx_hash, base_coin, event_type) already exists
    for this user.
    Transactions without a tx_hash are always inserted.

    Args:
        user_id: Account DB id to scope the uniqueness check and set on new rows.
        wallet_id: ID of the wallet these transactions were fetched for.
        chain_tag: Chain identifier (e.g. "ETH", "POLYGON") appended to source_platform
                   so we can later distinguish cross-chain contamination.

    Returns:
        (saved_count, skipped_count)
    """
    from sqlalchemy import select as sa_select

    # Pre-fetch existing keys to avoid N+1 queries (scoped to this user)
    existing_keys: set[tuple] = set()
    hashes_to_check = {tc.tx_hash for tc in transactions if tc.tx_hash}
    if hashes_to_check:
        rows = session.execute(
            sa_select(Transaction.tx_hash, Transaction.base_coin, Transaction.event_type).where(
                Transaction.user_id == user_id,
                Transaction.tx_hash.in_(hashes_to_check),
            )
        ).all()
        existing_keys = {(r.tx_hash, r.base_coin, r.event_type) for r in rows}

    saved_count = 0
    skipped_count = 0

    for tc in transactions:
        if tc.tx_hash:
            ev = tc.event_type.value if hasattr(tc.event_type, "value") else str(tc.event_type)
            if (tc.tx_hash, tc.base_coin, ev) in existing_keys:
                skipped_count += 1
                continue

        # Encode the chain into source_platform so we can trace origin later.
        # e.g. "ETHERSCAN" → "ETHERSCAN_ETH" or "ETHERSCAN_POLYGON"
        source = tc.source_platform
        if chain_tag and not source.endswith(f"_{chain_tag}"):
            source = f"{source}_{chain_tag}"

        tx = Transaction(
            user_id=user_id,
            import_batch_id=batch.id,
            wallet_id=wallet_id,
            source_platform=source,
            timestamp_utc=tc.timestamp_utc,
            event_type=tc.event_type,
            base_coin=tc.base_coin,
            base_amount=tc.base_amount,
            quote_coin=tc.quote_coin,
            quote_amount=tc.quote_amount,
            fee_coin=tc.fee_coin,
            fee_amount=tc.fee_amount,
            tx_hash=tc.tx_hash,
            from_address=tc.from_address,
            to_address=tc.to_address,
            price_sek=tc.price_sek,
            raw_payload=tc.raw_payload,
        )
        session.add(tx)
        saved_count += 1

    session.commit()
    return saved_count, skipped_count


def fetch(
    address: str | None = None,
    chain: str | None = None,
    all_wallets: bool = False,
) -> None:
    """Fetch transactions from blockchain explorers.

    Either specify --address and --chain for a single wallet, or use --all to fetch
    for all registered wallets.

    Examples:
        kryptoskatt fetch --address 0x1234... --chain ethereum
        kryptoskatt fetch --all
    """
    # Validate arguments
    if all_wallets:
        if address or chain:
            typer.echo("Error: Cannot use --all together with --address or --chain", err=True)
            raise typer.Exit(code=1)
        _fetch_all_wallets()
    else:
        if not address or not chain:
            typer.echo("Error: Must specify both --address and --chain, or use --all", err=True)
            raise typer.Exit(code=1)
        _fetch_single_address(address, chain)


def _fetch_single_address(address: str, chain: str) -> None:
    """Fetch transactions for a single address."""
    # Validate chain
    try:
        chain_enum = Chain(chain.upper())
    except ValueError:
        valid_chains = ", ".join(c.value for c in Chain)
        typer.echo(f"Error: Unknown chain: {chain}. Valid: {valid_chains}", err=True)
        raise typer.Exit(code=1)

    # Get registry and adapter
    registry = get_registry()
    adapter = registry.get_adapter(chain_enum)

    if adapter is None:
        typer.echo(f"Warning: No adapter available for chain {chain}. Skipping.", err=True)
        return

    # Fetch transactions
    try:
        typer.echo(f"Fetching transactions for {address} on {chain}...")
        transactions = adapter.fetch_transactions(address, chain_enum)

        if not transactions:
            typer.echo("No transactions found.")
            return

        # Save to database
        session = get_session()
        try:
            user_id = get_legacy_user_id(session)

            # Look up wallet_id for this address+chain so we can track origin
            wallet_record = (
                session.query(Wallet)
                .filter_by(address=address, chain=chain_enum.value)
                .filter(Wallet.user_id == user_id)
                .first()
            )
            wallet_id_for_save = wallet_record.id if wallet_record else None

            batch = create_import_batch_for_fetch(session, 1, len(transactions), user_id)
            saved_count, skipped_count = save_fetched_transactions(
                session, transactions, batch,
                user_id=user_id,
                wallet_id=wallet_id_for_save,
                chain_tag=chain_enum.value,
            )
            typer.echo(f"Saved {saved_count} transactions from {chain} ({skipped_count} already existed, skipped)")
        except Exception as e:
            typer.echo(f"Error saving to database: {e}", err=True)
            session.rollback()
            raise typer.Exit(code=1)
        finally:
            session.close()

    except Exception as e:
        logger.exception("Error fetching transactions")
        typer.echo(f"Error fetching transactions: {e}", err=True)
        raise typer.Exit(code=1)


def _fetch_all_wallets() -> None:
    """Fetch transactions for all registered wallets."""
    session = get_session()
    try:
        user_id = get_legacy_user_id(session)

        # Get all wallets
        wallet_service = WalletService(session, user_id)
        wallets = wallet_service.list_wallets(mine_only=True)

        if not wallets:
            typer.echo(
                "No wallets found. Add wallets with: kryptoskatt wallet add --address <addr> --chain <chain> --mine"
            )
            return

        typer.echo(f"Fetching transactions for {len(wallets)} wallets...")

        # Get registry including user's custom chain adapters
        registry = get_registry_for_user(session, user_id)
        unsupported_chains = set()
        fetched_wallets = 0

        # Fetch per wallet and save immediately so wallet_id is tracked correctly
        total_saved = 0
        total_skipped = 0

        for wallet in wallets:
            adapter = registry.get_adapter(wallet.chain)

            if adapter is None:
                unsupported_chains.add(wallet.chain)
                continue

            try:
                txs = adapter.fetch_transactions(wallet.address, wallet.chain)
                if txs:
                    batch = create_import_batch_for_fetch(session, 1, len(txs), user_id)
                    saved, skipped = save_fetched_transactions(
                        session, txs, batch,
                        user_id=user_id,
                        wallet_id=wallet.id,
                        chain_tag=wallet.chain,
                    )
                    total_saved += saved
                    total_skipped += skipped
                fetched_wallets += 1
            except Exception as e:
                logger.warning(
                    "Failed to fetch for wallet %s on %s: %s", wallet.address, wallet.chain, e
                )
                typer.echo(
                    f"Warning: Failed to fetch for {wallet.address[:20]}... on {wallet.chain}: {e}"
                )

        # Report unsupported chains
        if unsupported_chains:
            typer.echo(f"Warning: No adapter for chains: {', '.join(unsupported_chains)}")

        if total_saved + total_skipped == 0:
            typer.echo("No transactions found.")
            return

        typer.echo(f"Saved {total_saved} transactions from {fetched_wallets} wallets ({total_skipped} already existed, skipped)")

    finally:
        session.close()
