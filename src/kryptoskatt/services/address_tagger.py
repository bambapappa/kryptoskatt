"""Auto-tagger for unknown blockchain addresses."""

import logging
import time

import httpx
from sqlalchemy.orm import Session

from kryptoskatt.models.wallet import Wallet
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.contract_registry import classify_by_name, lookup_by_address
from kryptoskatt.services.wallet import WalletService

logger = logging.getLogger(__name__)

# Etherscan v2 base URL (chain-agnostic, uses chainid param)
_ETHERSCAN_BASE_URL = "https://api.etherscan.io/v2/api"

# EVM chain → Etherscan chain ID
_CHAIN_IDS: dict[str, int] = {
    "ETHEREUM": 1,
    "POLYGON": 137,
    "BNB": 56,
    "BASE": 8453,
    "ARBITRUM": 42161,
}

# Seconds between Etherscan API calls to respect rate limits
_ETHERSCAN_RATE_LIMIT_SLEEP = 0.25


class AddressTagger:
    """Resolve and register unknown addresses using a contract registry and Etherscan."""

    def __init__(self, session: Session, etherscan_api_key: str = ""):
        self.session = session
        self.etherscan_api_key = etherscan_api_key
        self.wallet_service = WalletService(session)

    def auto_tag_unknown(self, addresses: list[str], chain: str = "ETHEREUM") -> dict:
        """Tag unknown addresses using registry lookup and optional Etherscan queries.

        For each address not already registered as a wallet:
          1. Check KNOWN_CONTRACTS registry
          2. If EVM chain and Etherscan key available: call Etherscan getsourcecode API
          3. Classify by contract name pattern
          4. Register with is_mine=False and detected category

        Returns a summary dict: {"tagged": int, "skipped": int, "results": list}.
        """
        chain_upper = chain.upper()

        # Collect all currently registered addresses (any chain) to skip known ones
        known: set[str] = {w.address for w in self.session.query(Wallet).all()}

        use_etherscan = bool(self.etherscan_api_key) and chain_upper in _CHAIN_IDS
        tagged = 0
        skipped = 0
        results: list[dict] = []

        for address in addresses:
            if not address:
                skipped += 1
                continue

            if address in known:
                skipped += 1
                continue

            # 1. Try static registry
            entry = lookup_by_address(address)
            if entry:
                name = entry["name"]
                category = entry["category"]
                logger.info("Registry hit for %s → %s (%s)", address, name, category)
            elif use_etherscan:
                # 2. Etherscan live lookup
                etherscan_result = self._etherscan_lookup(address, chain_upper)
                time.sleep(_ETHERSCAN_RATE_LIMIT_SLEEP)
                if etherscan_result and etherscan_result.get("is_contract"):
                    contract_name = etherscan_result.get("name", "")
                    category = classify_by_name(contract_name) if contract_name else "external"
                    name = contract_name or ""
                    logger.info(
                        "Etherscan hit for %s → name=%r category=%s",
                        address,
                        name,
                        category,
                    )
                else:
                    # EOA or lookup failure — skip
                    skipped += 1
                    continue
            else:
                skipped += 1
                continue

            # 3. Register the address
            try:
                self.wallet_service.add_wallet(
                    WalletCreate(
                        address=address,
                        chain=chain_upper,
                        label=name,
                        is_mine=False,
                        category=category,
                    )
                )
                tagged += 1
                known.add(address)
                results.append({"address": address, "name": name, "category": category})
            except ValueError:
                # Already registered between query and insert — ignore
                skipped += 1

        return {"tagged": tagged, "skipped": skipped, "results": results}

    def _etherscan_lookup(self, address: str, chain: str) -> dict | None:
        """Call Etherscan v2 getsourcecode for an address.

        Returns {"name": str, "is_contract": bool} or None on network/API error.
        Returns {"name": "", "is_contract": True} for unverified contracts.
        Returns None for EOAs (externally owned accounts).
        """
        chain_id = _CHAIN_IDS.get(chain)
        if chain_id is None:
            return None

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    _ETHERSCAN_BASE_URL,
                    params={
                        "chainid": chain_id,
                        "module": "contract",
                        "action": "getsourcecode",
                        "address": address,
                        "apikey": self.etherscan_api_key,
                    },
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            logger.warning("Etherscan lookup failed for %s", address, exc_info=True)
            return None

        if data.get("status") != "1":
            return None

        result_list = data.get("result")
        if not result_list or not isinstance(result_list, list):
            return None

        item = result_list[0]
        contract_name: str = item.get("ContractName", "") or ""
        abi: str = item.get("ABI", "") or ""

        # ABI == "Contract source code not verified" indicates a deployed contract
        # whose source is not verified — it is still a contract, just unverified.
        # An EOA returns an empty ABI or a specific error string.
        is_unverified_contract = "not verified" in abi.lower()

        if contract_name:
            return {"name": contract_name, "is_contract": True}
        elif is_unverified_contract:
            return {"name": "", "is_contract": True}
        else:
            # Likely an EOA
            return None
