"""Helius API adapter for Solana transactions."""

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

# Known SPL token mint addresses → symbol
KNOWN_MINTS: dict[str, str] = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "So11111111111111111111111111111111111111112": "SOL",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "mSOL",
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj": "stSOL",
    "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux": "HNT",
    "mb1eu7TzEc71KxDpsmsKoucSSuuoGLv1drys1oP2jh6": "MOBILE",
    "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns": "IOT",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
    "onoyC1ZjHNtT2tShqvVSg5WEcQDbu5zht6sdU9Nwjrc": "ONO",   # Onocoy
    "CzYSquESBM4qVQiFas6pSMgeFRG4JLiYyNYHQUcNxudc": "BONO",
}

# Dust threshold: ignore native SOL transfers at or below this (lamports)
# 5000 = typical tx fee, used as spam/rent filter
DUST_THRESHOLD_LAMPORTS = 5000


class HeliusAdapter(ChainAdapter):
    """Adapter for Helius API — Solana chain."""

    BASE_URL = "https://api.helius.xyz/v0"

    def supported_chains(self) -> list[Chain]:
        return [Chain.SOLANA]

    def rate_limit_delay(self) -> float:
        return 0.2  # Helius free tier: 10 req/s

    def fetch_transactions(self, address: str, chain: Chain) -> list[TransactionCreate]:
        """Fetch all transactions for a Solana address via Helius parsed-transactions API.

        Also fetches transactions for all SPL token accounts owned by the wallet.
        This is necessary because Helius indexes batch-payout transactions (e.g.
        GEODNET paying 10 recipients at once) under the token account address
        (toUserAccount = CAGf...) rather than the wallet owner (9wyst...), so
        those transactions never appear in the wallet's own feed.
        """
        if not settings.helius_api_key:
            logger.warning("Helius API key not configured, returning empty list")
            return []

        mint_symbol_cache: dict[str, str] = {}

        # Fetch for the main wallet address
        transactions = self._fetch_address_transactions(address, address, mint_symbol_cache)

        # Also fetch for each SPL token account so we capture all incoming
        # token transfers regardless of how Helius indexed them
        token_accounts = self._get_token_accounts(address)
        for token_account in token_accounts:
            ta_txs = self._fetch_address_transactions(token_account, address, mint_symbol_cache)
            transactions.extend(ta_txs)

        return transactions

    def _fetch_address_transactions(
        self,
        fetch_address: str,
        owner_address: str,
        mint_cache: dict[str, str],
    ) -> list[TransactionCreate]:
        """Paginate through all transactions for fetch_address.

        When fetch_address is a SPL token account (different from owner_address),
        _parse_tx is called with fetch_address so that tokenTransfer entries
        addressed to the token account are accepted. Any resulting to_address
        equal to the token account is then normalised to owner_address so the
        rest of the system sees the wallet-owner address.
        """
        transactions: list[TransactionCreate] = []
        before: str | None = None
        is_token_account = fetch_address != owner_address

        while True:
            params: dict[str, Any] = {
                "api-key": settings.helius_api_key,
                "limit": 100,
            }
            if before:
                params["before"] = before

            url = f"{self.BASE_URL}/addresses/{fetch_address}/transactions"
            batch = self._get(url, params)
            if not batch:
                break

            for tx in batch:
                if is_token_account:
                    # Helius always resolves toUserAccount to the wallet owner
                    # (e.g. 9wyst...) even when the transaction was fetched via
                    # the token account endpoint (CAGf...).  Using owner_address
                    # here lets _parse_tx match those entries correctly.
                    parsed = self._parse_tx(tx, owner_address, mint_cache)
                else:
                    parsed = self._parse_tx(tx, fetch_address, mint_cache)
                transactions.extend(parsed)

            if len(batch) < 100:
                break

            before = batch[-1].get("signature")
            if not before:
                break

            time.sleep(self.rate_limit_delay())

        return transactions

    def _get_token_accounts(self, wallet_address: str) -> list[str]:
        """Return SPL token account addresses owned by wallet_address.

        Uses the Helius balances endpoint which lists all token accounts for a
        wallet. These are needed to catch incoming token transfers that were
        indexed by Helius under the token account address rather than the
        wallet-owner address.
        """
        url = f"{self.BASE_URL}/addresses/{wallet_address}/balances"
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, params={"api-key": settings.helius_api_key})
                resp.raise_for_status()
                data = resp.json()
                return [t["tokenAccount"] for t in data.get("tokens", []) if t.get("tokenAccount")]
        except Exception as e:
            logger.warning(f"Could not fetch token accounts for {wallet_address}: {e}")
            return []

    def _parse_tx(
        self,
        tx: dict[str, Any],
        address: str,
        mint_cache: dict[str, str],
    ) -> list[TransactionCreate]:
        """Parse a single Helius transaction into TransactionCreate objects."""
        results: list[TransactionCreate] = []
        sig = tx.get("signature", "")
        timestamp = tx.get("timestamp", 0)
        fee_lamports = tx.get("fee", 0)
        fee_payer = tx.get("feePayer", "")
        dt = datetime.fromtimestamp(timestamp, tz=UTC)

        # SOL fee paid by our address
        fee_sol = Decimal(fee_lamports) / Decimal(10**9) if fee_payer == address else None

        # --- Native SOL transfers ---
        for nt in tx.get("nativeTransfers", []):
            from_acc = nt.get("fromUserAccount", "")
            to_acc = nt.get("toUserAccount", "")
            lamports = nt.get("amount", 0)

            if from_acc != address and to_acc != address:
                continue

            # Skip dust / spam (rent payments, 1-lamport probes)
            if lamports <= DUST_THRESHOLD_LAMPORTS:
                continue

            amount = Decimal(lamports) / Decimal(10**9)
            event_type = EventType.TRANSFER_IN if to_acc == address else EventType.TRANSFER_OUT

            results.append(
                TransactionCreate(
                    source_platform="helius",
                    timestamp_utc=dt,
                    event_type=event_type,
                    base_coin="SOL",
                    base_amount=amount if event_type == EventType.TRANSFER_IN else -amount,
                    fee_coin="SOL" if fee_sol else None,
                    fee_amount=fee_sol,
                    tx_hash=sig,
                    from_address=from_acc,
                    to_address=to_acc,
                    raw_payload=tx,
                )
            )

        # --- SPL token transfers ---
        # Track mints already captured as incoming via tokenTransfers so the
        # accountData fallback below doesn't double-count them.
        covered_incoming_mints: set[str] = set()

        for tt in tx.get("tokenTransfers", []):
            from_acc = tt.get("fromUserAccount", "")
            to_acc = tt.get("toUserAccount", "")
            token_amount = tt.get("tokenAmount", 0)
            mint = tt.get("mint", "")

            if from_acc != address and to_acc != address:
                continue

            if not token_amount or not mint:
                continue

            symbol = self._resolve_mint(mint, mint_cache)
            amount = Decimal(str(token_amount))
            event_type = EventType.TRANSFER_IN if to_acc == address else EventType.TRANSFER_OUT

            if event_type == EventType.TRANSFER_IN:
                covered_incoming_mints.add(mint)

            results.append(
                TransactionCreate(
                    source_platform="helius",
                    timestamp_utc=dt,
                    event_type=event_type,
                    base_coin=symbol,
                    base_amount=amount if event_type == EventType.TRANSFER_IN else -amount,
                    tx_hash=sig,
                    from_address=from_acc,
                    to_address=to_acc,
                    raw_payload=tx,
                )
            )

        # --- Fallback: accountData token balance changes ---
        # Helius batch-payout transactions (e.g. GEODNET paying 10 wallets at
        # once) sometimes set toUserAccount to the SPL token account address
        # (e.g. CAGf...) rather than the wallet owner (9wyst...).  Our filter
        # above then skips them.  accountData.tokenBalanceChanges always uses
        # the wallet-owner address, so we use it to catch what tokenTransfers
        # missed.
        for acc_data in tx.get("accountData", []):
            for change in acc_data.get("tokenBalanceChanges", []):
                if change.get("userAccount") != address:
                    continue

                mint = change.get("mint", "")
                if not mint or mint in covered_incoming_mints:
                    continue  # already handled via tokenTransfers

                raw = change.get("rawTokenAmount", {})
                token_amount_raw = Decimal(str(raw.get("tokenAmount", "0")))
                decimals = int(raw.get("decimals", 6))

                if token_amount_raw <= 0:
                    continue  # negative = outgoing, skip

                amount = token_amount_raw / Decimal(10**decimals)
                symbol = self._resolve_mint(mint, mint_cache)

                # Locate the sender from tokenTransfers for this mint
                from_acc = ""
                for tt in tx.get("tokenTransfers", []):
                    if tt.get("mint") == mint:
                        from_acc = tt.get("fromUserAccount", "")
                        break

                covered_incoming_mints.add(mint)
                results.append(
                    TransactionCreate(
                        source_platform="helius",
                        timestamp_utc=dt,
                        event_type=EventType.TRANSFER_IN,
                        base_coin=symbol,
                        base_amount=amount,
                        tx_hash=sig,
                        from_address=from_acc,
                        to_address=address,
                        raw_payload=tx,
                    )
                )

        return results

    def _resolve_mint(self, mint: str, cache: dict[str, str]) -> str:
        """Resolve a mint address to a token symbol. Falls back to shortened mint."""
        if mint in cache:
            return cache[mint]

        symbol = KNOWN_MINTS.get(mint)
        if not symbol:
            # Try Helius token metadata API
            symbol = self._fetch_mint_symbol(mint) or mint[:8]

        cache[mint] = symbol
        return symbol

    def _fetch_mint_symbol(self, mint: str) -> str | None:
        """Fetch token symbol from Helius token metadata endpoint."""
        try:
            url = f"{self.BASE_URL}/token-metadata"
            params = {"api-key": settings.helius_api_key}
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, params=params, json={"mintAccounts": [mint]})
                resp.raise_for_status()
                data = resp.json()
                if data and isinstance(data, list) and data[0]:
                    meta = data[0]
                    # Try onChainMetadata first, then legacyMetadata
                    symbol = (
                        meta.get("onChainMetadata", {})
                        .get("metadata", {})
                        .get("data", {})
                        .get("symbol")
                    ) or (
                        meta.get("legacyMetadata", {}).get("symbol")
                    )
                    return symbol.strip() if symbol else None
        except Exception as e:
            logger.debug(f"Could not fetch metadata for mint {mint}: {e}")
        return None

    def _get(self, url: str, params: dict[str, Any]) -> list[dict[str, Any]] | None:
        """GET request to Helius API."""
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for {url}: {e}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error for {url}: {e}")
            return None
