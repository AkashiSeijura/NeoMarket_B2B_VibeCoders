"""Add CREATED product status and product seller ownership."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_add_product_created_and_seller_id"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE product_status ADD VALUE IF NOT EXISTS 'CREATED'")
    op.add_column(
        "products",
        sa.Column(
            "seller_id",
            sa.String(length=36),
            nullable=False,
            server_default="00000000-0000-0000-0000-000000000000",
        ),
    )
    op.alter_column("products", "seller_id", server_default=None)
    op.alter_column("products", "status", server_default=sa.text("'CREATED'"))


def downgrade() -> None:
    op.alter_column("products", "status", server_default=sa.text("'DRAFT'"))
    op.drop_column("products", "seller_id")
