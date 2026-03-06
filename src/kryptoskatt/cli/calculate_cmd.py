"""CLI command for calculating capital gains/losses."""

import typer

from kryptoskatt.db import get_session
from kryptoskatt.engine.dedup import DeduplicationEngine
from kryptoskatt.engine.gav import GavEngine
from kryptoskatt.engine.transfers import TransferMatcher
from kryptoskatt.services.wallet import WalletService


def run_calculate(year: int) -> None:
    """Calculate capital gains/losses for a tax year.

    This function runs the full calculation pipeline:
    1. Deduplicate transactions
    2. Match transfers between own wallets
    3. Calculate GAV (Genomsnittsmetoden) and generate disposal records

    Args:
        year: The tax year to calculate for.
    """
    session = get_session()
    try:
        # Step 1: Deduplicate transactions
        typer.echo("Step 1/3: Deduplicating transactions...")
        dedup_engine = DeduplicationEngine(session)
        dedup_report = dedup_engine.deduplicate_all()
        typer.echo(
            f"  Found {dedup_report.exact_matches} exact + {dedup_report.heuristic_matches} heuristic duplicates"
        )

        # Step 2: Match transfers
        typer.echo("Step 2/3: Matching transfers...")
        wallet_service = WalletService(session)
        my_addresses = wallet_service.get_my_addresses()
        transfer_matcher = TransferMatcher(session, my_addresses)
        transfer_report = transfer_matcher.match_all()
        typer.echo(
            f"  Matched {transfer_report.matched} transfers, {transfer_report.unmatched} unmatched"
        )

        # Step 3: Calculate GAV
        typer.echo(f"Step 3/3: Calculating GAV for {year}...")
        gav_engine = GavEngine(session)
        result = gav_engine.calculate(year=year)
        typer.echo(f"  Created {len(result.disposals)} disposals")

        # Show warnings if any
        for warning in result.warnings:
            typer.echo(f"  ⚠ {warning}")

        # Calculate totals for summary
        total_gains = sum(d.gain_loss_sek for d in result.disposals if d.gain_loss_sek > 0)
        total_losses = sum(abs(d.gain_loss_sek) for d in result.disposals if d.gain_loss_sek < 0)

        # Commit changes (GAV engine adds records but doesn't commit)
        session.commit()

        # Final summary
        typer.echo(f"Done! Total gains: {total_gains} SEK, Total losses: {total_losses} SEK")

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
