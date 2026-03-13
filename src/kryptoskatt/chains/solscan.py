"""Solscan v2 API adapter for Solana transactions."""

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.config import settings
from kryptoskatt.enums import Chain, EventType
from kryptoskatt.schemas import TransactionCreate

logger = logging.getLogger(__name__)


class SolscanAdapter(ChainAdapter):
    """Adapter for Solscan v2 API — Solana chain."""

    BASE_URL = "https://pro-api.solscan.io/v2.0"

    # Known DePIN distribution addresses — transfers FROM these = REWARD
    # Full address pattern from systemdesign.md: FceP6wv...9GfMDsp (GEOD rewards)
    DEPIN_REWARD_ADDRESSES: set[str] = {
        "FceP6wv4GkdG7GfMDsp",  # GEOD distribution (partial for matching)
    }

    # Known SPL token decimals (fallback when API doesn't provide)
    KNOWN_TOKEN_DECIMALS: dict[str, int] = {
        "GEOD": 6,
        "USDC": 6,
        "SOL": 9,
    }

    def supported_chains(self) -> list[Chain]:
        """Return list of chains this adapter handles."""
        return [Chain.SOLANA]

    def rate_limit_delay(self) -> float:
        """Seconds to wait between API calls. Conservative for Solscan."""
        return 0.5

    def fetch_transactions(self, address: str, chain: Chain) -> list[TransactionCreate]:
        """Fetch all transactions for an address on Solana.

        Makes two API calls:
        1. SOL transfers: /account/transactions
        2. SPL token transfers: /account/token/txs

        Returns combined list of TransactionCreate objects.
        """
        if not settings.solscan_api_key:
            logger.warning("Solscan API key not configured, returning empty list")
            return []

        transactions: list[TransactionCreate] = []

        # Fetch SOL transfers
        sol_txs = self._fetch_sol_transfers(address)
        transactions.extend(sol_txs)

        # Fetch SPL token transfers
        spl_txs = self._fetch_spl_transfers(address)
        transactions.extend(spl_txs)

        return transactions

    def _fetch_sol_transfers(self, address: str) -> list[TransactionCreate]:
        """Fetch all SOL transfers from Solscan v2 API using cursor-based pagination."""
        url = f"{self.BASE_URL}/account/transactions"
        transactions = []
        before_hash: str | None = None

        try:
            while True:
                params: dict[str, Any] = {"address": address, "limit": 40}
                if before_hash:
                    params["before_hash"] = before_hash

                response = self._make_request(url, params)
                if not response:
                    break

                data = response.get("data", [])
                if not data:
                    break

                for tx in data:
                    parsed = self._parse_sol_transfer(tx, address)
                    if parsed:
                        transactions.append(parsed)

                if len(data) < 40:
                    break  # last page

                before_hash = data[-1].get("txHash")
                if not before_hash:
                    break

                time.sleep(self.rate_limit_delay())

        except Exception as e:
            logger.error(f"Error fetching SOL transfers: {e}")

        return transactions

    def _fetch_spl_transfers(self, address: str) -> list[TransactionCreate]:
        """Fetch all SPL token transfers from Solscan v2 API using cursor-based pagination."""
        url = f"{self.BASE_URL}/account/token/txs"
        transactions = []
        before_hash: str | None = None

        try:
            while True:
                params: dict[str, Any] = {"address": address, "limit": 40}
                if before_hash:
                    params["before_hash"] = before_hash

                response = self._make_request(url, params)
                if not response:
                    break

                data = response.get("data", [])
                if not data:
                    break

                for tx in data:
                    parsed = self._parse_spl_transfer(tx, address)
                    if parsed:
                        transactions.append(parsed)

                if len(data) < 40:
                    break  # last page

                before_hash = data[-1].get("txHash")
                if not before_hash:
                    break

                time.sleep(self.rate_limit_delay())

        except Exception as e:
            logger.error(f"Error fetching SPL transfers: {e}")

        return transactions

    def _make_request(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Make HTTP request to Solscan API with proper headers."""
        headers = {"token": settings.solscan_api_key}

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for {url}: {e}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error for {url}: {e}")
            return None

    def _parse_sol_transfer(self, tx: dict[str, Any], our_address: str) -> TransactionCreate | None:
        """Parse a SOL transfer transaction from Solscan response."""
        try:
            tx_hash = tx.get("txHash", "")
            block_time = tx.get("blockTime", 0)
            parsed_instructions = tx.get("parsedInstruction", [])

            if not tx_hash:
                return None

            # Find SOL transfer instruction
            for instruction in parsed_instructions:
                if instruction.get("type") == "sol-transfer":
                    params = instruction.get("params", {})
                    source = params.get("source", "")
                    destination = params.get("destination", "")
                    amount_lamports = params.get("amount", 0)

                    if not source or not destination:
                        continue

                    # Determine event type and direction
                    event_type, from_addr, to_addr = self._classify_sol_transfer(
                        source, destination, our_address
                    )

                    # Convert lamports to SOL (9 decimals)
                    amount = Decimal(amount_lamports) / Decimal(10**9)

                    # Fee in lamports
                    fee_lamports = tx.get("fee", 0)
                    fee = Decimal(fee_lamports) / Decimal(10**9)

                    return TransactionCreate(
                        source_platform="solscan",
                        timestamp_utc=datetime.fromtimestamp(block_time, tz=UTC),
                        event_type=event_type,
                        base_coin="SOL",
                        base_amount=amount,
                        fee_coin="SOL" if fee > 0 else None,
                        fee_amount=fee if fee > 0 else None,
                        tx_hash=tx_hash,
                        from_address=from_addr,
                        to_address=to_addr,
                        raw_payload=tx,
                    )

            return None

        except Exception as e:
            logger.warning(f"Error parsing SOL transfer: {e}")
            return None

    def _parse_spl_transfer(self, tx: dict[str, Any], our_address: str) -> TransactionCreate | None:
        """Parse an SPL token transfer from Solscan response."""
        try:
            tx_hash = tx.get("txHash", "")
            block_time = tx.get("blockTime", 0)
            from_addr = tx.get("from", "")
            to_addr = tx.get("to", "")
            amount_raw = tx.get("amount", 0)
            token_symbol = tx.get("tokenSymbol", "")
            token_decimals = tx.get("tokenDecimals", 0)

            if not tx_hash or not token_symbol:
                return None

            # Determine event type
            event_type, from_address, to_address = self._classify_spl_transfer(
                from_addr, to_addr, our_address
            )

            # Get decimals (fallback to known list if not provided)
            if token_decimals == 0:
                token_decimals = self.KNOWN_TOKEN_DECIMALS.get(token_symbol, 6)

            # Convert to Decimal
            amount = Decimal(amount_raw) / Decimal(10**token_decimals)

            return TransactionCreate(
                source_platform="solscan",
                timestamp_utc=datetime.fromtimestamp(block_time, tz=UTC),
                event_type=event_type,
                base_coin=token_symbol,
                base_amount=amount,
                tx_hash=tx_hash,
                from_address=from_address,
                to_address=to_address,
                raw_payload=tx,
            )

        except Exception as e:
            logger.warning(f"Error parsing SPL transfer: {e}")
            return None

    def _classify_sol_transfer(
        self, source: str, destination: str, our_address: str
    ) -> tuple[str, str, str]:
        """Classify SOL transfer as TRANSFER_IN, TRANSFER_OUT, or REWARD."""
        # Check if this is from a DePIN reward address
        is_reward = any(source.startswith(addr) for addr in self.DEPIN_REWARD_ADDRESSES)

        if is_reward:
            return EventType.REWARD, source, destination

        if destination.lower() == our_address.lower():
            return EventType.TRANSFER_IN, source, destination
        elif source.lower() == our_address.lower():
            return EventType.TRANSFER_OUT, source, destination

        # Default to transfer
        return EventType.TRANSFER_IN, source, destination

    def _classify_spl_transfer(
        self, source: str, destination: str, our_address: str
    ) -> tuple[str, str, str]:
        """Classify SPL transfer as TRANSFER_IN, TRANSFER_OUT, or REWARD."""
        # Check if this is from a DePIN reward address
        is_reward = any(source.startswith(addr) for addr in self.DEPIN_REWARD_ADDRESSES)

        if is_reward:
            return EventType.REWARD, source, destination

        if destination.lower() == our_address.lower():
            return EventType.TRANSFER_IN, source, destination
        elif source.lower() == our_address.lower():
            return EventType.TRANSFER_OUT, source, destination

        # Default to transfer
        return EventType.TRANSFER_IN, source, destination
