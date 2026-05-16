"""Add reserve operations."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_add_reserve_operations"
down_revision = "0007_add_pending_invoice_creation_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reserve_operations",
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("idempotency_key", name=op.f("pk_reserve_operations")),
    )


def downgrade() -> None:
    op.drop_table("reserve_operations")
