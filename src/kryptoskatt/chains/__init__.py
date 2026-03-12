"""Chain adapters for blockchain transaction fetching."""

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.chains.registry import ChainRegistry


def get_registry() -> ChainRegistry:
    """Create a registry with all available adapters pre-registered.

    Import adapters lazily to avoid import errors when API keys aren't configured.
    """
    registry = ChainRegistry()
    from kryptoskatt.chains.etherscan import EtherscanAdapter
    registry.register(EtherscanAdapter())
    from kryptoskatt.chains.helius import HeliusAdapter
    registry.register(HeliusAdapter())
    from kryptoskatt.chains.bitcoin import BitcoinAdapter
    registry.register(BitcoinAdapter())
    from kryptoskatt.chains.subscan import SubscanAdapter
    registry.register(SubscanAdapter())
    return registry


__all__ = ["ChainAdapter", "ChainRegistry", "get_registry"]
