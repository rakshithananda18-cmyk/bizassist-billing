"""universal compatibility fields (all business types + GST Rule-46)

Makes the product/invoice schema fit EVERY business type (retail, wholesale,
pharmacy, garments, restaurant, services) and adds the GST-mandatory
`reverse_charge` field that was missing.

All columns are ADDITIVE + NULLABLE (with safe server defaults). Nothing existing
is altered or dropped — fully backward-compatible.

Revision ID: f3b8c1e6a2d7
Revises: e2a4b7d9c1f5
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa


revision = "f3b8c1e6a2d7"
down_revision = "e2a4b7d9c1f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── products: universal item-master fields ───────────────────────────────
    with op.batch_alter_table("products") as b:
        b.add_column(sa.Column("sku", sa.String(), nullable=True))
        b.add_column(sa.Column("brand", sa.String(), nullable=True))
        b.add_column(sa.Column("manufacturer", sa.String(), nullable=True))
        b.add_column(sa.Column("category", sa.String(), nullable=True))
        b.add_column(sa.Column("track_inventory", sa.Boolean(), nullable=True, server_default=sa.true()))
        b.add_column(sa.Column("price_includes_tax", sa.Boolean(), nullable=True, server_default=sa.false()))
        b.add_column(sa.Column("purchase_unit", sa.String(), nullable=True))
        b.add_column(sa.Column("conversion_factor", sa.Float(), nullable=True, server_default="1.0"))
        b.add_column(sa.Column("variant_of", sa.Integer(), nullable=True))
        b.add_column(sa.Column("attributes", sa.Text(), nullable=True))
    op.create_index("ix_products_sku", "products", ["sku"])
    op.create_index("ix_products_category", "products", ["category"])
    op.create_index("ix_products_variant_of", "products", ["variant_of"])

    # ── invoices: GST Rule-46 + universal billing fields ─────────────────────
    with op.batch_alter_table("invoices") as b:
        b.add_column(sa.Column("reverse_charge", sa.Boolean(), nullable=True, server_default=sa.false()))
        b.add_column(sa.Column("is_tax_inclusive", sa.Boolean(), nullable=True, server_default=sa.false()))
        b.add_column(sa.Column("discount_total", sa.Float(), nullable=True, server_default="0.0"))
        b.add_column(sa.Column("round_off", sa.Float(), nullable=True, server_default="0.0"))

    # ── purchase_orders share GSTFieldsMixin → same new doc-level columns ─────
    with op.batch_alter_table("purchase_orders") as b:
        b.add_column(sa.Column("reverse_charge", sa.Boolean(), nullable=True, server_default=sa.false()))
        b.add_column(sa.Column("is_tax_inclusive", sa.Boolean(), nullable=True, server_default=sa.false()))
        b.add_column(sa.Column("discount_total", sa.Float(), nullable=True, server_default="0.0"))
        b.add_column(sa.Column("round_off", sa.Float(), nullable=True, server_default="0.0"))

    # ── invoice_line_items: line description + batch/serial at sale ──────────
    with op.batch_alter_table("invoice_line_items") as b:
        b.add_column(sa.Column("description", sa.Text(), nullable=True))
        b.add_column(sa.Column("batch_no", sa.String(), nullable=True))
        b.add_column(sa.Column("serial_no", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invoice_line_items") as b:
        b.drop_column("serial_no")
        b.drop_column("batch_no")
        b.drop_column("description")
    with op.batch_alter_table("purchase_orders") as b:
        b.drop_column("round_off")
        b.drop_column("discount_total")
        b.drop_column("is_tax_inclusive")
        b.drop_column("reverse_charge")
    with op.batch_alter_table("invoices") as b:
        b.drop_column("round_off")
        b.drop_column("discount_total")
        b.drop_column("is_tax_inclusive")
        b.drop_column("reverse_charge")
    op.drop_index("ix_products_variant_of", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_index("ix_products_sku", table_name="products")
    with op.batch_alter_table("products") as b:
        b.drop_column("attributes")
        b.drop_column("variant_of")
        b.drop_column("conversion_factor")
        b.drop_column("purchase_unit")
        b.drop_column("price_includes_tax")
        b.drop_column("track_inventory")
        b.drop_column("category")
        b.drop_column("manufacturer")
        b.drop_column("brand")
        b.drop_column("sku")
