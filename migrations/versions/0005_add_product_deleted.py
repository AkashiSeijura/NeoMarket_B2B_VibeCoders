"""Add product soft delete flag."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_add_product_deleted"
down_revision = "0004_add_blocked_product_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("products", "deleted", server_default=None)


def downgrade() -> None:
    op.drop_column("products", "deleted")
