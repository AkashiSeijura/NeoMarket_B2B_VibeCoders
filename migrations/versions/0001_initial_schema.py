"""Initial schema for B2B seller cabinet."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


product_status = postgresql.ENUM(
    "DRAFT",
    "ON_MODERATION",
    "MODERATED",
    "REJECTED",
    name="product_status",
    create_type=False,
)

invoice_status = postgresql.ENUM(
    "CREATED",
    "ACCEPTED",
    name="invoice_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    product_status.create(bind, checkfirst=True)
    invoice_status.create(bind, checkfirst=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", product_status, nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT"),
    )

    op.create_table(
        "product_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("ordering", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "product_characteristics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "skus",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("active_quantity", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "sku_characteristics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("status", invoice_status, nullable=False, server_default=sa.text("'CREATED'")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    op.create_table(
        "invoice_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
    )

    category_table = sa.table(
        "categories",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
    )
    op.bulk_insert(
        category_table,
        [
            {"id": 1, "name": "Smartphones"},
            {"id": 2, "name": "Laptops"},
            {"id": 3, "name": "Accessories"},
        ],
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_table("invoice_items")
    op.drop_table("invoices")
    op.drop_table("sku_characteristics")
    op.drop_table("skus")
    op.drop_table("product_characteristics")
    op.drop_table("product_images")
    op.drop_table("products")
    op.drop_table("categories")

    invoice_status.drop(bind, checkfirst=True)
    product_status.drop(bind, checkfirst=True)
