"""Align invoice IDs and acceptance contract with OpenAPI."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_invoice_uuid_partial_acceptance"
down_revision = ("0011_add_sku_deleted", "b2b01_uuid_contract_ids")
branch_labels = None
depends_on = None


uuid_type = postgresql.UUID(as_uuid=True)


def _drop_fk_if_exists(table_name: str, *constraint_names: str) -> None:
    for constraint_name in constraint_names:
        op.execute(f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{constraint_name}"')


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE invoice_status ADD VALUE IF NOT EXISTS 'PARTIALLY_ACCEPTED'")
        op.execute("ALTER TYPE invoice_status ADD VALUE IF NOT EXISTS 'CANCELLED'")

    op.execute("ALTER TABLE invoices ADD COLUMN uuid_id uuid NOT NULL DEFAULT gen_random_uuid()")
    op.execute("ALTER TABLE invoice_items ADD COLUMN uuid_id uuid NOT NULL DEFAULT gen_random_uuid()")
    op.execute("ALTER TABLE invoice_items ADD COLUMN uuid_invoice_id uuid")
    op.execute(
        """
        UPDATE invoice_items AS ii
        SET uuid_invoice_id = i.uuid_id
        FROM invoices AS i
        WHERE ii.invoice_id = i.id
        """
    )
    op.execute("ALTER TABLE invoice_items ALTER COLUMN uuid_invoice_id SET NOT NULL")

    _drop_fk_if_exists("invoice_items", "invoice_items_invoice_id_fkey", "fk_invoice_items_invoice_id_invoices")
    op.execute('ALTER TABLE "invoice_items" DROP CONSTRAINT IF EXISTS "invoice_items_pkey"')
    op.execute('ALTER TABLE "invoices" DROP CONSTRAINT IF EXISTS "invoices_pkey"')

    op.drop_column("invoice_items", "id")
    op.alter_column("invoice_items", "uuid_id", new_column_name="id")
    op.drop_column("invoice_items", "invoice_id")
    op.alter_column("invoice_items", "uuid_invoice_id", new_column_name="invoice_id")
    op.drop_column("invoices", "id")
    op.alter_column("invoices", "uuid_id", new_column_name="id")

    op.create_primary_key("invoices_pkey", "invoices", ["id"])
    op.create_primary_key("invoice_items_pkey", "invoice_items", ["id"])
    op.create_foreign_key(
        "fk_invoice_items_invoice_id_invoices",
        "invoice_items",
        "invoices",
        ["invoice_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.alter_column(
        "invoices",
        "seller_id",
        existing_type=sa.String(length=36),
        type_=uuid_type,
        postgresql_using="seller_id::uuid",
        existing_nullable=False,
    )
    op.execute("UPDATE invoice_items SET accepted_quantity = 0 WHERE accepted_quantity IS NULL")
    op.alter_column("invoice_items", "accepted_quantity", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    _drop_fk_if_exists("invoice_items", "invoice_items_invoice_id_fkey", "fk_invoice_items_invoice_id_invoices")
    op.execute('ALTER TABLE "invoice_items" DROP CONSTRAINT IF EXISTS "invoice_items_pkey"')
    op.execute('ALTER TABLE "invoices" DROP CONSTRAINT IF EXISTS "invoices_pkey"')

    op.execute("ALTER TABLE invoices ADD COLUMN int_id integer")
    op.execute("ALTER TABLE invoice_items ADD COLUMN int_id integer")
    op.execute("ALTER TABLE invoice_items ADD COLUMN int_invoice_id integer")
    op.execute("CREATE SEQUENCE IF NOT EXISTS invoices_id_seq")
    op.execute("CREATE SEQUENCE IF NOT EXISTS invoice_items_id_seq")
    op.execute("UPDATE invoices SET int_id = nextval('invoices_id_seq')")
    op.execute("UPDATE invoice_items SET int_id = nextval('invoice_items_id_seq')")
    op.execute(
        """
        UPDATE invoice_items AS ii
        SET int_invoice_id = i.int_id
        FROM invoices AS i
        WHERE ii.invoice_id = i.id
        """
    )
    op.execute("ALTER TABLE invoices ALTER COLUMN int_id SET NOT NULL")
    op.execute("ALTER TABLE invoice_items ALTER COLUMN int_id SET NOT NULL")
    op.execute("ALTER TABLE invoice_items ALTER COLUMN int_invoice_id SET NOT NULL")

    op.drop_column("invoice_items", "id")
    op.alter_column("invoice_items", "int_id", new_column_name="id")
    op.drop_column("invoice_items", "invoice_id")
    op.alter_column("invoice_items", "int_invoice_id", new_column_name="invoice_id")
    op.drop_column("invoices", "id")
    op.alter_column("invoices", "int_id", new_column_name="id")

    op.create_primary_key("invoices_pkey", "invoices", ["id"])
    op.create_primary_key("invoice_items_pkey", "invoice_items", ["id"])
    op.create_foreign_key(
        "fk_invoice_items_invoice_id_invoices",
        "invoice_items",
        "invoices",
        ["invoice_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.alter_column(
        "invoices",
        "seller_id",
        existing_type=uuid_type,
        type_=sa.String(length=36),
        postgresql_using="seller_id::text",
        existing_nullable=False,
    )
    op.alter_column("invoice_items", "accepted_quantity", existing_type=sa.Integer(), nullable=True)
