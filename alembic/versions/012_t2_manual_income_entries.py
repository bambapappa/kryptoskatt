"""add t2_manual_income_entries table

Revision ID: 012_t2_manual_income_entries
Revises: 011_transaction_labels
Create Date: 2026-03-15
"""

from alembic import op
import sqlalchemy as sa

revision = "012_t2_manual_income_entries"
down_revision = "011_transaction_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "t2_manual_income_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False, server_default="REWARD"),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("amount_sek", sa.Numeric(18, 2), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_t2_manual_income_entries_user_year", "t2_manual_income_entries", ["user_id", "tax_year"])


def downgrade() -> None:
    op.drop_index("ix_t2_manual_income_entries_user_year", table_name="t2_manual_income_entries")
    op.drop_table("t2_manual_income_entries")
