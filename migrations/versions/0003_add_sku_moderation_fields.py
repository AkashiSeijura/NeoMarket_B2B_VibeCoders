"""Add SKU moderation fields and hard-blocked product status."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_add_sku_moderation_fields"
down_revision = "0002_add_product_created_and_seller_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE product_status ADD VALUE IF NOT EXISTS 'HARD_BLOCKED'")

    op.add_column(
        "skus",
        sa.Column("cost_price", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.alter_column("skus", "cost_price", server_default=None)

    op.add_column(
        "skus",
        sa.Column("discount", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    op.add_column(
        "skus",
        sa.Column("image", sa.String(length=1024), nullable=False, server_default=""),
    )
    op.alter_column("skus", "image", server_default=None)

    op.add_column(
        "skus",
        sa.Column("reserved_quantity", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("skus", "reserved_quantity")
    op.drop_column("skus", "image")
    op.drop_column("skus", "discount")
    op.drop_column("skus", "cost_price")
