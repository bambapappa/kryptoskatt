"""make transfer_links.tx_in_id nullable for address-registry internal transfers

Revision ID: b3f2c1d4e5a6
Revises: ae778706176e
Create Date: 2026-03-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3f2c1d4e5a6'
down_revision: Union[str, None] = 'ae778706176e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make tx_in_id nullable so we can create "confirmed internal" links
    # when only one side of the transfer has been imported, but both addresses
    # are known to belong to the user.
    op.alter_column(
        'transfer_links',
        'tx_in_id',
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # Set any NULL tx_in_id to 0 before making it non-nullable again
    op.execute("UPDATE transfer_links SET tx_in_id = tx_out_id WHERE tx_in_id IS NULL")
    op.alter_column(
        'transfer_links',
        'tx_in_id',
        existing_type=sa.Integer(),
        nullable=False,
    )
