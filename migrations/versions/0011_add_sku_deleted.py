"""Add SKU deleted flag."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_add_sku_deleted"
down_revision = "0010_add_fulfilled_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skus",
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("skus", "deleted", server_default=None)


def downgrade() -> None:
    op.drop_column("skus", "deleted")
