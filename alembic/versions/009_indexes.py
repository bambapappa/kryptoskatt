"""add composite indexes for GAV and K4 report queries

Revision ID: 009_indexes
Revises: 008_multi_tenant
Create Date: 2026-03-14
"""
from alembic import op

revision = "009_indexes"
down_revision = "008_multi_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite index used by GAV engine: fetch all transactions for a user in
    # timestamp order (the primary query in calculate()).
    op.create_index(
        "ix_transactions_user_id_timestamp",
        "transactions",
        ["user_id", "timestamp_utc"],
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_user_id_timestamp", table_name="transactions")
