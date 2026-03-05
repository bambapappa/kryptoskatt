"""Coinbase CSV parser."""

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from kryptoskatt.schemas import TransactionCreate


@dataclass
class ParseResult:
    """Result of parsing a CSV file."""

    transactions: list[TransactionCreate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CoinbaseParser:
    """Parser for Coinbase CSV exports."""

    # Column names from Coinbase CSV header
    COL_ID = "ID"
    COL_TIMESTAMP = "Timestamp"
    COL_TRANSACTION_TYPE = "Transaction Type"
    COL_ASSET = "Asset"
    COL_QUANTITY = "Quantity Transacted"
    COL_PRICE_CURRENCY = "Price Currency"
    COL_PRICE_AT_TRANSACTION = "Price at Transaction"
    COL_SUBTOTAL = "Subtotal"
    COL_TOTAL = "Total (inclusive of fees and/or spread)"
    COL_FEES = "Fees and/or Spread"
    COL_NOTES = "Notes"

    def parse(self, file_path: Path) -> ParseResult:
        """Parse a Coinbase CSV export file.

        Args:
            file_path: Path to the CSV file.

        Returns:
            ParseResult containing transactions and errors.
        """
        transactions = []
        errors = []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                # Check if first line is metadata (e.g., "Transactions")
                first_line = f.readline().strip()
                if first_line == "Transactions":
                    # Skip second metadata line (e.g., "User,...")
                    f.readline()
                else:
                    # Not a Coinbase format with metadata - reset to beginning
                    f.seek(0)
                reader = csv.DictReader(f)

                for row_num, row in enumerate(reader, start=4):  # Start at 4 (after 3 header lines)
                    try:
                        txs = self._parse_row(row)
                        transactions.extend(txs)
                    except Exception as e:
                        error_msg = f"Row {row_num}: {str(e)}"
                        errors.append(error_msg)

        except Exception as e:
            errors.append(f"Failed to read file: {str(e)}")

        return ParseResult(transactions=transactions, errors=errors)

    def _parse_row(self, row: dict[str, str]) -> list[TransactionCreate]:
        """Parse a single CSV row into TransactionCreate objects.

        Args:
            row: CSV row as dict.

        Returns:
            List of TransactionCreate objects (1 for most types, 2 for Convert).
        """
        tx_type = row.get(self.COL_TRANSACTION_TYPE, "").strip()
        timestamp_str = row.get(self.COL_TIMESTAMP, "").strip()
        asset = row.get(self.COL_ASSET, "").strip()
        quantity_str = row.get(self.COL_QUANTITY, "").strip()
        price_str = row.get(self.COL_PRICE_AT_TRANSACTION, "").strip()
        subtotal_str = row.get(self.COL_SUBTOTAL, "").strip()
        total_str = row.get(self.COL_TOTAL, "").strip()
        fees_str = row.get(self.COL_FEES, "").strip()
        notes = row.get(self.COL_NOTES, "").strip()

        # Parse the values first
        timestamp = self._parse_timestamp(timestamp_str)
        quantity = self._parse_amount(quantity_str)
        price_sek = self._parse_price(price_str)
        fee = self._parse_amount(fees_str)

        # Validate required fields
        if quantity_str and quantity is None:
            raise ValueError(f"Invalid quantity: '{quantity_str}'")
        if timestamp is None:
            raise ValueError(f"Invalid timestamp: '{timestamp_str}'")

        # Parse quote amount from subtotal (Total less fees = subtotal)
        quote_amount = self._parse_amount(subtotal_str)

        raw_payload = dict(row)

        # Map transaction type to event type(s)
        if tx_type == "Buy":
            return [
                self._create_buy(
                    timestamp=timestamp,
                    asset=asset,
                    quantity=quantity,
                    price_sek=price_sek,
                    quote_amount=quote_amount,
                    fee=fee,
                    raw_payload=raw_payload,
                )
            ]
        elif tx_type == "Sell":
            return [
                self._create_sell(
                    timestamp=timestamp,
                    asset=asset,
                    quantity=quantity,
                    price_sek=price_sek,
                    quote_amount=quote_amount,
                    fee=fee,
                    raw_payload=raw_payload,
                )
            ]
        elif tx_type == "Send":
            return [
                self._create_transfer_out(
                    timestamp=timestamp,
                    asset=asset,
                    quantity=quantity,
                    price_sek=price_sek,
                    notes=notes,
                    raw_payload=raw_payload,
                )
            ]
        elif tx_type == "Receive":
            return [
                self._create_transfer_in(
                    timestamp=timestamp,
                    asset=asset,
                    quantity=quantity,
                    price_sek=price_sek,
                    notes=notes,
                    raw_payload=raw_payload,
                )
            ]
        elif tx_type == "Convert":
            return self._create_swap_pair(
                timestamp=timestamp,
                asset=asset,
                quantity=quantity,
                notes=notes,
                price_sek=price_sek,
                fee=fee,
                raw_payload=raw_payload,
            )
        elif tx_type == "Reward":
            return [
                self._create_reward(
                    timestamp=timestamp,
                    asset=asset,
                    quantity=quantity,
                    raw_payload=raw_payload,
                )
            ]
        else:
            # Unknown type - create a generic transaction
            return [
                self._create_unknown(
                    timestamp=timestamp,
                    asset=asset,
                    quantity=quantity,
                    tx_type=tx_type,
                    raw_payload=raw_payload,
                )
            ]

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse timestamp string to datetime with UTC timezone.

        Args:
            timestamp_str: Timestamp string like "2025-09-08 10:46:38 UTC".

        Returns:
            datetime object with UTC timezone.
        """
        # Remove " UTC" suffix and parse
        ts = timestamp_str.replace(" UTC", "").strip()
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)

    def _parse_amount(self, amount_str: str) -> Decimal | None:
        """Parse amount string to Decimal.

        Handles:
        - Regular numbers: "100.50"
        - Negative with minus: "-100.50"
        - Swedish krona prefix: "kr100.50"
        - Negative with prefix: "-kr100.50" or "kr-100.50"

        Args:
            amount_str: Amount string from CSV.

        Returns:
            Decimal value or None if empty.
        """
        if not amount_str or amount_str.strip() == "":
            return None

        s = amount_str.strip()

        # Handle negative prefix like "-kr100.50" or "kr-100.50"
        is_negative = s.startswith("-") or s.startswith("-kr") or s.startswith("kr-")

        # Strip all non-numeric characters except decimal point and minus
        s = re.sub(r"[^0-9.-]", "", s)

        if not s or s == "-" or s == ".":
            return None

        try:
            return Decimal(s)
        except Exception:
            return None

    def _parse_price(self, price_str: str) -> Decimal | None:
        """Parse price string to Decimal.

        Handles Swedish krona prefix like "kr2.201200722149897974117269".

        Args:
            price_str: Price string from CSV.

        Returns:
            Decimal value or None if empty.
        """
        if not price_str or price_str.strip() == "":
            return None

        s = price_str.strip()

        # Strip "kr" prefix (case insensitive)
        s = re.sub(r"^-?kr", "", s, flags=re.IGNORECASE)

        if not s:
            return None

        try:
            return Decimal(s)
        except Exception:
            return None

    def _extract_address_from_notes(self, notes: str, pattern: str) -> str | None:
        """Extract address from notes using regex pattern.

        Args:
            notes: Notes string.
            pattern: Regex pattern with one capture group.

        Returns:
            Extracted address or None.
        """
        if not notes:
            return None

        match = re.search(pattern, notes)
        if match:
            return match.group(1)
        return None

    def _create_buy(
        self,
        timestamp: datetime,
        asset: str,
        quantity: Decimal,
        price_sek: Decimal | None,
        quote_amount: Decimal | None,
        fee: Decimal | None,
        raw_payload: dict[str, Any],
    ) -> TransactionCreate:
        """Create a BUY transaction."""
        return TransactionCreate(
            source_platform="COINBASE",
            timestamp_utc=timestamp,
            event_type="BUY",
            base_coin=asset,
            base_amount=quantity,
            quote_coin="SEK",
            quote_amount=quote_amount,
            fee_coin="SEK" if fee else None,
            fee_amount=fee,
            price_sek=price_sek,
            raw_payload=raw_payload,
        )

    def _create_sell(
        self,
        timestamp: datetime,
        asset: str,
        quantity: Decimal,
        price_sek: Decimal | None,
        quote_amount: Decimal | None,
        fee: Decimal | None,
        raw_payload: dict[str, Any],
    ) -> TransactionCreate:
        """Create a SELL transaction."""
        return TransactionCreate(
            source_platform="COINBASE",
            timestamp_utc=timestamp,
            event_type="SELL",
            base_coin=asset,
            base_amount=quantity,  # Negative for sell
            quote_coin="SEK",
            quote_amount=quote_amount,
            fee_coin="SEK" if fee else None,
            fee_amount=fee,
            price_sek=price_sek,
            raw_payload=raw_payload,
        )

    def _create_transfer_out(
        self,
        timestamp: datetime,
        asset: str,
        quantity: Decimal,
        price_sek: Decimal | None,
        notes: str,
        raw_payload: dict[str, Any],
    ) -> TransactionCreate:
        """Create a TRANSFER_OUT (Send) transaction."""
        # Extract address from notes like:
        # "Sent 91.799939 ALEO to aleo1ml4jys95lhw35zj6fqfsp9e9ws54v2h2ke85fnnqmcqc0ndczy8svwk9eq (to aleo1...wk9eq)"
        to_address = self._extract_address_from_notes(
            notes,
            r"Sent\s+[\d.]+\s+\w+\s+to\s+([a-zA-Z0-9]+)",
        )

        return TransactionCreate(
            source_platform="COINBASE",
            timestamp_utc=timestamp,
            event_type="TRANSFER_OUT",
            base_coin=asset,
            base_amount=quantity,  # Already negative in CSV
            to_address=to_address,
            price_sek=price_sek,
            raw_payload=raw_payload,
        )

    def _create_transfer_in(
        self,
        timestamp: datetime,
        asset: str,
        quantity: Decimal,
        price_sek: Decimal | None,
        notes: str,
        raw_payload: dict[str, Any],
    ) -> TransactionCreate:
        """Create a TRANSFER_IN (Receive) transaction."""
        # Extract addresses from notes like:
        # "Received 0.04268882 SOL from an external account (from 5LWTG...eDgHg to 5FhSP...MAVXk)"
        from_address = self._extract_address_from_notes(
            notes,
            r"\(from\s+([a-zA-Z0-9]+)",
        )
        to_address = self._extract_address_from_notes(
            notes,
            r"to\s+([a-zA-Z0-9]+.*?)\)",
        )

        return TransactionCreate(
            source_platform="COINBASE",
            timestamp_utc=timestamp,
            event_type="TRANSFER_IN",
            base_coin=asset,
            base_amount=quantity,
            from_address=from_address,
            to_address=to_address,
            price_sek=price_sek,
            raw_payload=raw_payload,
        )

    def _create_swap_pair(
        self,
        timestamp: datetime,
        asset: str,
        quantity: Decimal,
        notes: str,
        price_sek: Decimal | None,
        fee: Decimal | None,
        raw_payload: dict[str, Any],
    ) -> list[TransactionCreate]:
        """Create SWAP_OUT and SWAP_IN pair from Convert transaction.

        Notes format: "Converted 7.53325 XRP to 91.799939 ALEO"

        Args:
            timestamp: Transaction timestamp.
            asset: Original asset (the one being converted FROM).
            quantity: Amount of original asset (negative in CSV).
            notes: Notes containing swap details.
            price_sek: Price in SEK.
            raw_payload: Original row data.

        Returns:
            List of two transactions: SWAP_OUT and SWAP_IN.
        """
        # Parse the convert notes: "Converted 7.53325 XRP to 91.799939 ALEO"
        match = re.match(r"Converted\s+([\d.]+)\s+(\w+)\s+to\s+([\d.]+)\s+(\w+)", notes)
        if not match:
            # Fallback: create unknown transaction
            return [self._create_unknown(timestamp, asset, quantity, "Convert", raw_payload)]

        from_amount = Decimal(match.group(1))
        from_coin = match.group(2)
        to_amount = Decimal(match.group(3))
        to_coin = match.group(4)

        # SWAP_OUT: the original coin being given away (negative amount)
        swap_out = TransactionCreate(
            source_platform="COINBASE",
            timestamp_utc=timestamp,
            event_type="SWAP_OUT",
            base_coin=from_coin,
            base_amount=-from_amount,  # Negative to indicate sent
            quote_coin=to_coin,
            quote_amount=to_amount,
            fee_coin="SEK" if fee else None,
            fee_amount=fee,
            price_sek=price_sek,
            raw_payload=raw_payload,
        )

        # SWAP_IN: the new coin being received (positive amount)
        swap_in = TransactionCreate(
            source_platform="COINBASE",
            timestamp_utc=timestamp,
            event_type="SWAP_IN",
            base_coin=to_coin,
            base_amount=to_amount,
            quote_coin=from_coin,
            quote_amount=from_amount,
            price_sek=price_sek,
            raw_payload=raw_payload,
        )


        return [swap_out, swap_in]

    def _create_reward(
        self,
        timestamp: datetime,
        asset: str,
        quantity: Decimal,
        raw_payload: dict[str, Any],
    ) -> TransactionCreate:
        """Create a REWARD transaction."""
        return TransactionCreate(
            source_platform="COINBASE",
            timestamp_utc=timestamp,
            event_type="REWARD",
            base_coin=asset,
            base_amount=quantity,
            raw_payload=raw_payload,
        )

    def _create_unknown(
        self,
        timestamp: datetime,
        asset: str,
        quantity: Decimal,
        tx_type: str,
        raw_payload: dict[str, Any],
    ) -> TransactionCreate:
        """Create an UNKNOWN transaction type."""
        return TransactionCreate(
            source_platform="COINBASE",
            timestamp_utc=timestamp,
            event_type="UNKNOWN",
            base_coin=asset,
            base_amount=quantity,
            raw_payload=raw_payload,
        )
