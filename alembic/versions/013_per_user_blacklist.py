"""make coin_blacklist per-account

Revision ID: 013_per_user_blacklist
Revises: 012_t2_manual_income_entries
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "013_per_user_blacklist"
down_revision = "012_t2_manual_income_entries"
branch_labels = None
depends_on = None

LEGACY_ACCOUNT_ID = "legacy-single-user-0000"


def upgrade() -> None:
    # 1. Add nullable user_id
    op.add_column("coin_blacklist", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_coin_blacklist_user_id",
        "coin_blacklist",
        "accounts",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 2. Backfill existing (previously global) rows to the legacy account
    op.execute(
        sa.text(
            "UPDATE coin_blacklist SET user_id = "
            f"(SELECT id FROM accounts WHERE account_id = '{LEGACY_ACCOUNT_ID}') "
            "WHERE user_id IS NULL"
        )
    )

    # 3. Enforce NOT NULL
    op.alter_column("coin_blacklist", "user_id", nullable=False)

    # 4. Replace global unique(coin_symbol) with unique(user_id, coin_symbol)
    op.drop_constraint("coin_blacklist_coin_symbol_key", "coin_blacklist", type_="unique")
    op.create_unique_constraint(
        "uq_coin_blacklist_user_coin", "coin_blacklist", ["user_id", "coin_symbol"]
    )
    op.create_index("ix_coin_blacklist_user_id", "coin_blacklist", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_coin_blacklist_user_id", table_name="coin_blacklist")
    op.drop_constraint("uq_coin_blacklist_user_coin", "coin_blacklist", type_="unique")
    # Collapse per-user rows back to one global row per symbol before restoring uniqueness
    op.execute(
        sa.text(
            "DELETE FROM coin_blacklist a USING coin_blacklist b "
            "WHERE a.id > b.id AND a.coin_symbol = b.coin_symbol"
        )
    )
    op.create_unique_constraint(
        "coin_blacklist_coin_symbol_key", "coin_blacklist", ["coin_symbol"]
    )
    op.drop_constraint("fk_coin_blacklist_user_id", "coin_blacklist", type_="foreignkey")
    op.drop_column("coin_blacklist", "user_id")
