"""widen coin columns in disposals and gav_ledger from VARCHAR(20) to VARCHAR(100)

Revision ID: f7h6g5f4e3d2
Revises: e6g5f4d3c2b1
Create Date: 2026-03-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f7h6g5f4e3d2"
down_revision: Union[str, None] = "e6g5f4d3c2b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("disposals", "coin", type_=sa.String(100), existing_nullable=False)
    op.alter_column("gav_ledger", "coin", type_=sa.String(100), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("disposals", "coin", type_=sa.String(20), existing_nullable=False)
    op.alter_column("gav_ledger", "coin", type_=sa.String(20), existing_nullable=False)
