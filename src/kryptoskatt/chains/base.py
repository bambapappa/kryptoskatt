"""Abstract base class for blockchain chain adapters."""

from abc import ABC, abstractmethod

from kryptoskatt.schemas import TransactionCreate


class ChainAdapter(ABC):
    """Base class that all chain adapters must implement."""

    @abstractmethod
    def supported_chains(self) -> list[str]:
        """Return list of chains this adapter handles."""
        ...

    @abstractmethod
    def fetch_transactions(self, address: str, chain: str) -> list[TransactionCreate]:
        """Fetch all transactions for an address on the given chain."""
        ...

    def rate_limit_delay(self) -> float:
        """Seconds to wait between API calls. Override in subclass if needed."""
        return 0.2
