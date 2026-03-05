"""Crypto.com CSV parser."""

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from kryptoskatt.enums import EventType, Platform
from kryptoskatt.schemas import TransactionCreate


@dataclass
class ParseResult:
    """Result from parsing a CSV file."""

    transactions: list[TransactionCreate]
    errors: list[str]


class CryptoComParser:
    """Parser for Crypto.com CSV exports."""

    def parse(self, file_path: Path) -> ParseResult:
        """
        Parse a Crypto.com CSV export file.

        Args:
            file_path: Path to the CSV file

        Returns:
            ParseResult with transactions and errors
        """
        transactions: list[TransactionCreate] = []
        errors: list[str] = []

        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row_num, row in enumerate(reader, start=2):  # Start at 2 (1 is header)
                try:
                    txn = self._parse_row(row)
                    if txn:
                        transactions.extend(txn)
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")

        return ParseResult(transactions=transactions, errors=errors)

    def _parse_row(self, row: dict[str, str]) -> list[TransactionCreate]:
        """Parse a single CSV row into TransactionCreate objects."""
        raw_payload: dict[str, Any] = dict(row)

        # Parse timestamp
        timestamp_str = row.get("Timestamp (UTC)", "").strip()
        timestamp_utc = self._parse_timestamp(timestamp_str)

        # Parse transaction kind
        transaction_kind = row.get("Transaction Kind", "").strip()

        # Parse common fields
        currency = row.get("Currency", "").strip()
        amount_str = row.get("Amount", "").strip()
        to_currency = row.get("To Currency", "").strip()
        to_amount_str = row.get("To Amount", "").strip()
        native_amount_str = row.get("Native Amount", "").strip()
        tx_hash = row.get("Transaction Hash", "").strip()

        # Parse amounts as Decimal
        amount = self._parse_decimal(amount_str)
        to_amount = self._parse_decimal(to_amount_str)
        price_sek = self._parse_decimal(native_amount_str)

        # Handle different transaction kinds
        if transaction_kind == "crypto_exchange":
            return self._handle_crypto_exchange(
                timestamp_utc,
                currency,
                amount,
                to_currency,
                to_amount,
                price_sek,
                tx_hash,
                raw_payload,
            )
        elif transaction_kind == "crypto_wallet_swap_credited":
            return [
                self._create_transaction(
                    timestamp_utc,
                    EventType.SWAP_IN,
                    currency,
                    amount,
                    to_currency,
                    to_amount,
                    price_sek,
                    tx_hash,
                    raw_payload,
                )
            ]
        elif transaction_kind == "crypto_wallet_swap_debited":
            return [
                self._create_transaction(
                    timestamp_utc,
                    EventType.SWAP_OUT,
                    currency,
                    amount,
                    to_currency,
                    to_amount,
                    price_sek,
                    tx_hash,
                    raw_payload,
                )
            ]
        elif transaction_kind == "crypto_withdrawal":
            return [
                self._create_transaction(
                    timestamp_utc,
                    EventType.TRANSFER_OUT,
                    currency,
                    amount,
                    None,
                    None,
                    price_sek,
                    tx_hash,
                    raw_payload,
                )
            ]
        elif transaction_kind == "crypto_deposit":
            return [
                self._create_transaction(
                    timestamp_utc,
                    EventType.TRANSFER_IN,
                    currency,
                    amount,
                    None,
                    None,
                    price_sek,
                    tx_hash,
                    raw_payload,
                )
            ]
        elif "earn" in transaction_kind.lower() or "interest" in transaction_kind.lower():
            return [
                self._create_transaction(
                    timestamp_utc,
                    EventType.REWARD,
                    currency,
                    amount,
                    None,
                    None,
                    price_sek,
                    tx_hash,
                    raw_payload,
                )
            ]
        else:
            # Unknown transaction kind - skip silently or could raise
            return []

    def _handle_crypto_exchange(
        self,
        timestamp_utc: datetime,
        currency: str,
        amount: Decimal,
        to_currency: str,
        to_amount: Decimal,
        price_sek: Decimal | None,
        tx_hash: str,
        raw_payload: dict[str, Any],
    ) -> list[TransactionCreate]:
        """Handle crypto_exchange rows - create SWAP_OUT and SWAP_IN pairs."""
        transactions = []

        # SWAP_OUT: the sold currency (Currency/Amount columns)
        swap_out = self._create_transaction(
            timestamp_utc,
            EventType.SWAP_OUT,
            currency,
            amount,
            to_currency,
            to_amount,
            price_sek,
            tx_hash,
            raw_payload,
        )
        transactions.append(swap_out)

        # SWAP_IN: the bought currency (To Currency/To Amount columns)
        # quote_amount should be the positive amount of the sold currency
        quote_amount_for_swap_in = abs(amount) if amount else None
        swap_in = self._create_transaction(
            timestamp_utc,
            EventType.SWAP_IN,
            to_currency,
            to_amount,
            currency,
            quote_amount_for_swap_in,
            price_sek,
            tx_hash,
            raw_payload,
        )
        transactions.append(swap_in)

        return transactions

    def _create_transaction(
        self,
        timestamp_utc: datetime,
        event_type: EventType,
        base_coin: str,
        base_amount: Decimal,
        quote_coin: str | None,
        quote_amount: Decimal | None,
        price_sek: Decimal | None,
        tx_hash: str | None,
        raw_payload: dict[str, Any],
    ) -> TransactionCreate:
        """Create a TransactionCreate object."""
        return TransactionCreate(
            source_platform=Platform.CRYPTO_COM,
            timestamp_utc=timestamp_utc,
            event_type=event_type,
            base_coin=base_coin,
            base_amount=base_amount,
            quote_coin=quote_coin if quote_coin else None,
            quote_amount=quote_amount,
            tx_hash=tx_hash if tx_hash else None,
            price_sek=price_sek,
            raw_payload=raw_payload,
        )

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse timestamp string to datetime with UTC timezone."""
        # Format: "2025-11-07 14:31:06"
        dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)

    def _parse_decimal(self, value_str: str) -> Decimal | None:
        """Parse a string to Decimal, returning None if empty."""
        if not value_str or value_str.strip() == "":
            return None
        return Decimal(value_str.strip())
