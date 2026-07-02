"""CLI command for importing transaction files."""

from pathlib import Path

import typer

from kryptoskatt.db import get_session
from kryptoskatt.models.transaction import ImportBatch, Transaction
from kryptoskatt.parsers.binance import BinanceParser
from kryptoskatt.parsers.bitstamp import BitstampParser
from kryptoskatt.parsers.bybit import BybitParser
from kryptoskatt.parsers.coinbase import CoinbaseParser
from kryptoskatt.parsers.coinbase_advanced import CoinbaseAdvancedParser
from kryptoskatt.parsers.crypto_com import CryptoComParser
from kryptoskatt.parsers.gateio import GateIoParser
from kryptoskatt.parsers.kraken import KrakenParser
from kryptoskatt.parsers.kucoin import KuCoinParser
from kryptoskatt.parsers.ledger import LedgerParser
from kryptoskatt.parsers.manual_swap import ManualSwapParser
from kryptoskatt.parsers.mexc import MexcParser
from kryptoskatt.parsers.okx import OkxParser
from kryptoskatt.schemas import TransactionCreate

# Supported platforms
SUPPORTED_PLATFORMS = [
    "binance", "bitstamp", "bybit", "coinbase", "coinbase_advanced",
    "crypto_com", "gateio", "kraken", "kucoin", "ledger", "manual_swap",
    "mexc", "okx",
]


def detect_platform(file_path: Path, lines: list[str]) -> str:
    """Detect platform from file content.

    Args:
        file_path: Path to the file (used for extension check)
        lines: First few lines of the file

    Returns:
        Detected platform name ('coinbase', 'crypto_com', or 'mexc')
    """
    content = "\n".join(lines).lower()

    # Check for Binance markers (before Coinbase to avoid false positives)
    if "utc_time" in content and "operation" in content and "change" in content:
        return "binance"

    # Check for Bitstamp markers (v2 header has distinct currency columns)
    if "amount currency" in content and "value currency" in content and "subtype" in content:
        return "bitstamp"

    # Check for Gate.io markers
    if "action_desc" in content and "change_amount" in content:
        return "gateio"

    # Check for OKX markers (trading statement or funding bill)
    if ("trade type" in content and "order id" in content) or (
        "before balance" in content and "after balance" in content
    ):
        return "okx"

    # Check for Coinbase Advanced Trade markers
    if "trade id" in content and "size unit" in content and "price/fee/total unit" in content:
        return "coinbase_advanced"

    # Check for Coinbase markers
    if "coinbase" in content or "transaction type" in content:
        return "coinbase"

    # Check for Crypto.com markers
    if "crypto.com" in content or "transaction kind" in content:
        return "crypto_com"

    # Check for Ledger Live markers
    if "operation date" in content and "account xpub" in content:
        return "ledger"

    # Check for KuCoin markers
    if "tradeid" in content and "feecurrency" in content and "orderplacedat" in content:
        return "kucoin"

    # Check for manual swap markers
    if "from_coin" in content and "to_coin" in content and "from_amount" in content:
        return "manual_swap"

    # Check for Kraken ledger markers
    if "txid" in content and "refid" in content and "aclass" in content:
        return "kraken"

    # Check for Bybit order history markers
    if "filled price" in content and "fee symbol" in content and "order id" in content:
        return "bybit"

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

    if platform == "binance":
        return BinanceParser()
    elif platform == "bitstamp":
        return BitstampParser()
    elif platform == "bybit":
        return BybitParser()
    elif platform == "gateio":
        return GateIoParser()
    elif platform == "okx":
        return OkxParser()
    elif platform == "coinbase":
        return CoinbaseParser()
    elif platform == "coinbase_advanced":
        return CoinbaseAdvancedParser()
    elif platform == "crypto_com":
        return CryptoComParser()
    elif platform == "kraken":
        return KrakenParser()
    elif platform == "kucoin":
        return KuCoinParser()
    elif platform == "ledger":
        return LedgerParser()
    elif platform == "manual_swap":
        return ManualSwapParser()
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
    session,
    platform: str,
    filename: str,
    row_count: int,
    error_count: int,
    imported_count: int = 0,
    duplicate_count: int = 0,
    user_id: int | None = None,
) -> ImportBatch:
    """Create an ImportBatch record in the database.

    Args:
        session: Database session
        platform: Platform name
        filename: Name of imported file
        row_count: Number of rows parsed from file
        error_count: Number of parse errors encountered
        imported_count: Number of transactions actually saved
        duplicate_count: Number of transactions flagged as duplicates (updated by dedup engine)
        user_id: Account DB id (required for multi-tenant; falls back to legacy if None)

    Returns:
        Created ImportBatch instance
    """
    if user_id is None:
        from kryptoskatt.services.auth import get_legacy_user_id
        user_id = get_legacy_user_id(session)

    batch = ImportBatch(
        user_id=user_id,
        platform=platform.upper(),
        filename=filename,
        row_count=row_count,
        error_count=error_count,
        imported_count=imported_count,
        duplicate_count=duplicate_count,
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)
    return batch


