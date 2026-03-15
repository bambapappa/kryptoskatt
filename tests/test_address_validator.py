"""Tests for address format validation."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kryptoskatt.models.base import Base
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.address_validator import validate_address
from kryptoskatt.services.wallet import WalletService


@pytest.fixture
def db_session():
    """In-memory SQLite session for testing."""
    from tests.conftest import make_test_account

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    make_test_account(session)
    yield session
    session.close()


@pytest.fixture
def wallet_service(db_session):
    return WalletService(db_session, 1)


# --- validate_address unit tests ---


def test_valid_ethereum_address():
    valid, reason = validate_address("0xAbCdEf1234567890AbCdEf1234567890AbCdEf12", "ETHEREUM")
    assert valid is True
    assert reason == ""


def test_invalid_ethereum_address_too_short():
    valid, reason = validate_address("0xABCDEF", "ETHEREUM")
    assert valid is False
    assert "40 hex" in reason


def test_invalid_ethereum_address_no_prefix():
    valid, reason = validate_address("AbCdEf1234567890AbCdEf1234567890AbCdEf12", "ETHEREUM")
    assert valid is False


def test_valid_polygon_uses_eth_format():
    valid, _ = validate_address("0x1234567890abcdef1234567890abcdef12345678", "POLYGON")
    assert valid is True


def test_valid_bitcoin_legacy():
    # A well-known legacy address format (1...)
    valid, reason = validate_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf Na", "BITCOIN")
    # Contains spaces so should fail
    assert valid is False

    valid, reason = validate_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "BITCOIN")
    assert valid is True
    assert reason == ""


def test_valid_bitcoin_p2sh():
    valid, reason = validate_address("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "BITCOIN")
    assert valid is True
    assert reason == ""


def test_valid_bitcoin_bech32():
    valid, reason = validate_address("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "BITCOIN")
    assert valid is True
    assert reason == ""


def test_invalid_bitcoin_address():
    valid, reason = validate_address("notabitcoinaddress", "BITCOIN")
    assert valid is False
    assert "Bitcoin" in reason


def test_valid_solana_address():
    # 44-char base58
    valid, reason = validate_address("9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin", "SOLANA")
    assert valid is True
    assert reason == ""


def test_invalid_solana_address_too_short():
    valid, reason = validate_address("abc123", "SOLANA")
    assert valid is False


def test_valid_tron_address():
    valid, reason = validate_address("TRWBqiqoFZysoAeyR1J35ibuyc8EvhUAoY", "TRON")
    assert valid is True
    assert reason == ""


def test_invalid_tron_address_wrong_prefix():
    valid, reason = validate_address("ERWBqiqoFZysoAeyR1J35ibuyc8EvhUAoY", "TRON")
    assert valid is False


def test_valid_ripple_address():
    valid, reason = validate_address("rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh", "RIPPLE")
    assert valid is True
    assert reason == ""


def test_valid_kadena_k_prefix():
    valid, reason = validate_address("k:abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890", "KADENA")
    assert valid is True
    assert reason == ""


def test_valid_kadena_w_prefix():
    valid, reason = validate_address("w:abcdef1234", "KADENA")
    assert valid is True


def test_invalid_kadena_address():
    valid, reason = validate_address("abcdef1234", "KADENA")
    assert valid is False


def test_unknown_chain_accepts_anything():
    valid, reason = validate_address("any-random-string-here", "MYCHAIN")
    assert valid is True
    assert reason == ""


def test_unknown_chain_empty_string():
    # Even an empty address is "allowed" for unknown chains (chain guard is at service level)
    valid, reason = validate_address("", "MYCHAIN")
    assert valid is True


# --- WalletService integration tests ---


def test_wallet_service_rejects_invalid_address(wallet_service):
    """WalletService should raise ValueError for a bad Ethereum address in strict mode."""
    data = WalletCreate(
        address="not-an-eth-address",
        chain="ETHEREUM",
        label="Test",
        is_mine=True,
    )
    with pytest.raises(ValueError, match="Invalid address for chain ETHEREUM"):
        wallet_service.add_wallet(data, strict_validation=True)


def test_wallet_service_accepts_invalid_address_when_lenient(wallet_service):
    """WalletService should succeed for a bad address when strict_validation=False."""
    data = WalletCreate(
        address="not-an-eth-address",
        chain="ETHEREUM",
        label="Lenient import",
        is_mine=False,
    )
    wallet = wallet_service.add_wallet(data, strict_validation=False)
    assert wallet.id is not None


def test_wallet_service_accepts_valid_eth_address(wallet_service):
    data = WalletCreate(
        address="0xAbCdEf1234567890AbCdEf1234567890AbCdEf12",
        chain="ETHEREUM",
        label="Valid",
        is_mine=True,
    )
    wallet = wallet_service.add_wallet(data)
    assert wallet.chain == "ETHEREUM"


def test_wallet_service_unknown_chain_always_accepted(wallet_service):
    """Unknown chains bypass address format checks even in strict mode."""
    data = WalletCreate(
        address="any-format-accepted",
        chain="MYCHAIN",
        label="Custom chain",
        is_mine=False,
    )
    wallet = wallet_service.add_wallet(data, strict_validation=True)
    assert wallet.id is not None
