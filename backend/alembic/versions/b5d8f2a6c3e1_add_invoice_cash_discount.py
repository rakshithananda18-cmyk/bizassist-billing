"""add invoices.cash_discount (post-tax cash discount / round-off, R4)

Additive + backward-compatible: one nullable Float column, default 0. Existing
rows read as NULL → treated as 0 → strict no-op (no behaviour change). The column
holds a POST-tax cash discount that reduces the payable but NOT the taxable value
/ GST (the "Cash Dis" line on real kirana receipts; see
BENCHMARK_RECEIPT_MR_TRADERS.md).

IDEMPOTENT: `Base.metadata.create_all()` at import may already have added the
column, so the add is guarded by an existence check.

Revision ID: b5d8f2a6c3e1
Revises: a3c7e9b1d2f4
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b5d8f2a6c3e1"
down_revision = "a3c7e9b1d2f4"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = inspect(op.get_bind())
    try:
        return any(c["name"] == column for c in insp.get_columns(table))
    except Exception:
        return False


def upgrade() -> None:
    if not _has_column("invoices", "cash_discount"):
        op.add_column("invoices", sa.Column("cash_discount", sa.Float(), nullable=True, server_default="0"))


def downgrade() -> None:
    if _has_column("invoices", "cash_discount"):
        op.drop_column("invoices", "cash_discount")
