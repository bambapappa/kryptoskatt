"""Address format validation for known blockchain networks."""

import re


def validate_address(address: str, chain: str) -> tuple[bool, str]:
    """Validate address format for known chains.

    Args:
        address: The wallet address to validate.
        chain: The blockchain network name (case-insensitive).

    Returns:
        Tuple of (is_valid, reason). reason is empty string when valid.
    """
    addr = address.strip()
    chain_upper = chain.upper()

    if chain_upper in ("ETHEREUM", "POLYGON", "BNB", "BASE", "ARBITRUM", "MXC_ZKEVM", "ALEO"):
        if re.match(r"^0x[0-9a-fA-F]{40}$", addr):
            return True, ""
        return False, f"Expected 0x + 40 hex chars for {chain_upper}"

    if chain_upper == "BITCOIN":
        # Legacy (1...), P2SH (3...), bech32 (bc1...)
        if re.match(r"^(1|3)[a-km-zA-HJ-NP-Z1-9]{25,34}$", addr) or re.match(
            r"^bc1[a-z0-9]{6,87}$", addr
        ):
            return True, ""
        return False, "Invalid Bitcoin address format"

    if chain_upper == "SOLANA":
        if re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", addr):
            return True, ""
        return False, "Expected base58 (32-44 chars) for Solana"

    if chain_upper == "TRON":
        if addr.startswith("T") and len(addr) == 34:
            return True, ""
        return False, "Expected T + 33 chars for TRON"

    if chain_upper == "RIPPLE":
        if addr.startswith("r") and 25 <= len(addr) <= 35:
            return True, ""
        return False, "Expected r + 24-34 chars for XRP"

    if chain_upper == "KADENA":
        if addr.startswith(("k:", "w:")):
            return True, ""
        return False, "Expected k: or w: prefix for Kadena"

    # Unknown chain — allow any non-empty string
    return True, ""
