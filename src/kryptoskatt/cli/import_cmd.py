"""CLI command for importing transaction files."""

import typer
from pathlib import Path
from typing import Optional

from kryptoskatt.db import get_session
from kryptoskatt.models.transaction import ImportBatch, Transaction
from kryptoskatt.parsers.coinbase import CoinbaseParser
from kryptoskatt.parsers.crypto_com import CryptoComParser
from kryptoskatt.parsers.mexc import MexcParser
from kryptoskatt.schemas import TransactionCreate

# Supported platforms
SUPPORTED_PLATFORMS = ["coinbase", "crypto_com", "mexc"]


def detect_platform(file_path: Path, lines: list[str]) -> str:
    """Detect platform from file content.

    Args:
        file_path: Path to the file (used for extension check)
        lines: First few lines of the file

    Returns:
        Detected platform name ('coinbase', 'crypto_com', or 'mexc')
    """
    content = "\n".join(lines).lower()

    # Check for Coinbase markers
    if "coinbase" in content or "transaction type" in content:
        return "coinbase"

    # Check for Crypto.com markers
    if "crypto.com" in content or "transaction kind" in content:
        return "crypto_com"

    # Check for MEXC markers (tab-separated with Swedish headers)
    if file_path.suffix == ".tsv" or "tid" in content:
        return "mexc"

    # Default to coinbase if can't detect
    return "coinbase"


def get_parser(platform: str):
    """Get the appropriate parser for the platform.

    Args:
        platform: Platform name ('coinbase', 'crypto_com', or 'mexc')

    Returns:
        Parser instance

    Raises:
        ValueError: If platform is not supported
    """
    if platform not in SUPPORTED_PLATFORMS:
        valid = ", ".join(SUPPORTED_PLATFORMS)
        raise ValueError(f"Unsupported platform: {platform}. Valid: {valid}")

    if platform == "coinbase":
        return CoinbaseParser()
    elif platform == "crypto_com":
        return CryptoComParser()
    elif platform == "mexc":
        return MexcParser()


def parse_file(file_path: Path, platform: str):
    """Parse a transaction file.

    Args:
        file_path: Path to the file
        platform: Platform name

    Returns:
        Tuple of (transactions: list[TransactionCreate], errors: list[str])
    """
    parser = get_parser(platform)
    result = parser.parse(file_path)

    # Handle MEXC's different interface (returns tuple, not ParseResult)
    if isinstance(result, tuple):
        transactions, errors = result
    else:
        transactions = result.transactions
        errors = result.errors

    return transactions, errors


def create_import_batch(
    session, platform: str, filename: str, row_count: int, error_count: int
) -> ImportBatch:
    """Create an ImportBatch record in the database.

    Args:
        session: Database session
        platform: Platform name
        filename: Name of imported file
        row_count: Number of rows imported
        error_count: Number of errors encountered

    Returns:
        Created ImportBatch instance
    """
    batch = ImportBatch(
        platform=platform.upper(),
        filename=filename,
        row_count=row_count,
        error_count=error_count,
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


def save_transactions(session, transactions: list[TransactionCreate], batch: ImportBatch) -> int:
    """Save transactions to the database.

    Args:
        session: Database session
        transactions: List of TransactionCreate schemas
        batch: ImportBatch to link transactions to

    Returns:
        Number of transactions saved
    """
    saved_count = 0

    for tc in transactions:
        tx = Transaction(
            import_batch_id=batch.id,
            source_platform=tc.source_platform,
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
    return saved_count


def import_file(
    file: Path,
    platform: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """Import transaction data from exchange export files.

    Supported platforms:
    - coinbase: Coinbase CSV exports
    - crypto_com: Crypto.com CSV exports
    - mexc: MEXC TSV exports

    The platform will be auto-detected from file content if --platform is not specified.
    """
    file_path = Path(file)

    # Validate file exists
    if not file_path.exists():
        typer.echo(f"Error: File not found: {file_path}", err=True)
        raise typer.Exit(code=1)

    # Auto-detect platform if not provided
    if platform is None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = [f.readline() for _ in range(10)]
            platform = detect_platform(file_path, lines)
            typer.echo(f"Auto-detected platform: {platform}")
        except Exception as e:
            typer.echo(f"Error: Could not auto-detect platform: {e}", err=True)
            raise typer.Exit(code=1)

    # Validate platform
    platform = platform.lower()
    if platform not in SUPPORTED_PLATFORMS:
        valid = ", ".join(SUPPORTED_PLATFORMS)
        typer.echo(f"Error: Unsupported platform: {platform}. Valid: {valid}", err=True)
        raise typer.Exit(code=1)

    # Parse file
    try:
        transactions, errors = parse_file(file_path, platform)
    except Exception as e:
        typer.echo(f"Error parsing file: {e}", err=True)
        raise typer.Exit(code=1)

    # Show preview for dry-run
    if dry_run:
        typer.echo(f"\n=== DRY RUN: Preview ===")
        typer.echo(f"Platform: {platform}")
        typer.echo(f"File: {file_path.name}")
        typer.echo(f"Transactions found: {len(transactions)}")
        typer.echo(f"Errors: {len(errors)}")

        if errors:
            typer.echo("\n=== Errors ===")
            for err in errors[:10]:  # Show first 10 errors
                typer.echo(f"  - {err}")
            if len(errors) > 10:
                typer.echo(f"  ... and {len(errors) - 10} more")

        typer.echo("\n=== First 10 transactions ===")
        for i, tx in enumerate(transactions[:10]):
            typer.echo(
                f"  {i + 1}. {tx.timestamp_utc} | {tx.event_type} | {tx.base_amount} {tx.base_coin}"
            )
        if len(transactions) > 10:
            typer.echo(f"  ... and {len(transactions) - 10} more")

        typer.echo("\nNo data was saved (dry-run mode).")
        return

    # Save to database
    session = get_session()
    try:
        # Create import batch
        batch = create_import_batch(
            session=session,
            platform=platform,
            filename=file_path.name,
            row_count=len(transactions),
            error_count=len(errors),
        )

        # Save transactions
        saved_count = save_transactions(session, transactions, batch)

        typer.echo(f"Imported {saved_count} transactions from {file_path.name}")
        if errors:
            typer.echo(f"Errors: {len(errors)}")
            for err in errors[:5]:  # Show first 5 errors
                typer.echo(f"  - {err}")
            if len(errors) > 5:
                typer.echo(f"  ... and {len(errors) - 5} more")

    except Exception as e:
        typer.echo(f"Error saving to database: {e}", err=True)
        session.rollback()
        raise typer.Exit(code=1)
    finally:
        session.close()
