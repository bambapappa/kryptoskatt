"""scope coin_blacklist to a user (multi-tenant isolation)

Adds a user_id column to coin_blacklist so each account has its own blacklist,
and replaces the global unique(coin_symbol) constraint with a per-user
unique(user_id, coin_symbol). Pre-existing global rows are assigned to the
legacy single-user account when it exists.

Revision ID: 013_coin_blacklist_user_id
Revises: 012_t2_manual_income_entries
Create Date: 2026-06-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision = "013_coin_blacklist_user_id"
down_revision: Union[str, None] = "012_t2_manual_income_entries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_ACCOUNT_ID = "legacy-single-user-0000"


def upgrade() -> None:
    op.add_column("coin_blacklist", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index("ix_coin_blacklist_user_id", "coin_blacklist", ["user_id"])
    op.create_foreign_key(
        "fk_coin_blacklist_user_id",
        "coin_blacklist",
        "accounts",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Backfill pre-existing global rows to the legacy single-user account when present,
    # so existing single-user installs keep their blacklist behaviour.
    op.execute(
        "UPDATE coin_blacklist SET user_id = "
        f"(SELECT id FROM accounts WHERE account_id = '{LEGACY_ACCOUNT_ID}') "
        "WHERE user_id IS NULL "
        f"AND EXISTS (SELECT 1 FROM accounts WHERE account_id = '{LEGACY_ACCOUNT_ID}')"
    )

    # Drop the old global uniqueness on coin_symbol; enforce per-user uniqueness instead.
    op.execute("ALTER TABLE coin_blacklist DROP CONSTRAINT IF EXISTS coin_blacklist_coin_symbol_key")
    op.create_unique_constraint(
        "uq_coin_blacklist_user_symbol", "coin_blacklist", ["user_id", "coin_symbol"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_coin_blacklist_user_symbol", "coin_blacklist", type_="unique")
    op.drop_constraint("fk_coin_blacklist_user_id", "coin_blacklist", type_="foreignkey")
    op.drop_index("ix_coin_blacklist_user_id", table_name="coin_blacklist")
    op.drop_column("coin_blacklist", "user_id")
    op.create_unique_constraint(
        "coin_blacklist_coin_symbol_key", "coin_blacklist", ["coin_symbol"]
    )
