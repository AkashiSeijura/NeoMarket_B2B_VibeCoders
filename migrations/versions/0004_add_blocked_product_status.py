"""Add blocked product status."""

from __future__ import annotations

from alembic import op


revision = "0004_add_blocked_product_status"
down_revision = "0003_add_sku_moderation_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE product_status ADD VALUE IF NOT EXISTS 'BLOCKED'")


def downgrade() -> None:
    pass
