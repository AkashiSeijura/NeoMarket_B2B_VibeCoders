"""Add product blocking feedback fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_add_product_blocking_fields"
down_revision = "0005_add_product_deleted"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("blocking_reason", sa.JSON(), nullable=True))
    op.add_column("products", sa.Column("field_reports", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "field_reports")
    op.drop_column("products", "blocking_reason")
