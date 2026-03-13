"""MEXC TSV parser for deposit, withdrawal, and trade exports."""

import csv
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate

# Network to Chain mapping
NETWORK_TO_CHAIN: dict[str, Chain] = {
    "Ethereum(ERC20)": Chain.ETHEREUM,
    "Solana(SOL)": Chain.SOLANA,
    "Polygon(MATIC)": Chain.POLYGON,
    "BNB Smart Chain(BEP20)": Chain.BNB,
    "KDA": Chain.KADENA,
    "PEAQ": Chain.PEAQ,
    "TRON(TRC20)": Chain.TRON,
    "Bitcoin(BTC)": Chain.BITCOIN,
    "BASE": Chain.BASE,
    "Arbitrum One(ARB)": Chain.ARBITRUM,
    "XRP": Chain.RIPPLE,
    "VeChain(VET)": Chain.VECHAIN,
}


def strip_tx_suffix(txid: str) -> str:
    """Strip :NNN suffix from TxID for cross-platform matching."""
    if ":" in txid:
        # Split on last colon and check if the suffix is numeric
        parts = txid.rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0]
    return txid


def parse_timestamp(timestamp_str: str) -> datetime:
    """Parse MEXC timestamp string to UTC datetime."""
    dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=UTC)


def map_network_to_chain(network: str) -> Chain:
    """Map MEXC network string to Chain enum."""
    return NETWORK_TO_CHAIN.get(network, Chain.UNKNOWN)


class MexcParser:
    """Parser for MEXC TSV export files."""

    # Swedish column headers for different file types
    DEPOSIT_HEADERS = {"Insättningsbelopp"}
    WITHDRAWAL_HEADERS = {"Uttagsadress"}
    TRADE_HEADERS = {"Kvantitet"}

    def parse(self, file_path: Path) -> tuple[list[TransactionCreate], list[str]]:
        """
        Parse MEXC TSV file and return transactions and errors.

        Args:
            file_path: Path to the TSV file

        Returns:
            Tuple of (transactions: list[TransactionCreate], errors: list[str])
        """
        transactions: list[TransactionCreate] = []
        errors: list[str] = []

        with open(file_path, encoding="utf-8") as f:
            first_line = f.readline()
            delimiter = ";" if ";" in first_line else "\t"
            f.seek(0)
            reader = csv.reader(f, delimiter=delimiter)
            headers = next(reader)

            # Detect file type from headers
            file_type = self._detect_file_type(headers)
            if file_type is None:
                errors.append(f"Unknown MEXC file type. Headers: {headers}")
                return transactions, errors

            # Build header index
            header_index = {header: idx for idx, header in enumerate(headers)}

            for row_num, row in enumerate(reader, start=2):
                try:
                    if len(row) < len(headers):
                        errors.append(f"Row {row_num}: Not enough columns")
                        continue

                    # Skip failed/pending deposit rows (Status column present in newer exports).
                    # Only filter deposits — withdrawal/trade statuses use different wording.
                    if file_type == "deposit" and "Status" in header_index:
                        status = row[header_index["Status"]]
                        if status and "krediterats" not in status.lower() and "completed" not in status.lower():
                            continue

                    tx = self._parse_row(row, header_index, file_type)
                    if tx is not None:
                        transactions.append(tx)
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")

        return transactions, errors

    def _detect_file_type(self, headers: list[str]) -> str | None:
        """Detect file type from headers."""
        header_set = set(headers)
        if self.DEPOSIT_HEADERS.intersection(header_set):
            return "deposit"
        if self.WITHDRAWAL_HEADERS.intersection(header_set):
            return "withdrawal"
        if self.TRADE_HEADERS.intersection(header_set):
            return "trade"
        return None

    def _parse_row(
        self, row: list[str], header_index: dict[str, int], file_type: str
    ) -> TransactionCreate | None:
        """Parse a single row based on file type."""
        if file_type == "deposit":
            return self._parse_deposit_row(row, header_index)
        if file_type == "withdrawal":
            return self._parse_withdrawal_row(row, header_index)
        if file_type == "trade":
            return self._parse_trade_row(row, header_index)
        return None

    def _parse_deposit_row(self, row: list[str], header_index: dict[str, int]) -> TransactionCreate:
        """Parse a deposit row."""
        raw_payload = dict(zip(header_index.keys(), row))

        timestamp = parse_timestamp(row[header_index["Tid"]])
        crypto = row[header_index["Krypto"]]
        network = row[header_index["Nätverk"]]
        amount = Decimal(row[header_index["Insättningsbelopp"]])
        txid = row[header_index["TxID"]]

        chain = map_network_to_chain(network)
        raw_payload["chain"] = chain.value

        return TransactionCreate(
            source_platform="MEXC",
            timestamp_utc=timestamp,
            event_type=EventType.TRANSFER_IN,
            base_coin=crypto,
            base_amount=amount,
            tx_hash=strip_tx_suffix(txid),
            raw_payload=raw_payload,
        )

    def _parse_withdrawal_row(
        self, row: list[str], header_index: dict[str, int]
    ) -> TransactionCreate:
        """Parse a withdrawal row."""
        raw_payload = dict(zip(header_index.keys(), row))

        timestamp = parse_timestamp(row[header_index["Tid"]])
        crypto = row[header_index["Krypto"]]
        network = row[header_index["Nätverk"]]
        # Use settlement amount (Avräkningsbelopp) as base amount
        settlement_amount = Decimal(row[header_index["Avräkningsbelopp"]])
        fee_amount = Decimal(row[header_index["Handelsavgift"]])
        txid = row[header_index["TxID"]]
        to_address = row[header_index["Uttagsadress"]]

        chain = map_network_to_chain(network)
        raw_payload["chain"] = chain.value

        # Negative amount for TRANSFER_OUT
        return TransactionCreate(
            source_platform="MEXC",
            timestamp_utc=timestamp,
            event_type=EventType.TRANSFER_OUT,
            base_coin=crypto,
            base_amount=-settlement_amount,  # Negative for TRANSFER_OUT
            fee_coin=crypto,
            fee_amount=fee_amount,
            tx_hash=strip_tx_suffix(txid),
            to_address=to_address,
            raw_payload=raw_payload,
        )

    def _parse_trade_row(self, row: list[str], header_index: dict[str, int]) -> TransactionCreate:
        """Parse a trade row."""
        raw_payload = dict(zip(header_index.keys(), row))

        timestamp = parse_timestamp(row[header_index["Tid"]])
        crypto = row[header_index["Krypto"]]
        amount = Decimal(row[header_index["Kvantitet"]])
        trade_type = row[header_index["Typ"]]

        # Determine event type from trade type
        if trade_type in ("Köp", "Buy", "köp", "buy"):
            event_type = EventType.BUY
        elif trade_type in ("Sälj", "Sell", "sälj", "sell"):
            event_type = EventType.SELL
            amount = -amount  # Negative for SELL
        else:
            event_type = EventType.UNKNOWN

        return TransactionCreate(
            source_platform="MEXC",
            timestamp_utc=timestamp,
            event_type=event_type,
            base_coin=crypto,
            base_amount=amount,
            raw_payload=raw_payload,
        )