def _content_key(platform, ts, event_type, base_coin, base_amount,
                 quote_coin, quote_amount, fee_coin, fee_amount, tx_hash) -> tuple:
    """Normalized content identity of a transaction row, for re-import detection.

    Amounts are normalized through float64: SQLite stores Numeric as float,
    so values read back can carry noise in the last decimals. The tiny
    precision loss is fine for an identity check — every other field must
    also match.
    """
    if ts is not None and ts.tzinfo is not None:
        from datetime import UTC as _UTC
        ts = ts.astimezone(_UTC).replace(tzinfo=None)
    ev = event_type.value if hasattr(event_type, "value") else str(event_type)

    def _num(x):
        return None if x is None else repr(float(x))

    return (platform, ts, ev, base_coin, _num(base_amount),
            quote_coin, _num(quote_amount), fee_coin, _num(fee_amount), tx_hash)


def save_transactions(session, transactions: list[TransactionCreate], batch: ImportBatch, user_id: int | None = None) -> int:
    """Save transactions to the database, skipping rows already imported.

    A row is skipped if an identical row (same platform, timestamp, event
    type, coins, amounts, fees and tx_hash) already exists for this user —
    so re-uploading the same export file is a no-op. Multiset semantics:
    if the file legitimately contains two identical fills, both are kept
    unless two identical rows already exist in the database.

    Args:
        session: Database session
        transactions: List of TransactionCreate schemas
        batch: ImportBatch to link transactions to (duplicate_count is updated)
        user_id: Account DB id (required for multi-tenant; falls back to legacy if None)

    Returns:
        Number of transactions saved
    """
    if user_id is None:
        from kryptoskatt.services.auth import get_legacy_user_id
        user_id = get_legacy_user_id(session)

    # Count existing identical rows in the incoming time window (one query)
    from collections import Counter

    existing: Counter = Counter()
    timestamps = [tc.timestamp_utc for tc in transactions if tc.timestamp_utc is not None]
    if timestamps:
        rows = session.query(
            Transaction.source_platform, Transaction.timestamp_utc, Transaction.event_type,
            Transaction.base_coin, Transaction.base_amount,
            Transaction.quote_coin, Transaction.quote_amount,
            Transaction.fee_coin, Transaction.fee_amount, Transaction.tx_hash,
        ).filter(
            Transaction.user_id == user_id,
            Transaction.timestamp_utc >= min(timestamps),
            Transaction.timestamp_utc <= max(timestamps),
        ).all()
        existing = Counter(_content_key(*row) for row in rows)

    saved_count = 0
    skipped_count = 0

    for tc in transactions:
        key = _content_key(
            tc.source_platform, tc.timestamp_utc, tc.event_type,
            tc.base_coin, tc.base_amount, tc.quote_coin, tc.quote_amount,
            tc.fee_coin, tc.fee_amount, tc.tx_hash,
        )
        if existing[key] > 0:
            existing[key] -= 1
            skipped_count += 1
            continue
        tx = Transaction(
            user_id=user_id,
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

    batch.imported_count = saved_count
    batch.duplicate_count = skipped_count
    session.commit()
    return saved_count


def import_file(
    file: Path,
    platform: str | None = None,
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
            with open(file_path, encoding="utf-8") as f:
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
        typer.echo("\n=== DRY RUN: Preview ===")
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
        # Create import batch (imported_count updated below after save)
        batch = create_import_batch(
            session=session,
            platform=platform,
            filename=file_path.name,
            row_count=len(transactions),
            error_count=len(errors),
        )

        # Save transactions
        saved_count = save_transactions(session, transactions, batch)

        # Update imported_count now that we know the actual saved count
        batch.imported_count = saved_count
        session.commit()

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
