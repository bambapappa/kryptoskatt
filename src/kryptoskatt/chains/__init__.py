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
    from kryptoskatt.chains.tronscan import TronscanAdapter
    registry.register(TronscanAdapter())
    from kryptoskatt.chains.xrpl import XrplAdapter
    registry.register(XrplAdapter())
    from kryptoskatt.chains.blockscout import BlockscoutAdapter
    registry.register(BlockscoutAdapter())
    from kryptoskatt.chains.vechain import VeChainAdapter
    registry.register(VeChainAdapter())
    from kryptoskatt.chains.chainweb import ChainwebAdapter
    registry.register(ChainwebAdapter())
    return registry


def get_registry_for_user(session, account_id: int) -> ChainRegistry:
    """Build registry including user's custom chain adapters."""
    registry = get_registry()
    from kryptoskatt.models.custom_chain_config import CustomChainConfig
    configs = session.query(CustomChainConfig).filter(
        CustomChainConfig.account_id == account_id
    ).all()
    for cfg in configs:
        if cfg.adapter_type == "blockscout":
            from kryptoskatt.chains.blockscout import DynamicBlockscoutAdapter
            adapter = DynamicBlockscoutAdapter(
                chain_name=cfg.chain_name,
                base_url=cfg.explorer_url,
                native_coin=cfg.native_coin or cfg.chain_name,
            )
        elif cfg.adapter_type == "etherscan":
            from kryptoskatt.chains.etherscan import DynamicEtherscanAdapter
            adapter = DynamicEtherscanAdapter(
                chain_name=cfg.chain_name,
                chain_id=cfg.chain_id or 1,
                api_key=cfg.api_key or "",
                native_coin=cfg.native_coin or "ETH",
            )
        else:
            continue
        registry.register(adapter)
    return registry


__all__ = ["ChainAdapter", "ChainRegistry", "get_registry", "get_registry_for_user"]
