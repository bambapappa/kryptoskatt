"""add account_api_keys table

Revision ID: 015_account_api_keys
Revises: 014_reward_type
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = "015_account_api_keys"
down_revision = "014_reward_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("api_key", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("account_id", "provider", name="uq_account_api_key_provider"),
    )


def downgrade() -> None:
    op.drop_table("account_api_keys")
