"""K4 Report Generator for Swedish Skatteverket tax reports."""

import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from kryptoskatt.models.disposal import Disposal
from kryptoskatt.schemas import K4Report, K4SummaryRow


class K4ReportGenerator:
    """Generates K4 tax reports from Disposal records."""

    def __init__(self, session: Session, user_id: int):
        """Initialize with a database session and user_id.

        Args:
            session: SQLAlchemy session for database queries.
            user_id: Account DB id to scope queries to.
        """
        self._session = session
        self._user_id = user_id

    def generate(self, year: int) -> K4Report:
        """Generate K4 report for a given tax year.

        Queries all Disposal records for the year, groups by coin,
        calculates per-coin sums and totals.

        Args:
            year: The tax year to generate the report for.

        Returns:
            K4Report with rows per coin and totals.
        """
        # Query all disposals for the given year
        stmt = select(Disposal).where(
            Disposal.user_id == self._user_id,
            Disposal.tax_year == year,
        )
        disposals = self._session.execute(stmt).scalars().all()

        # Group by coin
        coin_data: dict[str, dict[str, Decimal]] = {}
        for disposal in disposals:
            coin = disposal.coin
            if coin not in coin_data:
                coin_data[coin] = {
                    "proceeds_sek": Decimal("0"),
                    "cost_basis_sek": Decimal("0"),
                    "gain_loss_sek": Decimal("0"),
                }

            coin_data[coin]["proceeds_sek"] += disposal.proceeds_sek
            coin_data[coin]["cost_basis_sek"] += disposal.cost_basis_sek
            coin_data[coin]["gain_loss_sek"] += disposal.gain_loss_sek

        # Create K4SummaryRow for each coin, rounding to 2 decimal places
        rows: list[K4SummaryRow] = []
        total_gains = Decimal("0")
        total_losses = Decimal("0")

        for coin, data in coin_data.items():
            # Round to 2 decimal places for final output
            proceeds = data["proceeds_sek"].quantize(Decimal("0.01"))
            cost_basis = data["cost_basis_sek"].quantize(Decimal("0.01"))
            gain_loss = data["gain_loss_sek"].quantize(Decimal("0.01"))

            rows.append(
                K4SummaryRow(
                    coin=coin,
                    proceeds_sek=proceeds,
                    cost_basis_sek=cost_basis,
                    gain_loss_sek=gain_loss,
                )
            )

            # Track totals (gains are positive, losses are negative)
            if gain_loss > 0:
                total_gains += gain_loss
            elif gain_loss < 0:
                total_losses += abs(gain_loss)

        # Round totals to 2 decimal places
        total_gains = total_gains.quantize(Decimal("0.01"))
        total_losses = total_losses.quantize(Decimal("0.01"))

        return K4Report(
            tax_year=year,
            rows=rows,
            total_gains=total_gains,
            total_losses=total_losses,
        )

    @staticmethod
    def export_csv(report: K4Report, output_path: Path) -> None:
        """Export K4 report to CSV with Swedish headers.

        Args:
            report: The K4Report to export.
            output_path: Path to write the CSV file.
        """
        # Swedish headers
        headers = ["Tillgång", "Försäljningspris SEK", "Omkostnadsbelopp SEK", "Vinst/Förlust SEK"]

        # Calculate totals
        sum_proceeds = sum(row.proceeds_sek for row in report.rows)
        sum_cost_basis = sum(row.cost_basis_sek for row in report.rows)
        sum_gain_loss = sum(row.gain_loss_sek for row in report.rows)

        lines = [",".join(headers)]

        # Add data rows (coin order is deterministic from dict)
        for row in report.rows:
            lines.append(f"{row.coin},{row.proceeds_sek},{row.cost_basis_sek},{row.gain_loss_sek}")

        # Add total row
        lines.append(f"TOTALT,{sum_proceeds},{sum_cost_basis},{sum_gain_loss}")

        # Write with UTF-8 BOM for Excel Swedish locale compatibility
        content = "\n".join(lines)
        output_path.write_text(content, encoding="utf-8-sig")

    @staticmethod
    def export_json(report: K4Report, output_path: Path) -> None:
        """Export K4 report to JSON.

        Args:
            report: The K4Report to export.
            output_path: Path to write the JSON file.
        """
        # Convert to dict with Decimal values as strings for precision
        data = {
            "tax_year": report.tax_year,
            "rows": [
                {
                    "coin": row.coin,
                    "proceeds_sek": str(row.proceeds_sek),
                    "cost_basis_sek": str(row.cost_basis_sek),
                    "gain_loss_sek": str(row.gain_loss_sek),
                }
                for row in report.rows
            ],
            "total_gains": str(report.total_gains),
            "total_losses": str(report.total_losses),
        }

        # Use Pydantic's model_dump for proper serialization
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        output_path.write_text(json_str, encoding="utf-8")

    def generate_full_transaction_list(self, year: int, output_path: Path) -> None:
        """Generate detailed disposal list for the given year.

        This is the "underlag" Skatteverket may request for 10-year retention.

        Args:
            year: The tax year to generate the transaction list for.
            output_path: Path to write the CSV file.
        """
        # Query all disposals for the year, ordered chronologically
        stmt = (
            select(Disposal)
            .where(Disposal.user_id == self._user_id, Disposal.tax_year == year)
            .order_by(Disposal.sell_timestamp)
        )
        disposals = self._session.execute(stmt).scalars().all()

        # Swedish headers
        headers = [
            "Datum",
            "Tillgång",
            "Antal",
            "Försäljningspris SEK",
            "Omkostnadsbelopp SEK",
            "Vinst/Förlust SEK",
            "GAV vid försäljning SEK",
        ]

        lines = [",".join(headers)]

        # Add data rows (sell_amount is negative, use absolute value for display)
        for d in disposals:
            # Format date as YYYY-MM-DD
            date_str = d.sell_timestamp.strftime("%Y-%m-%d")
            amount = abs(d.sell_amount)  # Display positive amount

            lines.append(
                f"{date_str},{d.coin},{amount},{d.proceeds_sek},{d.cost_basis_sek},{d.gain_loss_sek},{d.gav_at_disposal}"
            )

        # Write with UTF-8 BOM for Excel compatibility
        content = "\n".join(lines)
        output_path.write_text(content, encoding="utf-8-sig")
