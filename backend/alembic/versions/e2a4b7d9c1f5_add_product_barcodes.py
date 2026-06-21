"""add product_barcodes (one product -> many barcodes)

Additive + backward-compatible: a new table only; `products.barcode` stays as
the primary/display code. Nothing existing is touched.

Revision ID: e2a4b7d9c1f5
Revises: d1f3a6c8e2b0
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa


revision = "e2a4b7d9c1f5"
down_revision = "d1f3a6c8e2b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_barcodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("barcode", sa.String(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("business_id", "barcode", name="uq_product_barcode_biz_code"),
    )
    op.create_index("ix_product_barcodes_id", "product_barcodes", ["id"])
    op.create_index("ix_product_barcodes_business_id", "product_barcodes", ["business_id"])
    op.create_index("ix_product_barcodes_product_id", "product_barcodes", ["product_id"])
    op.create_index("ix_product_barcodes_barcode", "product_barcodes", ["barcode"])
    op.create_index("ix_product_barcode_biz_code", "product_barcodes", ["business_id", "barcode"])
    op.create_index("ix_product_barcode_product", "product_barcodes", ["business_id", "product_id"])


def downgrade() -> None:
    op.drop_index("ix_product_barcode_product", table_name="product_barcodes")
    op.drop_index("ix_product_barcode_biz_code", table_name="product_barcodes")
    op.drop_index("ix_product_barcodes_barcode", table_name="product_barcodes")
    op.drop_index("ix_product_barcodes_product_id", table_name="product_barcodes")
    op.drop_index("ix_product_barcodes_business_id", table_name="product_barcodes")
    op.drop_index("ix_product_barcodes_id", table_name="product_barcodes")
    op.drop_table("product_barcodes")
