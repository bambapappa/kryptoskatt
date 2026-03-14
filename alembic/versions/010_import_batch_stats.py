"""add imported_count and duplicate_count to import_batches

Revision ID: 010_import_batch_stats
Revises: 009_indexes
Create Date: 2026-03-14
"""
import sqlalchemy as sa
from alembic import op

revision = "010_import_batch_stats"
down_revision = "009_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_batches",
        sa.Column("imported_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "import_batches",
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("import_batches", "duplicate_count")
    op.drop_column("import_batches", "imported_count")
