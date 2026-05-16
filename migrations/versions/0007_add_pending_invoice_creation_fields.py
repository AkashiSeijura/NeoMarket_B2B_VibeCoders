"""Add pending invoice creation fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_add_pending_invoice_creation_fields"
down_revision = "0006_add_product_blocking_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE invoice_status ADD VALUE IF NOT EXISTS 'PENDING'")

    op.add_column(
        "invoices",
        sa.Column(
            "seller_id",
            sa.String(length=36),
            nullable=False,
            server_default="00000000-0000-0000-0000-000000000000",
        ),
    )
    op.alter_column("invoices", "seller_id", server_default=None)
    op.alter_column("invoices", "status", server_default=sa.text("'PENDING'"))
    op.add_column("invoice_items", sa.Column("accepted_quantity", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("invoice_items", "accepted_quantity")
    op.alter_column("invoices", "status", server_default=sa.text("'CREATED'"))
    op.drop_column("invoices", "seller_id")
