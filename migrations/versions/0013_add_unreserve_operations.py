"""Add unreserve operations."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_add_unreserve_operations"
down_revision = "0012_invoice_uuid_partial_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "unreserve_operations",
        sa.Column("order_id", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("order_id", name=op.f("pk_unreserve_operations")),
    )


def downgrade() -> None:
    op.drop_table("unreserve_operations")
