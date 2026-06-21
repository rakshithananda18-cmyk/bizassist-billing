"""add_purchase_invoices

Revision ID: 7ea4d9eb55fb
Revises: a4c9d2e7b3f1
Create Date: 2026-06-15 23:23:22.488603
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7ea4d9eb55fb'
down_revision = 'a4c9d2e7b3f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Check foreign key on products
    fks = inspector.get_foreign_keys('products')
    fk_names = [fk['name'] for fk in fks if fk['name'] is not None]
    if 'fk_products_variant_of_products' not in fk_names:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("products", schema=None) as batch_op:
                batch_op.create_foreign_key(op.f('fk_products_variant_of_products'), 'products', ['variant_of'], ['id'])
        else:
            op.create_foreign_key(op.f('fk_products_variant_of_products'), 'products', 'products', ['variant_of'], ['id'])

    if not inspector.has_table("purchase_invoices"):
        op.create_table(
            "purchase_invoices",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=True),
            sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("vendors.id", name=op.f("fk_purchase_invoices_supplier_id_vendors")), nullable=True),
            sa.Column("supplier_name", sa.String(), nullable=True),
            sa.Column("invoice_number", sa.String(), nullable=True),
            sa.Column("invoice_date", sa.String(), nullable=True),
            sa.Column("due_date", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=True, server_default="Pending"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("file_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("gstin_buyer", sa.String(), nullable=True),
            sa.Column("place_of_supply", sa.String(), nullable=True),
            sa.Column("invoice_type", sa.String(), nullable=True),
            sa.Column("subtotal", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("cgst_total", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("sgst_total", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("igst_total", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("cess_total", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("total_amount", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("reverse_charge", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("is_tax_inclusive", sa.Boolean(), nullable=True, server_default=sa.false()),
            sa.Column("discount_total", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("round_off", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("irn", sa.String(), nullable=True),
            sa.Column("ack_no", sa.String(), nullable=True),
            sa.Column("ack_date", sa.String(), nullable=True),
            sa.Column("qr_code", sa.Text(), nullable=True),
        )
        op.create_index("ix_purchase_invoices_id", "purchase_invoices", ["id"])
        op.create_index("ix_purchase_invoices_business_id", "purchase_invoices", ["business_id"])
        op.create_index("ix_purchase_invoices_supplier_id", "purchase_invoices", ["supplier_id"])
        op.create_index("ix_purchase_invoices_invoice_number", "purchase_invoices", ["invoice_number"])
        op.create_index("ix_purchase_invoices_file_id", "purchase_invoices", ["file_id"])
        
        with op.batch_alter_table('purchase_invoices', schema=None) as batch_op:
            batch_op.create_index('ix_purchase_invoice_business_date', ['business_id', 'invoice_date'], unique=False)
            batch_op.create_index('ix_purchase_invoice_business_status', ['business_id', 'status'], unique=False)

    if not inspector.has_table("purchase_invoice_line_items"):
        op.create_table(
            "purchase_invoice_line_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("purchase_invoice_id", sa.Integer(), sa.ForeignKey("purchase_invoices.id", name=op.f("fk_purchase_invoice_line_items_purchase_invoice_id_purchase_invoices")), nullable=False),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", name=op.f("fk_purchase_invoice_line_items_product_id_products")), nullable=True),
            sa.Column("product_name", sa.String(), nullable=False),
            sa.Column("hsn_sac", sa.String(), nullable=True),
            sa.Column("unit", sa.String(), nullable=True, server_default="Nos"),
            sa.Column("quantity", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("purchase_unit", sa.String(), nullable=True),
            sa.Column("conversion_factor", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("unit_price", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("cgst_rate", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("sgst_rate", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("igst_rate", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("taxable_value", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("cgst_amount", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("sgst_amount", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("igst_amount", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("line_total", sa.Float(), nullable=True, server_default="0.0"),
            sa.Column("batch", sa.String(), nullable=True),
            sa.Column("expiry", sa.String(), nullable=True),
            sa.Column("confidence_score", sa.Float(), nullable=True, server_default="1.0"),
            sa.Column("is_matched", sa.Boolean(), nullable=True, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_purchase_invoice_line_items_id", "purchase_invoice_line_items", ["id"])
        op.create_index("ix_purchase_invoice_line_items_purchase_invoice_id", "purchase_invoice_line_items", ["purchase_invoice_id"])
        op.create_index("ix_purchase_invoice_line_items_product_id", "purchase_invoice_line_items", ["product_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    if inspector.has_table("purchase_invoice_line_items"):
        op.drop_table("purchase_invoice_line_items")
        
    if inspector.has_table("purchase_invoices"):
        op.drop_table("purchase_invoices")
        
    fks = inspector.get_foreign_keys('products')
    fk_names = [fk['name'] for fk in fks if fk['name'] is not None]
    if 'fk_products_variant_of_products' in fk_names:
        op.drop_constraint(op.f('fk_products_variant_of_products'), 'products', type_='foreignkey')
