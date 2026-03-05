"""Pytest configuration and fixtures for KryptoSkatt tests."""

import pytest
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def coinbase_csv(fixtures_dir):
    return fixtures_dir / "coinbase_sample.csv"


@pytest.fixture
def crypto_com_csv(fixtures_dir):
    return fixtures_dir / "crypto_com_sample.csv"


@pytest.fixture
def mexc_deposit_tsv(fixtures_dir):
    return fixtures_dir / "mexc_deposit_sample.tsv"


@pytest.fixture
def mexc_withdrawal_tsv(fixtures_dir):
    return fixtures_dir / "mexc_withdrawal_sample.tsv"


@pytest.fixture
def sample_buy_eth():
    """Sample BUY transaction for ETH."""
    from kryptoskatt.schemas import TransactionCreate

    return TransactionCreate(
        source_platform="coinbase",
        timestamp_utc=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        event_type="BUY",
        base_coin="ETH",
        base_amount=Decimal("0.5"),
        quote_coin="SEK",
        quote_amount=Decimal("15000.00"),
        fee_coin="SEK",
        fee_amount=Decimal("150.00"),
    )


@pytest.fixture
def sample_sell_eth():
    """Sample SELL transaction for ETH."""
    from kryptoskatt.schemas import TransactionCreate

    return TransactionCreate(
        source_platform="coinbase",
        timestamp_utc=datetime(2024, 6, 15, 14, 0, 0, tzinfo=timezone.utc),
        event_type="SELL",
        base_coin="ETH",
        base_amount=Decimal("-0.25"),
        quote_coin="SEK",
        quote_amount=Decimal("10000.00"),
    )


@pytest.fixture
def sample_swap_btc_to_eth():
    """Sample SWAP: BTC out, ETH in (two transactions)."""
    from kryptoskatt.schemas import TransactionCreate

    swap_out = TransactionCreate(
        source_platform="coinbase",
        timestamp_utc=datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        event_type="SWAP_OUT",
        base_coin="BTC",
        base_amount=Decimal("-0.01"),
        quote_coin="ETH",
        quote_amount=Decimal("0.15"),
    )
    swap_in = TransactionCreate(
        source_platform="coinbase",
        timestamp_utc=datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        event_type="SWAP_IN",
        base_coin="ETH",
        base_amount=Decimal("0.15"),
        quote_coin="BTC",
        quote_amount=Decimal("0.01"),
    )
    return swap_out, swap_in


@pytest.fixture
def sample_transfer_in():
    """Sample TRANSFER_IN (received from external)."""
    from kryptoskatt.schemas import TransactionCreate

    return TransactionCreate(
        source_platform="coinbase",
        timestamp_utc=datetime(2024, 2, 10, 8, 0, 0, tzinfo=timezone.utc),
        event_type="TRANSFER_IN",
        base_coin="SOL",
        base_amount=Decimal("1.5"),
        from_address="5LWTG...eDgHg",
        to_address="5FhSP...MAVXk",
    )


@pytest.fixture
def sample_reward_geod():
    """Sample REWARD (DePIN mining reward)."""
    from kryptoskatt.schemas import TransactionCreate

    return TransactionCreate(
        source_platform="on_chain",
        timestamp_utc=datetime(2024, 4, 5, 0, 0, 0, tzinfo=timezone.utc),
        event_type="REWARD",
        base_coin="GEOD",
        base_amount=Decimal("12.0"),
        from_address="FceP6wv...9GfMDsp",
    )


@pytest.fixture
def sample_eth_wallet():
    from kryptoskatt.schemas import WalletCreate

    return WalletCreate(
        address="0x85fB22b3C15C7C2c93F26E83F446950D9408ba67",
        chain="ETHEREUM",
        label="Main ETH Wallet",
        is_mine=True,
    )


@pytest.fixture
def sample_sol_wallet():
    from kryptoskatt.schemas import WalletCreate

    return WalletCreate(
        address="CAGfWWXbwW3NkbkHFxbhXn1RU7kywHTDaSipsRKeLhR8",
        chain="SOLANA",
        label="Main SOL Wallet",
        is_mine=True,
    )


@pytest.fixture
def anyio_backend():
    """Use asyncio as the async backend for pytest-asyncio."""
    return "asyncio"
