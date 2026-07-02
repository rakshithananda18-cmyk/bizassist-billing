"""add invoice print fields (invoice-template system, Phase 1)

Adds the print-payload snapshot fields (plan §Phase-1 migration #1):
  invoices.invoice_title          — stored display-title override (presentation-only)
  invoice_line_items.mrp          — MRP at sale time (retail/pharma print column)
  invoice_line_items.expiry_date  — expiry at sale time (pharma print column)
  invoice_line_items.attributes   — JSON snapshot of vertical fields (size/color/warranty…)

All additive + nullable: zero backfill, historical rows render via fallbacks in
core/billing/print_payload.py. Mirrored for local SQLite in database/migration.py
(_COLUMN_MIGRATIONS) per the universal-compatibility convention.

Revision ID: a8d3f1c9e5b7
Revises: 3b7d5e0a9c1f
"""
from alembic import op
import sqlalchemy as sa

revision = "a8d3f1c9e5b7"
down_revision = "3b7d5e0a9c1f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoices", sa.Column("invoice_title", sa.String(), nullable=True))
    op.add_column("invoice_line_items", sa.Column("mrp", sa.Float(), nullable=True))
    op.add_column("invoice_line_items", sa.Column("expiry_date", sa.String(), nullable=True))
    op.add_column("invoice_line_items", sa.Column("attributes", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("invoice_line_items", "attributes")
    op.drop_column("invoice_line_items", "expiry_date")
    op.drop_column("invoice_line_items", "mrp")
    op.drop_column("invoices", "invoice_title")
