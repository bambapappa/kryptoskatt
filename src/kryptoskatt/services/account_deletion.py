"""Complete erasure of an account and everything linked to it (GDPR art. 17).

Single implementation shared by the web UI and the REST API so the two can
never drift apart. Every table holding per-account data must be listed here;
``tests/test_account_deletion.py`` fails if a model with a user/account column
is missing.
"""

from typing import Any

from sqlalchemy.orm import Session

from kryptoskatt.models.account import Account
from kryptoskatt.models.account_api_key import AccountApiKey
from kryptoskatt.models.coin_blacklist import CoinBlacklist
from kryptoskatt.models.custom_chain_config import CustomChainConfig
from kryptoskatt.models.disposal import Disposal
from kryptoskatt.models.gav_ledger import GavLedger
from kryptoskatt.models.manual_price import ManualPrice
from kryptoskatt.models.share_link import ShareLink
from kryptoskatt.models.t2_manual_entry import T2ManualEntry
from kryptoskatt.models.t2_manual_income_entry import T2ManualIncomeEntry
from kryptoskatt.models.transaction import ImportBatch, Transaction
from kryptoskatt.models.transfer_link import TransferLink
from kryptoskatt.models.user_session import UserSession
from kryptoskatt.models.wallet import Wallet

# (model, owner column name) — deleted in this order.
OWNED_TABLES: tuple[tuple[Any, str], ...] = (
    (Transaction, "user_id"),
    (ImportBatch, "user_id"),
    (Wallet, "user_id"),
    (Disposal, "user_id"),
    (GavLedger, "user_id"),
    (T2ManualEntry, "user_id"),
    (T2ManualIncomeEntry, "user_id"),
    (CoinBlacklist, "user_id"),
    (ManualPrice, "user_id"),
    (CustomChainConfig, "account_id"),
    (AccountApiKey, "account_id"),
    (ShareLink, "account_id"),
    (UserSession, "account_id"),
)


def delete_account_data(db: Session, account_db_id: int) -> None:
    """Delete the account and all of its data in one transaction."""
    tx_ids = db.query(Transaction.id).filter(Transaction.user_id == account_db_id)
    db.query(TransferLink).filter(
        TransferLink.tx_out_id.in_(tx_ids) | TransferLink.tx_in_id.in_(tx_ids)
    ).delete(synchronize_session=False)
    for model, column in OWNED_TABLES:
        db.query(model).filter(getattr(model, column) == account_db_id).delete(
            synchronize_session=False
        )
    db.query(Account).filter(Account.id == account_db_id).delete(synchronize_session=False)
    db.commit()


# Columns never included in an export: credentials and internal hashes.
_EXPORT_EXCLUDED_TABLES = {"user_sessions", "account_api_keys"}
_EXPORT_EXCLUDED_COLUMNS = {"token_hash", "session_token", "api_key"}


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)


def _row_dict(row: object) -> dict:
    from sqlalchemy import inspect

    return {
        attr.columns[0].name: _jsonable(getattr(row, attr.key))
        for attr in inspect(type(row)).column_attrs  # type: ignore[union-attr]
        if attr.columns[0].name not in _EXPORT_EXCLUDED_COLUMNS
    }


def export_account_data(db: Session, account: Account) -> dict:
    """All personal data held about the account (GDPR art. 15 and 20), as JSON-ready dict."""
    from datetime import UTC, datetime

    data: dict = {
        "exported_at": datetime.now(UTC).isoformat(),
        "account_id": account.account_id,
        "created_at": str(account.created_at),
    }
    for model, column in OWNED_TABLES:
        table = model.__table__
        if table.name in _EXPORT_EXCLUDED_TABLES:
            continue
        rows = db.query(model).filter(getattr(model, column) == account.id).all()
        data[table.name] = [_row_dict(row) for row in rows]
    own_tx = db.query(Transaction.id).filter(Transaction.user_id == account.id)
    data["transfer_links"] = [
        _row_dict(link)
        for link in db.query(TransferLink).filter(TransferLink.tx_out_id.in_(own_tx)).all()
    ]
    return data
