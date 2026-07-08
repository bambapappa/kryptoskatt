"""add share_links table

Revision ID: 016_share_links
Revises: 015_account_api_keys
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = "016_share_links"
down_revision = "015_account_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "share_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_share_links_token_hash", "share_links", ["token_hash"])
    op.create_index("ix_share_links_account_id", "share_links", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_share_links_account_id", table_name="share_links")
    op.drop_index("ix_share_links_token_hash", table_name="share_links")
    op.drop_table("share_links")
