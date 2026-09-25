"""Chain adapters for blockchain transaction fetching."""

from kryptoskatt.chains.base import ChainAdapter
from kryptoskatt.chains.registry import ChainRegistry


def get_registry(api_keys: dict[str, str] | None = None) -> ChainRegistry:
    """Create a registry with all available adapters pre-registered.

    Import adapters lazily to avoid import errors when API keys aren't configured.

    ``api_keys`` optionally maps provider slugs ("etherscan", "helius",
    "solscan", "tronscan", "vechainstats", "subscan") to effective keys. When a
    slug is absent, the adapter falls back to the instance key from settings.

    Solana: registers HeliusAdapter when a Helius key is effective; falls back to
    SolscanAdapter when only a Solscan key is effective; omits Solana support
    when neither is present.
    """
    from kryptoskatt.config import settings

    keys = api_keys or {}

    def key_for(slug: str, settings_attr: str) -> str:
        return keys.get(slug) or getattr(settings, settings_attr, "")

    registry = ChainRegistry()
    from kryptoskatt.chains.etherscan import EtherscanAdapter
    registry.register(EtherscanAdapter(api_key=key_for("etherscan", "etherscan_api_key")))

    # Solana adapter — prefer Helius, fall back to Solscan
    helius_key = key_for("helius", "helius_api_key")
    solscan_key = key_for("solscan", "solscan_api_key")
    if helius_key:
        from kryptoskatt.chains.helius import HeliusAdapter
        registry.register(HeliusAdapter(api_key=helius_key))
    elif solscan_key:
        from kryptoskatt.chains.solscan import SolscanAdapter
        registry.register(SolscanAdapter(api_key=solscan_key))

    from kryptoskatt.chains.bitcoin import BitcoinAdapter
    registry.register(BitcoinAdapter())
    from kryptoskatt.chains.subscan import SubscanAdapter
    registry.register(SubscanAdapter(api_key=key_for("subscan", "subscan_api_key")))
    from kryptoskatt.chains.tronscan import TronscanAdapter
    registry.register(TronscanAdapter(api_key=key_for("tronscan", "tronscan_api_key")))
    from kryptoskatt.chains.xrpl import XrplAdapter
    registry.register(XrplAdapter())
    from kryptoskatt.chains.blockscout import KEYLESS_EVM_CONFIG, BlockscoutAdapter
    registry.register(BlockscoutAdapter())
    if not key_for("etherscan", "etherscan_api_key"):
        # No Etherscan key: use free public Blockscout instances instead.
        registry.register(BlockscoutAdapter(KEYLESS_EVM_CONFIG))
    from kryptoskatt.chains.vechain import VeChainAdapter
    registry.register(VeChainAdapter(api_key=key_for("vechainstats", "vechainstats_api_key")))
    from kryptoskatt.chains.chainweb import ChainwebAdapter
    registry.register(ChainwebAdapter())
    return registry


def get_registry_for_user(session, account_id: int) -> ChainRegistry:
    """Build registry including the account's own API keys and custom chains."""
    from kryptoskatt.services.api_keys import resolve_api_keys

    registry = get_registry(resolve_api_keys(session, account_id))
    from kryptoskatt.models.custom_chain_config import CustomChainConfig
    from kryptoskatt.services.secrets import decrypt_secret
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
                api_key=decrypt_secret(cfg.api_key),
                native_coin=cfg.native_coin or "ETH",
            )
        else:
            continue
        registry.register(adapter)
    return registry


# Chains that can only be fetched with a (free) API key: chain → accepted
# provider slugs (any one of them is enough) and the env var shown to users.
KEY_REQUIRED: dict[str, tuple[tuple[str, ...], str]] = {
    "BNB": (("etherscan",), "ETHERSCAN_API_KEY"),
    "SOLANA": (("helius", "solscan"), "HELIUS_API_KEY"),
    "PEAQ": (("subscan",), "SUBSCAN_API_KEY"),
    "TRON": (("tronscan",), "TRONSCAN_API_KEY"),
    "VECHAIN": (("vechainstats",), "VECHAINSTATS_API_KEY"),
}


def missing_api_key(chain: str, effective_keys: dict[str, str]) -> str | None:
    """Name of the key a chain still needs, or None when it can be fetched.

    ``effective_keys`` is the output of ``resolve_api_keys`` (the account's
    own keys, falling back to the instance keys). Chains not listed in
    KEY_REQUIRED (Bitcoin, XRP, Kadena, and ETH/Base/Arbitrum/Polygon via
    keyless Blockscout) never need a key.
    """
    rule = KEY_REQUIRED.get(str(chain).upper())
    if rule is None:
        return None
    slugs, env_name = rule
    return None if any(effective_keys.get(s) for s in slugs) else env_name


__all__ = [
    "KEY_REQUIRED",
    "ChainAdapter",
    "ChainRegistry",
    "get_registry",
    "get_registry_for_user",
    "missing_api_key",
]
