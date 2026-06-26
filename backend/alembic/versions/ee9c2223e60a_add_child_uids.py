"""add_child_uids

Revision ID: ee9c2223e60a
Revises: b9f1c3e7a2d4
Create Date: 2026-06-27 03:28:21.071832
"""
import uuid
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = 'ee9c2223e60a'
down_revision = 'b9f1c3e7a2d4'
branch_labels = None
depends_on = None


_TABLES = [
    "invoice_line_items",
    "purchase_order_line_items",
    "purchase_invoice_line_items",
    "rate_limit_configs",
    "alert_configs",
    "stock_ledger",
    "product_barcodes",
    "business_settings",
    "invoice_payments",
    "shared_ledgers",
    "stock_transfer_line_items",
]


def _existing_tables(insp) -> set:
    try:
        return set(insp.get_table_names())
    except Exception:
        return set()


def _has_column(insp, table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in insp.get_columns(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    present = _existing_tables(insp)
    is_pg = bind.dialect.name == "postgresql"

    for table in _TABLES:
        if table not in present:
            continue

        if not _has_column(insp, table, "uid"):
            op.add_column(table, sa.Column("uid", sa.String(length=36), nullable=True))

        if is_pg:
            op.execute(
                f'UPDATE "{table}" SET uid = gen_random_uuid()::text WHERE uid IS NULL'
            )
        else:
            rows = bind.execute(
                sa.text(f'SELECT id FROM "{table}" WHERE uid IS NULL')
            ).fetchall()
            for (row_id,) in rows:
                bind.execute(
                    sa.text(f'UPDATE "{table}" SET uid = :u WHERE id = :i'),
                    {"u": str(uuid.uuid4()), "i": row_id},
                )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    present = _existing_tables(insp)
    for table in _TABLES:
        if table in present and _has_column(insp, table, "uid"):
            op.drop_column(table, "uid")
