"""CLI command for generating tax reports."""

from pathlib import Path

import typer

from kryptoskatt.db import get_session
from kryptoskatt.reports.k4 import K4ReportGenerator
from kryptoskatt.services.auth import get_legacy_user_id


def run_report(
    year: int,
    format: str = "csv",
    output_dir: str = "./reports",
    full: bool = False,
    personnummer: str = "",
    namn: str = "",
) -> None:
    """Generate tax report for a specific year.

    Args:
        year: The tax year to generate the report for.
        format: Output format (csv, json or sru).
        output_dir: Directory to write the report files to.
        full: Also generate full transaction list.
        personnummer: 12-digit personnummer (required for the sru format).
        namn: Taxpayer full name (required for the sru format).
    """
    session = get_session()
    try:
        # Create output directory if it doesn't exist
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        user_id = get_legacy_user_id(session)

        # Year-to-year GAV carryover has its own generator (holdings-based, not
        # disposal-based) so it is handled before the K4/disposal path.
        if format == "carryover":
            from kryptoskatt.reports.gav_carryover import GavCarryoverReport

            carry = GavCarryoverReport(session, user_id).generate(year)
            output_file = output_path / f"gav_carryover_{year}.csv"
            headers = [
                "Tillgång",
                "Ingående antal",
                "Ingående omkostnad SEK",
                "Ingående GAV SEK",
                "Utgående antal",
                "Utgående omkostnad SEK",
                "Utgående GAV SEK",
                "Förändring antal",
                "Förändring omkostnad SEK",
            ]
            lines = [",".join(headers)]
            for r in carry.rows:
                lines.append(
                    f"{r.coin},{r.opening_units},{r.opening_cost_sek},{r.opening_gav_sek},"
                    f"{r.closing_units},{r.closing_cost_sek},{r.closing_gav_sek},"
                    f"{r.units_delta},{r.cost_delta_sek}"
                )
            lines.append(
                f"TOTALT,,{carry.opening_total_cost_sek},,,{carry.closing_total_cost_sek},,,"
            )
            output_file.write_text("\n".join(lines), encoding="utf-8-sig")
            typer.echo(f"GAV carryover written to {output_file}")
            return

        # Generate report
        generator = K4ReportGenerator(session, user_id)
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
        elif format == "sru":
            from kryptoskatt.reports.sru import K4SruGenerator, SruTaxpayer

            if not personnummer or not namn:
                typer.echo(
                    "Error: --personnummer and --namn are required for the sru format.",
                    err=True,
                )
                raise typer.Exit(code=1)
            try:
                export = K4SruGenerator(session, user_id).generate(
                    year, SruTaxpayer(personnummer=personnummer, namn=namn)
                )
            except ValueError as e:
                typer.echo(f"Error: {e}", err=True)
                raise typer.Exit(code=1) from e
            from kryptoskatt.reports.sru import SRU_ENCODING

            info_file = output_path / "INFO.SRU"
            blank_file = output_path / "BLANKETTER.SRU"
            info_file.write_text(export.info_sru, encoding=SRU_ENCODING)
            blank_file.write_text(export.blanketter_sru, encoding=SRU_ENCODING)
            typer.echo(f"SRU files written to {info_file} and {blank_file}")
        else:
            typer.echo(f"Error: Unknown format '{format}'. Use 'csv', 'json' or 'sru'.", err=True)
            raise typer.Exit(code=1)

        # Generate full transaction list if requested
        if full:
            full_path = output_path / f"transactions_{year}.csv"
            generator.generate_full_transaction_list(year, full_path)
            typer.echo(f"Full transaction list written to {full_path}")

    finally:
        session.close()
