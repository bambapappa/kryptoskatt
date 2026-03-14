"""add label column to transactions

Revision ID: 011_transaction_labels
Revises: 010_import_batch_stats
Create Date: 2026-03-14
"""

import sqlalchemy as sa

from alembic import op

revision = "011_transaction_labels"
down_revision = "010_import_batch_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("label", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transactions", "label")
