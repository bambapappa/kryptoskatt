"""widen base_coin, quote_coin, fee_coin from VARCHAR(20) to VARCHAR(100)

Revision ID: d5f4e3c2b1a0
Revises: c4e3d2f1a0b9
Create Date: 2026-03-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d5f4e3c2b1a0"
down_revision: Union[str, None] = "c4e3d2f1a0b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("transactions", "base_coin", type_=sa.String(100), existing_nullable=False)
    op.alter_column("transactions", "quote_coin", type_=sa.String(100), existing_nullable=True)
    op.alter_column("transactions", "fee_coin", type_=sa.String(100), existing_nullable=True)


def downgrade() -> None:
    op.alter_column("transactions", "base_coin", type_=sa.String(20), existing_nullable=False)
    op.alter_column("transactions", "quote_coin", type_=sa.String(20), existing_nullable=True)
    op.alter_column("transactions", "fee_coin", type_=sa.String(20), existing_nullable=True)
