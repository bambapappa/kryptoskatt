"""SRU export for the Swedish K4 form (Skatteverket electronic filing).

Produces the two files Skatteverket's "Filöverföring" service accepts:

- ``INFO.SRU``        — filer identity (personnummer, name, address)
- ``BLANKETTER.SRU``  — the K4 form data itself

Cryptocurrencies are reported in **K4 Avsnitt D** ("Övriga tillgångar
… kryptovalutor …"). Field codes for section D rows are 3410–3475
(``34<row>0``..``34<row>5`` for antal/beteckning/försäljningspris/
omkostnadsbelopp/vinst/förlust) with a maximum of 7 rows per form page;
the per-page summary lives in 3500/3501/3503/3504. Each additional page
is a new ``#BLANKETT`` block numbered via field 7014.

Unlike shares, crypto amounts may be fractional — Skatteverket accepts a
decimal *antal* with a comma separator and up to eight decimals
(e.g. ``0,06`` for 0.06 BTC). Monetary amounts are whole kronor.

Field codes verified against the Skatteverket K4 specification and the
open-source generators ebtcap/K4SRU and duga3/K4Skatt.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from kryptoskatt import __version__
from kryptoskatt.models.disposal import Disposal

# Section D: max rows per K4 page, and the field-code base.
ROWS_PER_PAGE = 7
_ROW_BASE = 34  # row field codes are "34<row>x": 3410..3475
# Section D summary field codes
_SUM_PROCEEDS = "3500"
_SUM_COST = "3501"
_SUM_GAIN = "3503"
_SUM_LOSS = "3504"
# K4 form version suffix in the blankett id (stable across recent years).
K4_FORM_VERSION = "P4"

_LINE_SEP = "\r\n"  # SRU records are CR+LF separated
SRU_ENCODING = "iso-8859-1"


@dataclass
class SruTaxpayer:
    """The person the K4 is filed for. personnummer must be 12 digits."""

    personnummer: str
    namn: str
    postnummer: str = ""
    postort: str = ""
    adress: str = ""
    epost: str = ""

    def normalized_pnr(self) -> str:
        """Return the personnummer as 12 digits (YYYYMMDDNNNN) or raise."""
        digits = self.personnummer.replace("-", "").replace(" ", "").replace("+", "")
        if len(digits) != 12 or not digits.isdigit():
            raise ValueError(
                "Personnummer måste anges med 12 siffror (ÅÅÅÅMMDDNNNN), "
                f"fick: {self.personnummer!r}"
            )
        return digits


@dataclass
class SruRow:
    """One aggregated K4 section-D row (one coin)."""

    antal: Decimal
    beteckning: str
    forsaljningspris: int
    omkostnadsbelopp: int
    vinst: int
    forlust: int


@dataclass
class SruExport:
    info_sru: str
    blanketter_sru: str


def _format_antal(amount: Decimal) -> str:
    """Format a crypto amount: comma decimal, ≤8 decimals, no trailing zeros."""
    q = amount.quantize(Decimal("0.00000001")).normalize()
    # normalize() can yield exponent form for integers (e.g. 1E+2) — expand it
    text = format(q, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _round_krona(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class K4SruGenerator:
    """Generates K4 SRU files (section D — cryptocurrencies) from disposals."""

    def __init__(self, session: Session, user_id: int):
        self._session = session
        self._user_id = user_id

    def _aggregate_rows(self, year: int) -> list[SruRow]:
        """One row per coin, aggregated over the year, sorted by coin."""
        disposals = self._session.execute(
            select(Disposal).where(
                Disposal.user_id == self._user_id,
                Disposal.tax_year == year,
            )
        ).scalars().all()

        by_coin: dict[str, dict[str, Decimal]] = {}
        for d in disposals:
            agg = by_coin.setdefault(
                d.coin,
                {"antal": Decimal("0"), "proceeds": Decimal("0"), "cost": Decimal("0")},
            )
            agg["antal"] += abs(Decimal(str(d.sell_amount)))
            agg["proceeds"] += Decimal(str(d.proceeds_sek))
            agg["cost"] += Decimal(str(d.cost_basis_sek))

        rows: list[SruRow] = []
        for coin in sorted(by_coin):
            agg = by_coin[coin]
            proceeds = _round_krona(agg["proceeds"])
            cost = _round_krona(agg["cost"])
            gain = proceeds - cost
            rows.append(SruRow(
                antal=agg["antal"],
                beteckning=coin[:80],
                forsaljningspris=proceeds,
                omkostnadsbelopp=cost,
                vinst=gain if gain > 0 else 0,
                forlust=-gain if gain < 0 else 0,
            ))
        return rows

    def generate(self, year: int, taxpayer: SruTaxpayer, *, created_at: datetime | None = None) -> SruExport:
        """Build INFO.SRU + BLANKETTER.SRU for the given year.

        Raises ValueError if there are no disposals for the year or the
        taxpayer's personnummer is malformed.
        """
        pnr = taxpayer.normalized_pnr()
        rows = self._aggregate_rows(year)
        if not rows:
            raise ValueError(f"Inga avyttringar att redovisa för {year}")

        created_at = created_at or datetime.now(UTC)
        info = self._build_info(taxpayer, pnr)
        blanketter = self._build_blanketter(year, rows, pnr, taxpayer.namn, created_at)
        return SruExport(info_sru=info, blanketter_sru=blanketter)

    def _build_info(self, taxpayer: SruTaxpayer, pnr: str) -> str:
        lines = [
            "#DATABESKRIVNING_START",
            "#PRODUKT SRU",
            f"#PROGRAM KryptoSkatt {__version__}",
            "#FILNAMN BLANKETTER.SRU",
            "#DATABESKRIVNING_SLUT",
            "#MEDIELEV_START",
            f"#ORGNR {pnr}",
            f"#NAMN {taxpayer.namn}",
        ]
        if taxpayer.adress:
            lines.append(f"#ADRESS {taxpayer.adress}")
        if taxpayer.postnummer:
            lines.append(f"#POSTNR {taxpayer.postnummer}")
        if taxpayer.postort:
            lines.append(f"#POSTORT {taxpayer.postort}")
        if taxpayer.epost:
            lines.append(f"#EMAIL {taxpayer.epost}")
        lines.append("#MEDIELEV_SLUT")
        return _LINE_SEP.join(lines) + _LINE_SEP

    def _build_blanketter(
        self, year: int, rows: list[SruRow], pnr: str, namn: str, created_at: datetime
    ) -> str:
        date_str = created_at.strftime("%Y%m%d %H%M%S")
        pages = [rows[i:i + ROWS_PER_PAGE] for i in range(0, len(rows), ROWS_PER_PAGE)]
        lines: list[str] = []

        for page_no, page_rows in enumerate(pages, start=1):
            lines.append(f"#BLANKETT K4-{year}{K4_FORM_VERSION}")
            lines.append(f"#IDENTITET {pnr} {date_str}")
            lines.append(f"#NAMN {namn}")

            sum_proceeds = sum_cost = sum_gain = sum_loss = 0
            for row_idx, row in enumerate(page_rows, start=1):
                base = f"{_ROW_BASE}{row_idx}"  # 341, 342, … 347
                lines.append(f"#UPPGIFT {base}0 {_format_antal(row.antal)}")
                lines.append(f"#UPPGIFT {base}1 {row.beteckning}")
                lines.append(f"#UPPGIFT {base}2 {row.forsaljningspris}")
                lines.append(f"#UPPGIFT {base}3 {row.omkostnadsbelopp}")
                lines.append(f"#UPPGIFT {base}4 {row.vinst}")
                lines.append(f"#UPPGIFT {base}5 {row.forlust}")
                sum_proceeds += row.forsaljningspris
                sum_cost += row.omkostnadsbelopp
                sum_gain += row.vinst
                sum_loss += row.forlust

            lines.append(f"#UPPGIFT {_SUM_PROCEEDS} {sum_proceeds}")
            lines.append(f"#UPPGIFT {_SUM_COST} {sum_cost}")
            lines.append(f"#UPPGIFT {_SUM_GAIN} {sum_gain}")
            lines.append(f"#UPPGIFT {_SUM_LOSS} {sum_loss}")
            lines.append(f"#UPPGIFT 7014 {page_no}")
            lines.append("#BLANKETTSLUT")

        lines.append("#FIL_SLUT")
        return _LINE_SEP.join(lines) + _LINE_SEP
