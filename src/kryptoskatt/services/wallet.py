"""Wallet service for managing tracked cryptocurrency wallets."""

from sqlalchemy.orm import Session
from kryptoskatt.models.wallet import Wallet
from kryptoskatt.enums import Chain
from kryptoskatt.schemas import WalletCreate


class WalletService:
    """Service for managing tracked cryptocurrency wallets."""

    def __init__(self, session: Session):
        """Initialize with a database session.

        Args:
            session: SQLAlchemy session for database operations.
        """
        self.session = session

    def add_wallet(self, data: WalletCreate) -> Wallet:
        """Add a new wallet.

        Args:
            data: WalletCreate schema with wallet details.

        Returns:
            The created Wallet instance.

        Raises:
            ValueError: If chain is invalid or wallet already exists.
        """
        # Validate chain
        chain_upper = data.chain.upper()
        try:
            Chain(chain_upper)
        except ValueError:
            valid_chains = ", ".join(c.value for c in Chain)
            raise ValueError(f"Unknown chain: {data.chain}. Valid: {valid_chains}")

        # Check for duplicate (address + chain)
        existing = (
            self.session.query(Wallet)
            .filter(Wallet.address == data.address, Wallet.chain == chain_upper)
            .first()
        )

        if existing:
            raise ValueError(
                f"Wallet with address '{data.address}' on chain '{chain_upper}' already exists."
            )

        # Create wallet
        wallet = Wallet(
            address=data.address,
            chain=chain_upper,
            label=data.label,
            is_mine=data.is_mine,
        )
        self.session.add(wallet)
        self.session.commit()
        self.session.refresh(wallet)
        return wallet

    def list_wallets(self, chain: str | None = None, mine_only: bool = False) -> list[Wallet]:
        """List wallets with optional filtering.

        Args:
            chain: Filter by chain (case-insensitive).
            mine_only: If True, only return wallets where is_mine=True.

        Returns:
            List of Wallet instances matching the filters.
        """
        query = self.session.query(Wallet)

        if chain:
            query = query.filter(Wallet.chain == chain.upper())

        if mine_only:
            query = query.filter(Wallet.is_mine == True)

        return query.order_by(Wallet.created_at.desc()).all()

    def remove_wallet(self, address: str, chain: str | None = None) -> bool:
        """Remove a wallet by address.

        Args:
            address: Wallet address to remove.
            chain: Optional chain to narrow down removal.

        Returns:
            True if wallet was removed, False if not found.
        """
        query = self.session.query(Wallet).filter(Wallet.address == address)

        if chain:
            query = query.filter(Wallet.chain == chain.upper())

        wallet = query.first()

        if wallet:
            self.session.delete(wallet)
            self.session.commit()
            return True

        return False

    def get_my_addresses(self) -> set[tuple[str, str]]:
        """Get all addresses where is_mine=True.

        Returns:
            Set of (address, chain) tuples for wallets marked as mine.
        """
        wallets = self.session.query(Wallet).filter(Wallet.is_mine == True).all()
        return {(w.address, w.chain) for w in wallets}
