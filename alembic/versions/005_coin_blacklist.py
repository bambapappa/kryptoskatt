"""add coin_blacklist table

Revision ID: e6g5f4d3c2b1
Revises: d5f4e3c2b1a0
Create Date: 2026-03-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e6g5f4d3c2b1"
down_revision: Union[str, None] = "d5f4e3c2b1a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coin_blacklist",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("coin_symbol", sa.String(100), nullable=False, unique=True),
        sa.Column("reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("coin_blacklist")
