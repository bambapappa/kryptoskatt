"""CLI command for generating tax reports."""

from pathlib import Path

import typer

from kryptoskatt.db import get_session
from kryptoskatt.reports.k4 import K4ReportGenerator


def run_report(
    year: int,
    format: str = "csv",
    output_dir: str = "./reports",
    full: bool = False,
) -> None:
    """Generate tax report for a specific year.

    Args:
        year: The tax year to generate the report for.
        format: Output format (csv or json).
        output_dir: Directory to write the report files to.
        full: Also generate full transaction list.
    """
    session = get_session()
    try:
        # Create output directory if it doesn't exist
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate report
        generator = K4ReportGenerator(session)
        report = generator.generate(year)

        # Check if there are disposals
        if len(report.rows) == 0:
            typer.echo(
                f"No disposals found for {year}. Run 'kryptoskatt calculate --year {year}' first."
            )
            return

        # Export based on format
        if format == "csv":
            output_file = output_path / f"k4_{year}.csv"
            K4ReportGenerator.export_csv(report, output_file)
            typer.echo(f"Report written to {output_file}")
        elif format == "json":
            output_file = output_path / f"k4_{year}.json"
            K4ReportGenerator.export_json(report, output_file)
            typer.echo(f"Report written to {output_file}")
        else:
            typer.echo(f"Error: Unknown format '{format}'. Use 'csv' or 'json'.", err=True)
            raise typer.Exit(code=1)

        # Generate full transaction list if requested
        if full:
            full_path = output_path / f"transactions_{year}.csv"
            generator.generate_full_transaction_list(year, full_path)
            typer.echo(f"Full transaction list written to {full_path}")

    finally:
        session.close()
