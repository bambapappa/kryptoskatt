"""Tests for wallet service and CLI."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kryptoskatt.models.base import Base
from kryptoskatt.models.wallet import Wallet
from kryptoskatt.schemas import WalletCreate
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
    """WalletService instance with test session."""
    return WalletService(db_session, 1)


class TestWalletService:
    """Tests for WalletService."""

    def test_add_wallet(self, wallet_service, db_session):
        """Test adding a wallet."""
        data = WalletCreate(
            address="0x85fB22b3C15C7C2c93F26E83F446950D9408ba67",
            chain="ETHEREUM",
            label="Main ETH Wallet",
            is_mine=True,
        )
        wallet = wallet_service.add_wallet(data)

        assert wallet.id is not None
        assert wallet.address == data.address
        assert wallet.chain == "ETHEREUM"
        assert wallet.label == data.label
        assert wallet.is_mine is True

        # Verify in DB
        db_wallet = db_session.query(Wallet).filter_by(id=wallet.id).first()
        assert db_wallet is not None

    def test_add_duplicate_wallet_raises(self, wallet_service):
        """Test that adding duplicate address+chain raises ValueError."""
        data = WalletCreate(
            address="0x85fB22b3C15C7C2c93F26E83F446950D9408ba67",
            chain="ETHEREUM",
            label="Main ETH Wallet",
            is_mine=True,
        )
        wallet_service.add_wallet(data)

        # Try adding same wallet again
        with pytest.raises(ValueError, match="already exists"):
            wallet_service.add_wallet(data)

    def test_list_wallets(self, wallet_service):
        """Test listing all wallets."""
        # Add two wallets
        wallet_service.add_wallet(
            WalletCreate(address="0xAAA", chain="ETHEREUM", label="ETH1", is_mine=True)
        )
        wallet_service.add_wallet(
            WalletCreate(address="0xBBB", chain="SOLANA", label="SOL1", is_mine=True)
        )

        wallets = wallet_service.list_wallets()
        assert len(wallets) == 2

    def test_list_wallets_filter_chain(self, wallet_service):
        """Test filtering wallets by chain."""
        wallet_service.add_wallet(
            WalletCreate(address="0xAAA", chain="ETHEREUM", label="ETH", is_mine=True)
        )
        wallet_service.add_wallet(
            WalletCreate(address="BBB", chain="SOLANA", label="SOL", is_mine=True)
        )

        eth_wallets = wallet_service.list_wallets(chain="ethereum")
        assert len(eth_wallets) == 1
        assert eth_wallets[0].chain == "ETHEREUM"

        sol_wallets = wallet_service.list_wallets(chain="solana")
        assert len(sol_wallets) == 1
        assert sol_wallets[0].chain == "SOLANA"

    def test_list_wallets_mine_only(self, wallet_service):
        """Test filtering wallets by mine_only."""
        wallet_service.add_wallet(
            WalletCreate(address="0xAAA", chain="ETHEREUM", label="My ETH", is_mine=True)
        )
        wallet_service.add_wallet(
            WalletCreate(address="0xBBB", chain="ETHEREUM", label="Watch ETH", is_mine=False)
        )

        all_wallets = wallet_service.list_wallets()
        assert len(all_wallets) == 2

        mine_only = wallet_service.list_wallets(mine_only=True)
        assert len(mine_only) == 1
        assert mine_only[0].is_mine is True

    def test_remove_wallet(self, wallet_service, db_session):
        """Test removing a wallet."""
        wallet = wallet_service.add_wallet(
            WalletCreate(address="0xAAA", chain="ETHEREUM", label="To Remove", is_mine=True)
        )
        wallet_id = wallet.id

        removed = wallet_service.remove_wallet("0xAAA")
        assert removed is True

        # Verify removed from DB
        db_wallet = db_session.query(Wallet).filter_by(id=wallet_id).first()
        assert db_wallet is None

    def test_remove_nonexistent_returns_false(self, wallet_service):
        """Test removing non-existent wallet returns False."""
        result = wallet_service.remove_wallet("0xNONEXISTENT")
        assert result is False

    def test_unknown_chain_is_accepted(self, wallet_service):
        """Unknown chain strings are stored; validation is deferred to fetch time."""
        data = WalletCreate(
            address="0xAAA",
            chain="CUSTOMCHAIN",
            label="Custom Chain Wallet",
            is_mine=True,
        )
        wallet = wallet_service.add_wallet(data)
        assert wallet.chain == "CUSTOMCHAIN"

    def test_empty_chain_raises(self, wallet_service):
        """Empty chain string raises ValueError."""
        data = WalletCreate(
            address="0xAAA",
            chain="",
            label="Bad Chain",
            is_mine=True,
        )
        with pytest.raises(ValueError, match="Chain cannot be empty"):
            wallet_service.add_wallet(data)

    def test_get_my_addresses(self, wallet_service):
        """Test getting all my addresses."""
        wallet_service.add_wallet(
            WalletCreate(address="0xAAA", chain="ETHEREUM", label="My ETH", is_mine=True)
        )
        wallet_service.add_wallet(
            WalletCreate(address="0xBBB", chain="ETHEREUM", label="Watch ETH", is_mine=False)
        )
        wallet_service.add_wallet(
            WalletCreate(address="CCC", chain="SOLANA", label="My SOL", is_mine=True)
        )

        my_addresses = wallet_service.get_my_addresses()
        assert len(my_addresses) == 2
        assert ("0xAAA", "ETHEREUM") in my_addresses
        assert ("CCC", "SOLANA") in my_addresses
        assert ("0xBBB", "ETHEREUM") not in my_addresses


class TestWalletCLI:
    """Tests for wallet CLI commands (basic smoke tests)."""

    def test_add_command_import(self):
        """Test that wallet CLI can be imported."""
        from kryptoskatt.cli.wallet import wallet_app
        assert wallet_app is not None

    def test_add_command_registered(self):
        """Test that add command is registered."""
        from typer.testing import CliRunner

        from kryptoskatt.cli.wallet import wallet_app

        runner = CliRunner()
        result = runner.invoke(wallet_app, ["--help"])
        assert result.exit_code == 0
        assert "add" in result.output
        assert "list" in result.output
        assert "remove" in result.output
