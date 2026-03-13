"""add multi-tenant accounts, sessions, custom_chain_configs and user_id on tenant tables

Revision ID: 008_multi_tenant
Revises: 007_t2_manual_entries
Create Date: 2026-03-13
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "008_multi_tenant"
down_revision = "007_t2_manual_entries"
branch_labels = None
depends_on = None

LEGACY_ACCOUNT_ID = "legacy-single-user-0000"


def upgrade() -> None:
    # 1. Create accounts table
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(64), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index("ix_accounts_account_id", "accounts", ["account_id"])

    # 2. Create sessions table
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_token", sa.String(64), unique=True, nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_token", "sessions", ["session_token"])

    # 3. Create custom_chain_configs table
    op.create_table(
        "custom_chain_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chain_name", sa.String(100), nullable=False),
        sa.Column("explorer_url", sa.String(512), nullable=False),
        sa.Column("api_key", sa.String(256), nullable=True),
        sa.Column("adapter_type", sa.String(50), nullable=False),
        sa.Column("native_coin", sa.String(20), nullable=False, server_default=""),
        sa.Column("chain_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_custom_chain_account_id", "custom_chain_configs", ["account_id"])
    op.create_unique_constraint(
        "uq_custom_chain_account_name",
        "custom_chain_configs",
        ["account_id", "chain_name"],
    )

    # 4. Insert legacy single-user account
    now = datetime.now(timezone.utc)
    op.execute(
        sa.text(
            "INSERT INTO accounts (account_id, created_at, last_active_at, is_active) "
            f"VALUES ('{LEGACY_ACCOUNT_ID}', '{now.isoformat()}', '{now.isoformat()}', true)"
        )
    )

    # 5a. Add nullable user_id to wallets
    op.add_column("wallets", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_wallets_user_id", "wallets", "accounts", ["user_id"], ["id"])
    # backfill
    op.execute(
        sa.text(
            "UPDATE wallets SET user_id = (SELECT id FROM accounts WHERE account_id = '"
            + LEGACY_ACCOUNT_ID
            + "')"
        )
    )
    op.alter_column("wallets", "user_id", nullable=False)
    op.create_index("ix_wallets_user_id_chain", "wallets", ["user_id", "chain"])

    # 5b. Add nullable user_id to import_batches
    op.add_column("import_batches", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_import_batches_user_id", "import_batches", "accounts", ["user_id"], ["id"]
    )
    op.execute(
        sa.text(
            "UPDATE import_batches SET user_id = (SELECT id FROM accounts WHERE account_id = '"
            + LEGACY_ACCOUNT_ID
            + "')"
        )
    )
    op.alter_column("import_batches", "user_id", nullable=False)

    # 5c. Add nullable user_id to transactions
    op.add_column("transactions", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_transactions_user_id", "transactions", "accounts", ["user_id"], ["id"]
    )
    op.execute(
        sa.text(
            "UPDATE transactions SET user_id = (SELECT id FROM accounts WHERE account_id = '"
            + LEGACY_ACCOUNT_ID
            + "')"
        )
    )
    op.alter_column("transactions", "user_id", nullable=False)
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])

    # 5d. Add nullable user_id to disposals
    op.add_column("disposals", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_disposals_user_id", "disposals", "accounts", ["user_id"], ["id"]
    )
    op.execute(
        sa.text(
            "UPDATE disposals SET user_id = (SELECT id FROM accounts WHERE account_id = '"
            + LEGACY_ACCOUNT_ID
            + "')"
        )
    )
    op.alter_column("disposals", "user_id", nullable=False)
    op.create_index("ix_disposals_user_year", "disposals", ["user_id", "tax_year"])

    # 5e. Add nullable user_id to gav_ledger
    op.add_column("gav_ledger", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_gav_ledger_user_id", "gav_ledger", "accounts", ["user_id"], ["id"]
    )
    op.execute(
        sa.text(
            "UPDATE gav_ledger SET user_id = (SELECT id FROM accounts WHERE account_id = '"
            + LEGACY_ACCOUNT_ID
            + "')"
        )
    )
    op.alter_column("gav_ledger", "user_id", nullable=False)

    # 5f. Add nullable user_id to t2_manual_entries
    op.add_column("t2_manual_entries", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_t2_manual_entries_user_id", "t2_manual_entries", "accounts", ["user_id"], ["id"]
    )
    op.execute(
        sa.text(
            "UPDATE t2_manual_entries SET user_id = (SELECT id FROM accounts WHERE account_id = '"
            + LEGACY_ACCOUNT_ID
            + "')"
        )
    )
    op.alter_column("t2_manual_entries", "user_id", nullable=False)


def downgrade() -> None:
    op.drop_column("t2_manual_entries", "user_id")
    op.drop_column("gav_ledger", "user_id")
    op.drop_index("ix_disposals_user_year", table_name="disposals")
    op.drop_column("disposals", "user_id")
    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_column("transactions", "user_id")
    op.drop_column("import_batches", "user_id")
    op.drop_index("ix_wallets_user_id_chain", table_name="wallets")
    op.drop_column("wallets", "user_id")
    op.drop_index("ix_custom_chain_account_id", table_name="custom_chain_configs")
    op.drop_table("custom_chain_configs")
    op.drop_index("ix_sessions_token", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_accounts_account_id", table_name="accounts")
    op.drop_table("accounts")
