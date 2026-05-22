"""Add processed moderation events."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_add_processed_moderation_events"
down_revision = "0008_add_reserve_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processed_moderation_events",
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("idempotency_key", name=op.f("pk_processed_moderation_events")),
    )


def downgrade() -> None:
    op.drop_table("processed_moderation_events")
