"""Chain adapter registry — dispatches to correct adapter per chain."""

import logging

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.enums import Chain

logger = logging.getLogger(__name__)


class ChainRegistry:
    """Registry that maps chains to their adapters."""

    def __init__(self) -> None:
        self._adapters: dict[Chain, ChainAdapter] = {}

    def register(self, adapter: ChainAdapter) -> None:
        """Register an adapter for all its supported chains."""
        for chain in adapter.supported_chains():
            self._adapters[chain] = adapter

    def get_adapter(self, chain: Chain) -> ChainAdapter | None:
        """Get adapter for a chain, or None if unsupported."""
        adapter = self._adapters.get(chain)
        if adapter is None:
            logger.warning("No adapter for chain %s, skipping", chain)
        return adapter

    def supported_chains(self) -> list[Chain]:
        """Return all chains that have registered adapters."""
        return list(self._adapters.keys())

    def fetch_all(self, wallets: list) -> list:
        """Fetch transactions for all wallets, dispatching to correct adapter.

        Args:
            wallets: List of wallet objects with .address and .chain attributes.

        Returns:
            List of TransactionCreate objects from all adapters.
        """
        from kryptoskatt.schemas import TransactionCreate

        results: list[TransactionCreate] = []
        for wallet in wallets:
            adapter = self.get_adapter(wallet.chain)
            if adapter is None:
                logger.warning(
                    "No adapter for chain %s, skipping address %s",
                    wallet.chain,
                    wallet.address,
                )
                continue
            txs = adapter.fetch_transactions(wallet.address, wallet.chain)
            results.extend(txs)
        return results
