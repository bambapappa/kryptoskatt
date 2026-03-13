"""Registry of known blockchain contract addresses for auto-tagging."""

import re

# Maps lowercase address → {name, category, chain}
KNOWN_CONTRACTS: dict[str, dict] = {
    # --- DEX routers (Ethereum) ---
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d": {
        "name": "Uniswap V2 Router",
        "category": "dex",
        "chain": "ETHEREUM",
    },
    "0xe592427a0aece92de3edee1f18e0157c05861564": {
        "name": "Uniswap V3 Router",
        "category": "dex",
        "chain": "ETHEREUM",
    },
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": {
        "name": "Uniswap V3 Router 2",
        "category": "dex",
        "chain": "ETHEREUM",
    },
    "0x1111111254eeb25477b68fb85ed929f73a960582": {
        "name": "1inch V5",
        "category": "dex",
        "chain": "ETHEREUM",
    },
    "0x111111125421ca6dc452d289314280a0f8842a65": {
        "name": "1inch V6",
        "category": "dex",
        "chain": "ETHEREUM",
    },
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f": {
        "name": "SushiSwap Router",
        "category": "dex",
        "chain": "ETHEREUM",
    },
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": {
        "name": "Uniswap Universal Router",
        "category": "dex",
        "chain": "ETHEREUM",
    },
    "0xec7be89e9d109e7e3fec59c222cf297125fefda2": {
        "name": "Uniswap Universal Router 2",
        "category": "dex",
        "chain": "ETHEREUM",
    },
    # --- DEX routers (Base) ---
    "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24": {
        "name": "Uniswap V2 Router",
        "category": "dex",
        "chain": "BASE",
    },
    "0x2626664c2603336e57b271c5c0b26f421741e481": {
        "name": "Uniswap V3 Router 2",
        "category": "dex",
        "chain": "BASE",
    },
    "0x198ef79f1f515f02dfe9e3115ed9fc3cde7b18a": {
        "name": "1inch V5",
        "category": "dex",
        "chain": "BASE",
    },
    # --- Bridges ---
    "0x8315177ab297ba92a06054ce80a67ed4dbd7ed3a": {
        "name": "Arbitrum Bridge",
        "category": "bridge",
        "chain": "ETHEREUM",
    },
    "0x4dbd4fc535ac27206064b68ffcf827b0a60bab3f": {
        "name": "Arbitrum Inbox",
        "category": "bridge",
        "chain": "ETHEREUM",
    },
    "0x99c9fc46f92e8a1c0dec1b1747d010903e884be1": {
        "name": "Optimism Bridge",
        "category": "bridge",
        "chain": "ETHEREUM",
    },
    "0xbeba340eb3516928b66e3f9a28a1f23b86e6a2dc": {
        "name": "Base Bridge",
        "category": "bridge",
        "chain": "ETHEREUM",
    },
    "0x49048044d57e1c92a77f79988d21fa8faf74e97e": {
        "name": "Base Portal",
        "category": "bridge",
        "chain": "ETHEREUM",
    },
    "0x3154cf16ccdb4c6d922629664174b904d80f2c35": {
        "name": "Base Bridge L2",
        "category": "bridge",
        "chain": "BASE",
    },
    "0x4200000000000000000000000000000000000010": {
        "name": "Optimism Standard Bridge",
        "category": "bridge",
        "chain": "BASE",
    },
    # --- Staking ---
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": {
        "name": "Lido stETH",
        "category": "staking",
        "chain": "ETHEREUM",
    },
    "0x00000000219ab540356cbb839cbe05303d7705fa": {
        "name": "ETH2 Deposit Contract",
        "category": "staking",
        "chain": "ETHEREUM",
    },
    "0xdd3f50f8a6cafbe9b31a427582963f465e745af8": {
        "name": "Frax Staking",
        "category": "staking",
        "chain": "ETHEREUM",
    },
    # --- NFT / Marketplace ---
    "0x00000000006c3852cbef3e08e8df289169ede581": {
        "name": "OpenSea Seaport 1.1",
        "category": "nft",
        "chain": "ETHEREUM",
    },
    "0x0000000000000068f116a894984e2db1123eb395": {
        "name": "OpenSea Seaport 1.6",
        "category": "nft",
        "chain": "ETHEREUM",
    },
}

# (compiled_regex, category) — checked in order; first match wins
CATEGORY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"uniswap|sushiswap|pancake|curve|balancer|1inch|swap.?router|dex|aggregat", re.IGNORECASE), "dex"),
    (re.compile(r"bridge|portal|messenger|gateway|l1standard|l2standard|inbox|outbox|rollup", re.IGNORECASE), "bridge"),
    (re.compile(r"staking|lido|rocket.?pool|vault|yearn|convex|deposit.?contract", re.IGNORECASE), "staking"),
    (re.compile(r"opensea|seaport|blur|nft.?market|raribles", re.IGNORECASE), "nft"),
    (re.compile(r"wrapped|weth|wbtc|unwrap", re.IGNORECASE), "dex"),
]


def lookup_by_address(address: str) -> dict | None:
    """Return the registry entry for a known contract address, or None.

    Comparison is case-insensitive.
    """
    return KNOWN_CONTRACTS.get(address.lower())


def classify_by_name(contract_name: str) -> str:
    """Classify a contract by its name using regex patterns.

    Returns the matched category string, or "external" if nothing matches.
    """
    for pattern, category in CATEGORY_PATTERNS:
        if pattern.search(contract_name):
            return category
    return "external"
