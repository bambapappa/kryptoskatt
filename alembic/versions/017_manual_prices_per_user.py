"""move manual prices out of the shared price cache into a per-account table

Existing MANUAL rows in price_cache have no owner. They are copied to every
account that has a transaction in that coin (preserving today's results for
the users who could have entered them) and then removed from the shared cache.

Revision ID: 017_manual_prices_per_user
Revises: 016_share_links
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = "017_manual_prices_per_user"
down_revision = "016_share_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_prices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("price_sek", sa.Numeric(precision=28, scale=18), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "symbol", "date", name="uq_manual_prices_user_symbol_date"),
    )
    op.create_index("ix_manual_prices_user_id", "manual_prices", ["user_id"])
    op.execute(
        """
        INSERT INTO manual_prices (user_id, symbol, date, price_sek)
        SELECT DISTINCT t.user_id, UPPER(p.coin_id), p.date, p.price_sek
        FROM price_cache p
        JOIN transactions t ON UPPER(t.base_coin) = UPPER(p.coin_id)
        WHERE p.source = 'MANUAL'
        """
    )
    op.execute("DELETE FROM price_cache WHERE source = 'MANUAL'")


def downgrade() -> None:
    op.drop_index("ix_manual_prices_user_id", table_name="manual_prices")
    op.drop_table("manual_prices")
