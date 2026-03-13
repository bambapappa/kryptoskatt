"""add t2_manual_entries table

Revision ID: 007
Revises: 006
Create Date: 2026-03-13
"""
from alembic import op
import sqlalchemy as sa

revision = "007_t2_manual_entries"
down_revision = "f7h6g5f4e3d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "t2_manual_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tax_year", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=True),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("amount_sek", sa.Numeric(18, 2), nullable=False),
        sa.Column("vendor", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_t2_manual_entries_tax_year", "t2_manual_entries", ["tax_year"])


def downgrade() -> None:
    op.drop_index("ix_t2_manual_entries_tax_year", table_name="t2_manual_entries")
    op.drop_table("t2_manual_entries")
