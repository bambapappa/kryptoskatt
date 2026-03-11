"""add category column to wallets

Revision ID: c4e3d2f1a0b9
Revises: b3f2c1d4e5a6
Create Date: 2026-03-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e3d2f1a0b9'
down_revision: Union[str, None] = 'b3f2c1d4e5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'wallets',
        sa.Column('category', sa.String(50), nullable=False, server_default='own'),
    )


def downgrade() -> None:
    op.drop_column('wallets', 'category')
