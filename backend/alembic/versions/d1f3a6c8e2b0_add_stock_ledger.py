"""add stock_ledger (billing foundation, append-only, D4)

Additive + backward-compatible: a brand-new table only. Nothing existing is
touched, so all current data and tests are unaffected.

Revision ID: d1f3a6c8e2b0
Revises: b707f13242e7
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa


revision = "d1f3a6c8e2b0"
down_revision = "b707f13242e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("product_name", sa.String(), nullable=True),
        sa.Column("movement_type", sa.String(), nullable=False),
        sa.Column("qty_delta", sa.Float(), nullable=False),
        sa.Column("balance_after", sa.Float(), nullable=True),
        sa.Column("reference_type", sa.String(), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("device_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_stock_ledger_id", "stock_ledger", ["id"])
    op.create_index("ix_stock_ledger_business_id", "stock_ledger", ["business_id"])
    op.create_index("ix_stock_ledger_product_id", "stock_ledger", ["product_id"])
    op.create_index("ix_stock_ledger_product_name", "stock_ledger", ["product_name"])
    op.create_index("ix_stock_ledger_movement_type", "stock_ledger", ["movement_type"])
    op.create_index("ix_stock_ledger_created_at", "stock_ledger", ["created_at"])
    op.create_index("ix_stock_ledger_biz_product", "stock_ledger", ["business_id", "product_id"])
    op.create_index("ix_stock_ledger_biz_name", "stock_ledger", ["business_id", "product_name"])


def downgrade() -> None:
    op.drop_index("ix_stock_ledger_biz_name", table_name="stock_ledger")
    op.drop_index("ix_stock_ledger_biz_product", table_name="stock_ledger")
    op.drop_index("ix_stock_ledger_created_at", table_name="stock_ledger")
    op.drop_index("ix_stock_ledger_movement_type", table_name="stock_ledger")
    op.drop_index("ix_stock_ledger_product_name", table_name="stock_ledger")
    op.drop_index("ix_stock_ledger_product_id", table_name="stock_ledger")
    op.drop_index("ix_stock_ledger_business_id", table_name="stock_ledger")
    op.drop_index("ix_stock_ledger_id", table_name="stock_ledger")
    op.drop_table("stock_ledger")
