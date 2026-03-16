"""Wallet service for managing tracked cryptocurrency wallets."""

from sqlalchemy.orm import Session

from kryptoskatt.models.wallet import Wallet
from kryptoskatt.schemas import WalletCreate
from kryptoskatt.services.address_validator import validate_address


def _null_wallet_id_in_transactions(session: Session, wallet_id: int) -> None:
    """Set wallet_id=NULL on all transactions referencing this wallet before deletion."""
    from kryptoskatt.models.transaction import Transaction
    session.query(Transaction).filter(Transaction.wallet_id == wallet_id).update(
        {Transaction.wallet_id: None}, synchronize_session=False
    )

# EVM chains that share the same address format (same private key → same address).
# Registering the same address on multiple of these causes cross-chain contamination
# where the same tx_hash ends up stored as both ETH and POL (or BNB etc.) transactions.
EVM_CHAINS: frozenset[str] = frozenset({"ETHEREUM", "POLYGON", "BNB", "BASE", "ARBITRUM"})


class WalletService:
    """Service for managing tracked cryptocurrency wallets."""

    def __init__(self, session: Session, user_id: int):
        """Initialize with a database session and user_id.

        Args:
            session: SQLAlchemy session for database operations.
            user_id: Account DB id to scope all queries and mutations to.
        """
        self.session = session
        self.user_id = user_id

    def add_wallet(self, data: WalletCreate, strict_validation: bool = True) -> Wallet:
        """Add a new wallet.

        Args:
            data: WalletCreate schema with wallet details.
            strict_validation: If True, reject addresses that fail format checks for
                known chains. Set to False for lenient onboarding flows.

        Returns:
            The created Wallet instance.

        Raises:
            ValueError: If chain is invalid, address format is wrong (strict mode),
                or wallet already exists.
        """
        # Accept any non-empty chain string — unknown chains are stored but skipped
        # in fetch until the user adds a custom chain config.
        chain_upper = data.chain.upper()
        if not chain_upper:
            raise ValueError("Chain cannot be empty")

        # EVM addresses are case-insensitive hex — lowercase for consistent storage.
        # Non-EVM chains (Solana, TRON, XRP, Bitcoin, Kadena…) are base58/bech32
        # and case-sensitive, so preserve the original casing.
        if chain_upper in EVM_CHAINS:
            address_norm = data.address.strip().lower()
        else:
            address_norm = data.address.strip()

        if strict_validation:
            is_valid, reason = validate_address(address_norm, chain_upper)
            if not is_valid:
                raise ValueError(f"Invalid address for chain {chain_upper}: {reason}")

        # Check for duplicate (address + chain + user)
        existing = (
            self.session.query(Wallet)
            .filter(
                Wallet.user_id == self.user_id,
                Wallet.address == address_norm,
                Wallet.chain == chain_upper,
            )
            .first()
        )

        if existing:
            raise ValueError(
                f"Wallet with address '{address_norm}' on chain '{chain_upper}' already exists."
            )

        # Create wallet
        wallet = Wallet(
            user_id=self.user_id,
            address=address_norm,
            chain=chain_upper,
            label=data.label,
            is_mine=data.is_mine,
            category=data.category,
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
        query = self.session.query(Wallet).filter(Wallet.user_id == self.user_id)

        if chain:
            query = query.filter(Wallet.chain == chain.upper())

        if mine_only:
            query = query.filter(Wallet.is_mine == True)  # noqa: E712

        return query.order_by(Wallet.created_at.desc()).all()

    def remove_wallet(self, address: str, chain: str | None = None) -> bool:
        """Remove a wallet by address.

        Args:
            address: Wallet address to remove.
            chain: Optional chain to narrow down removal.

        Returns:
            True if wallet was removed, False if not found.
        """
        query = self.session.query(Wallet).filter(
            Wallet.user_id == self.user_id,
            Wallet.address == address,
        )

        if chain:
            query = query.filter(Wallet.chain == chain.upper())

        wallet = query.first()

        if wallet:
            _null_wallet_id_in_transactions(self.session, wallet.id)
            self.session.delete(wallet)
            self.session.commit()
            return True

        return False

    def get_my_addresses(self) -> set[tuple[str, str]]:
        """Get all addresses where is_mine=True.

        Returns:
            Set of (address, chain) tuples for wallets marked as mine.
        """
        wallets = (
            self.session.query(Wallet)
            .filter(Wallet.user_id == self.user_id, Wallet.is_mine == True)  # noqa: E712
            .all()
        )
        return {(w.address, w.chain) for w in wallets}
