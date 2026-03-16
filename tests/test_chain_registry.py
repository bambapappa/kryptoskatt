"""Tests for chain registry and adapter system."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from kryptoskatt.chains import ChainAdapter, ChainRegistry, get_registry
from kryptoskatt.enums import Chain
from kryptoskatt.schemas import TransactionCreate


class MockAdapter(ChainAdapter):
    """Mock adapter for testing."""

    def supported_chains(self) -> list[Chain]:
        return [Chain.ETHEREUM, Chain.POLYGON]

    def fetch_transactions(self, address: str, chain: Chain) -> list[TransactionCreate]:
        return [
            TransactionCreate(
                source_platform="MOCK",
                timestamp_utc=datetime(2024, 1, 1, tzinfo=UTC),
                event_type="TRANSFER_IN",
                base_coin="ETH",
                base_amount=Decimal("1.0"),
            )
        ]


@dataclass
class MockWallet:
    """Mock wallet for testing."""

    address: str
    chain: Chain


class TestChainAdapterAbstract:
    """Tests for ChainAdapter ABC."""

    def test_chain_adapter_is_abstract(self):
        """Cannot instantiate ChainAdapter directly."""
        with pytest.raises(TypeError):
            ChainAdapter()

    def test_concrete_adapter_can_be_created(self):
        """A minimal concrete subclass works."""
        adapter = MockAdapter()
        assert adapter.supported_chains() == [Chain.ETHEREUM, Chain.POLYGON]

    def test_rate_limit_delay_default(self):
        """Default rate_limit_delay is 0.2."""
        adapter = MockAdapter()
        assert adapter.rate_limit_delay() == 0.2


class TestChainRegistry:
    """Tests for ChainRegistry."""

    def test_registry_register_and_get(self):
        """Register a mock adapter, get_adapter returns it for its chains."""
        registry = ChainRegistry()
        adapter = MockAdapter()
        registry.register(adapter)

        assert registry.get_adapter(Chain.ETHEREUM) is adapter
        assert registry.get_adapter(Chain.POLYGON) is adapter

    def test_registry_get_unsupported_returns_none(self):
        """get_adapter(Chain.KADENA) returns None when not registered."""
        registry = ChainRegistry()
        assert registry.get_adapter(Chain.KADENA) is None

    def test_registry_unsupported_returns_none(self, caplog):
        """Getting unsupported chain returns None."""
        registry = ChainRegistry()
        result = registry.get_adapter(Chain.KADENA)

        assert result is None

    def test_registry_supported_chains(self):
        """After registration, supported_chains() returns correct list."""
        registry = ChainRegistry()
        adapter = MockAdapter()
        registry.register(adapter)

        chains = registry.supported_chains()
        assert Chain.ETHEREUM in chains
        assert Chain.POLYGON in chains
        assert len(chains) == 2

    def test_fetch_all_dispatches_correctly(self):
        """fetch_all with wallets dispatches to right adapter."""
        registry = ChainRegistry()
        adapter = MockAdapter()
        registry.register(adapter)

        wallets = [
            MockWallet(address="0x123", chain=Chain.ETHEREUM),
            MockWallet(address="0x456", chain=Chain.POLYGON),
        ]

        results = registry.fetch_all(wallets)
        assert len(results) == 2  # 1 tx per wallet

    def test_fetch_all_skips_unsupported(self, caplog):
        """fetch_all skips wallets for unsupported chains with warning."""
        import logging

        registry = ChainRegistry()
        adapter = MockAdapter()
        registry.register(adapter)

        wallets = [
            MockWallet(address="0x123", chain=Chain.ETHEREUM),
            MockWallet(address="0x456", chain=Chain.KADENA),  # Not supported
        ]

        with caplog.at_level(logging.WARNING):
            results = registry.fetch_all(wallets)

        assert len(results) == 1  # Only ETH wallet processed
        assert any("No adapter for chain KADENA" in record.message for record in caplog.records)

    def test_get_registry_has_adapters(self):
        """get_registry() returns registry with all configured chain adapters."""
        from kryptoskatt.config import settings

        registry = get_registry()
        chains = registry.supported_chains()
        assert Chain.ETHEREUM in chains
        assert Chain.POLYGON in chains
        assert Chain.BNB in chains
        assert Chain.BITCOIN in chains
        assert Chain.TRON in chains
        assert Chain.RIPPLE in chains
        assert Chain.VECHAIN in chains
        assert Chain.MXC_ZKEVM in chains
        # Solana only registered when an API key is configured
        if settings.helius_api_key or settings.solscan_api_key:
            assert Chain.SOLANA in chains
