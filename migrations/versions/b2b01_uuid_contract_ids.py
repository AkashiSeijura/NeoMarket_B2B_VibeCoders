"""Use UUIDs for B2B product contract identifiers."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b2b01_uuid_contract_ids"
down_revision = "0002_add_product_created_and_seller_id"
branch_labels = None
depends_on = None


uuid_type = postgresql.UUID(as_uuid=True)


def _drop_fk_if_exists(table_name: str, *constraint_names: str) -> None:
    for constraint_name in constraint_names:
        op.execute(f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{constraint_name}"')


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    _drop_fk_if_exists("product_images", "fk_product_images_product_id_products", "product_images_product_id_fkey")
    _drop_fk_if_exists(
        "product_characteristics",
        "fk_product_characteristics_product_id_products",
        "product_characteristics_product_id_fkey",
    )
    _drop_fk_if_exists("skus", "fk_skus_product_id_products", "skus_product_id_fkey")
    _drop_fk_if_exists(
        "sku_characteristics",
        "fk_sku_characteristics_sku_id_skus",
        "sku_characteristics_sku_id_fkey",
    )
    _drop_fk_if_exists("invoice_items", "fk_invoice_items_sku_id_skus", "invoice_items_sku_id_fkey")
    _drop_fk_if_exists("products", "fk_products_category_id_categories", "products_category_id_fkey")

    op.alter_column("categories", "id", existing_type=sa.Integer(), type_=uuid_type, postgresql_using="gen_random_uuid()")
    op.alter_column("products", "id", existing_type=sa.Integer(), type_=uuid_type, postgresql_using="gen_random_uuid()")
    op.alter_column(
        "products",
        "category_id",
        existing_type=sa.Integer(),
        type_=uuid_type,
        postgresql_using="gen_random_uuid()",
    )
    op.alter_column(
        "products",
        "seller_id",
        existing_type=sa.String(length=36),
        type_=uuid_type,
        postgresql_using="seller_id::uuid",
    )
    op.alter_column(
        "product_images",
        "id",
        existing_type=sa.Integer(),
        type_=uuid_type,
        postgresql_using="gen_random_uuid()",
    )
    op.alter_column(
        "product_images",
        "product_id",
        existing_type=sa.Integer(),
        type_=uuid_type,
        postgresql_using="gen_random_uuid()",
    )
    op.alter_column(
        "product_characteristics",
        "id",
        existing_type=sa.Integer(),
        type_=uuid_type,
        postgresql_using="gen_random_uuid()",
    )
    op.alter_column(
        "product_characteristics",
        "product_id",
        existing_type=sa.Integer(),
        type_=uuid_type,
        postgresql_using="gen_random_uuid()",
    )
    op.alter_column(
        "skus",
        "id",
        existing_type=sa.Integer(),
        type_=uuid_type,
        postgresql_using="gen_random_uuid()",
    )
    op.alter_column(
        "skus",
        "product_id",
        existing_type=sa.Integer(),
        type_=uuid_type,
        postgresql_using="gen_random_uuid()",
    )
    op.alter_column(
        "sku_characteristics",
        "id",
        existing_type=sa.Integer(),
        type_=uuid_type,
        postgresql_using="gen_random_uuid()",
    )
    op.alter_column(
        "sku_characteristics",
        "sku_id",
        existing_type=sa.Integer(),
        type_=uuid_type,
        postgresql_using="gen_random_uuid()",
    )
    op.alter_column(
        "invoice_items",
        "sku_id",
        existing_type=sa.Integer(),
        type_=uuid_type,
        postgresql_using="gen_random_uuid()",
    )

    op.create_foreign_key(
        "fk_products_category_id_categories",
        "products",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_product_images_product_id_products",
        "product_images",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_product_characteristics_product_id_products",
        "product_characteristics",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_skus_product_id_products",
        "skus",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_sku_characteristics_sku_id_skus",
        "sku_characteristics",
        "skus",
        ["sku_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_invoice_items_sku_id_skus",
        "invoice_items",
        "skus",
        ["sku_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    _drop_fk_if_exists("product_images", "fk_product_images_product_id_products", "product_images_product_id_fkey")
    _drop_fk_if_exists(
        "product_characteristics",
        "fk_product_characteristics_product_id_products",
        "product_characteristics_product_id_fkey",
    )
    _drop_fk_if_exists("skus", "fk_skus_product_id_products", "skus_product_id_fkey")
    _drop_fk_if_exists(
        "sku_characteristics",
        "fk_sku_characteristics_sku_id_skus",
        "sku_characteristics_sku_id_fkey",
    )
    _drop_fk_if_exists("invoice_items", "fk_invoice_items_sku_id_skus", "invoice_items_sku_id_fkey")
    _drop_fk_if_exists("products", "fk_products_category_id_categories", "products_category_id_fkey")

    op.alter_column(
        "categories",
        "id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using=(
            "CASE name "
            "WHEN 'Smartphones' THEN 1 "
            "WHEN 'Laptops' THEN 2 "
            "WHEN 'Accessories' THEN 3 "
            "ELSE abs(hashtext(id::text)) END"
        ),
    )
    op.alter_column(
        "products",
        "id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(id::text))",
    )
    op.alter_column(
        "products",
        "category_id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(category_id::text))",
    )
    op.alter_column(
        "products",
        "seller_id",
        existing_type=uuid_type,
        type_=sa.String(length=36),
        postgresql_using="seller_id::text",
    )
    op.alter_column(
        "product_images",
        "id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(id::text))",
    )
    op.alter_column(
        "product_images",
        "product_id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(product_id::text))",
    )
    op.alter_column(
        "product_characteristics",
        "id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(id::text))",
    )
    op.alter_column(
        "product_characteristics",
        "product_id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(product_id::text))",
    )
    op.alter_column(
        "skus",
        "id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(id::text))",
    )
    op.alter_column(
        "skus",
        "product_id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(product_id::text))",
    )
    op.alter_column(
        "sku_characteristics",
        "id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(id::text))",
    )
    op.alter_column(
        "sku_characteristics",
        "sku_id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(sku_id::text))",
    )
    op.alter_column(
        "invoice_items",
        "sku_id",
        existing_type=uuid_type,
        type_=sa.Integer(),
        postgresql_using="abs(hashtext(sku_id::text))",
    )

    op.create_foreign_key(
        "fk_products_category_id_categories",
        "products",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_product_images_product_id_products",
        "product_images",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_product_characteristics_product_id_products",
        "product_characteristics",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_skus_product_id_products",
        "skus",
        "products",
        ["product_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_sku_characteristics_sku_id_skus",
        "sku_characteristics",
        "skus",
        ["sku_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_invoice_items_sku_id_skus",
        "invoice_items",
        "skus",
        ["sku_id"],
        ["id"],
        ondelete="RESTRICT",
    )
