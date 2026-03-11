"""Audit export: all transactions for a tax year with explorer URLs.

Provides a complete, verifiable record of all transactions supporting K4 and T2
reports. Designed to be handed to Skatteverket so they can independently verify
each transaction on-chain.

Columns exported:
  rapport, datum, tid, typ, tillgång, antal, pris_sek, belopp_sek,
  tx_hash, explorer_url, källa, från_adress, till_adress
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import extract
from sqlalchemy.orm import Session

from kryptoskatt.enums import EventType
from kryptoskatt.models.transaction import Transaction
from kryptoskatt.models.transfer_link import TransferLink
from kryptoskatt.models.wallet import Wallet

# Map source_platform → blockchain explorer prefix
# tx_hash is appended directly
_EXPLORER_PREFIXES: dict[str, str] = {
    "helius":     "https://solscan.io/tx/",
    "solscan":    "https://solscan.io/tx/",
}

_ETHERSCAN_EXPLORERS: dict[str, str] = {
    "ETHEREUM": "https://etherscan.io/tx/",
    "POLYGON":  "https://polygonscan.com/tx/",
    "BNB":      "https://bscscan.com/tx/",
}

# Event types that are taxable disposals (K4)
_DISPOSAL_TYPES = {EventType.SELL.value, EventType.SWAP_OUT.value, EventType.TRANSFER_OUT.value}
# Event types that are acquisitions (K4 counterpart — shown for context)
_ACQUISITION_TYPES = {EventType.BUY.value, EventType.SWAP_IN.value, EventType.TRANSFER_IN.value}


@dataclass
class AuditRow:
    rapport: str           # K4-Avyttring | K4-Anskaffning | T2-Intäkt | T2-Kostnad | Intern | Övrigt
    datum: date
    tid: str               # HH:MM UTC
    typ: str               # event_type
    tillgang: str          # base_coin
    antal: Decimal
    pris_sek: Optional[Decimal]
    belopp_sek: Optional[Decimal]
    tx_hash: Optional[str]
    explorer_url: str
    kalla: str             # source_platform
    fran_adress: Optional[str]
    till_adress: Optional[str]


class AuditExport:
    """Generates a complete transaction audit trail for a tax year."""

    def __init__(self, session: Session):
        self.session = session

    def generate(self, year: int) -> list[AuditRow]:
        # ── Build lookup tables ────────────────────────────────────────────
        # wallet_id → chain (for Etherscan URL resolution)
        wallet_chain: dict[int, str] = {
            w.id: w.chain for w in self.session.query(Wallet).all()
        }
        # address → category (for T2 income/cost classification)
        wallet_category: dict[str, str] = {
            w.address: w.category
            for w in self.session.query(Wallet).all()
            if w.address
        }
        # tx_ids that are linked as internal transfers (both sides registered)
        internal_tx_ids: set[int] = set()
        for link in self.session.query(TransferLink).all():
            internal_tx_ids.add(link.tx_out_id)
            if link.tx_in_id is not None:
                internal_tx_ids.add(link.tx_in_id)

        # Income-source addresses (mining_pool, depin)
        income_addresses = {
            addr for addr, cat in wallet_category.items()
            if cat in ("mining_pool", "depin")
        }
        # Cost-destination addresses (hardware_vendor)
        cost_addresses = {
            addr for addr, cat in wallet_category.items()
            if cat == "hardware_vendor"
        }

        # ── Query all non-duplicate transactions for the year ──────────────
        txs = (
            self.session.query(Transaction)
            .filter(
                Transaction.is_duplicate.is_(False),
                extract("year", Transaction.timestamp_utc) == year,
            )
            .order_by(Transaction.timestamp_utc, Transaction.id)
            .all()
        )

        rows: list[AuditRow] = []
        for tx in txs:
            rapport = self._classify(tx, internal_tx_ids, income_addresses, cost_addresses)
            explorer_url = self._explorer_url(tx, wallet_chain)

            amount = abs(tx.base_amount) if tx.base_amount is not None else Decimal("0")
            belopp: Optional[Decimal] = None
            if tx.price_sek is not None and amount:
                belopp = (amount * tx.price_sek).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            rows.append(
                AuditRow(
                    rapport=rapport,
                    datum=tx.timestamp_utc.date(),
                    tid=tx.timestamp_utc.strftime("%H:%M"),
                    typ=tx.event_type,
                    tillgang=tx.base_coin,
                    antal=amount.normalize(),
                    pris_sek=tx.price_sek,
                    belopp_sek=belopp,
                    tx_hash=tx.tx_hash,
                    explorer_url=explorer_url,
                    kalla=tx.source_platform,
                    fran_adress=tx.from_address,
                    till_adress=tx.to_address,
                )
            )

        return rows

    def export_csv(self, year: int) -> str:
        """Return CSV string with BOM for Excel compatibility."""
        rows = self.generate(year)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "Rapport", "Datum", "Tid (UTC)", "Typ", "Tillgång", "Antal",
            "Pris (SEK/enhet)", "Belopp (SEK)", "TX-hash", "Explorer-URL",
            "Källa", "Från-adress", "Till-adress",
        ])
        for r in rows:
            writer.writerow([
                r.rapport,
                r.datum.isoformat(),
                r.tid,
                r.typ,
                r.tillgang,
                r.antal,
                r.pris_sek if r.pris_sek is not None else "",
                r.belopp_sek if r.belopp_sek is not None else "",
                r.tx_hash or "",
                r.explorer_url,
                r.kalla,
                r.fran_adress or "",
                r.till_adress or "",
            ])
        return "\ufeff" + buf.getvalue()  # BOM for Excel

    # ── Private helpers ────────────────────────────────────────────────────

    def _classify(
        self,
        tx: Transaction,
        internal_tx_ids: set[int],
        income_addresses: set[str],
        cost_addresses: set[str],
    ) -> str:
        et = tx.event_type

        # T2 income: REWARD or TRANSFER_IN from income address
        if et == EventType.REWARD.value:
            return "T2-Intäkt"
        if et == EventType.TRANSFER_IN.value and tx.from_address in income_addresses:
            return "T2-Intäkt"

        # T2 cost: outgoing payment to hardware_vendor
        if et in _DISPOSAL_TYPES and tx.to_address in cost_addresses:
            return "T2-Kostnad"

        # Internal transfer (both sides registered as own)
        if tx.id in internal_tx_ids:
            return "Intern"

        # K4 disposal
        if et in _DISPOSAL_TYPES:
            return "K4-Avyttring"

        # K4 acquisition (BUY, SWAP_IN, TRANSFER_IN)
        if et in _ACQUISITION_TYPES:
            return "K4-Anskaffning"

        return "Övrigt"

    def _explorer_url(self, tx: Transaction, wallet_chain: dict[int, str]) -> str:
        if not tx.tx_hash:
            return ""

        platform = (tx.source_platform or "").lower()

        # Solana
        if platform in _EXPLORER_PREFIXES:
            return _EXPLORER_PREFIXES[platform] + tx.tx_hash

        # Etherscan-family: derive chain from the wallet
        if "etherscan" in platform:
            chain = wallet_chain.get(tx.wallet_id or 0, "ETHEREUM")
            prefix = _ETHERSCAN_EXPLORERS.get(chain, _ETHERSCAN_EXPLORERS["ETHEREUM"])
            return prefix + tx.tx_hash

        return ""
