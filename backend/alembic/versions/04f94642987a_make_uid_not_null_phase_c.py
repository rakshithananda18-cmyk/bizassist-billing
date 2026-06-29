"""make_uid_not_null_phase_c

Revision ID: 04f94642987a
Revises: c4d2e6f8a1b3
Create Date: 2026-06-30 03:31:36.943232
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '04f94642987a'
down_revision = 'c4d2e6f8a1b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = [
        "customers", "vendors", "products", "invoices", "invoice_line_items",
        "inventory", "payments", "stock_ledger", "product_barcodes",
        "business_settings", "invoice_payments", "shared_ledgers",
        "expenses", "godowns", "stock_transfers", "stock_transfer_line_items",
        "purchase_invoices", "purchase_invoice_line_items", "purchase_orders",
        "purchase_order_line_items", "alert_configs", "rate_limit_configs"
    ]
    for table in tables:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column('uid', nullable=False)


def downgrade() -> None:
    tables = [
        "customers", "vendors", "products", "invoices", "invoice_line_items",
        "inventory", "payments", "stock_ledger", "product_barcodes",
        "business_settings", "invoice_payments", "shared_ledgers",
        "expenses", "godowns", "stock_transfers", "stock_transfer_line_items",
        "purchase_invoices", "purchase_invoice_line_items", "purchase_orders",
        "purchase_order_line_items", "alert_configs", "rate_limit_configs"
    ]
    for table in tables:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column('uid', nullable=True)
