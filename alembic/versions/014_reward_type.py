"""add reward_type to transactions

Revision ID: 014_reward_type
Revises: 013_per_user_blacklist
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = "014_reward_type"
down_revision = "013_per_user_blacklist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("reward_type", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("transactions", "reward_type")
