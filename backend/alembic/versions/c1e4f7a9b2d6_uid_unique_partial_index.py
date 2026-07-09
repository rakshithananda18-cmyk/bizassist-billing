"""add partial unique index on uid for all business-owned tables

IDEMPOTENT: safe to run on fresh DBs and existing ones.

Strategy:
  1. Deduplicate any rows that share the same (uid, business_id) — keeps the
     highest id (most recent). This cleans up duplicates before indexing.
  2. Create a partial UNIQUE index ON uid WHERE uid IS NOT NULL — future
     inserts are rejected at DB level if they double-insert the same uid.
     NULL uids are excluded so backfill rows don't clash.

Works on SQLite (partial indexes since 3.8.9) and PostgreSQL.

Revision ID: c1e4f7a9b2d6
Revises: ba1f7c3e9d20
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision      = "c1e4f7a9b2d6"
down_revision = "ba1f7c3e9d20"
branch_labels = None
depends_on    = None

_UID_TABLES = [
    "customers", "vendors", "products", "invoices", "inventory", "payments",
    "purchase_orders", "purchase_invoices", "expenses", "godowns",
    "stock_transfers", "journal_entries", "period_locks",
    "invoice_line_items", "purchase_order_line_items",
    "purchase_invoice_line_items", "rate_limit_configs", "alert_configs",
    "stock_ledger", "product_barcodes", "business_settings",
    "invoice_payments", "b2b_ledgers", "stock_transfer_line_items",
    "register_shifts", "shift_cash_movements",
]

_DEDUP_TABLES = [
    "invoices", "invoice_payments", "customers", "vendors", "products",
    "purchase_invoices", "expenses", "inventory", "godowns",
    "stock_transfers", "purchase_orders",
]


def _table_exists(insp, table):
    try:
        return insp.has_table(table)
    except Exception:
        return False


def _has_column(insp, table, col):
    try:
        return any(c["name"] == col for c in insp.get_columns(table))
    except Exception:
        return False


def upgrade():
    bind  = op.get_bind()
    insp  = inspect(bind)
    is_pg = bind.dialect.name == "postgresql"

    # Step 1: Deduplicate (keep highest id per uid+business_id group)
    for table in _DEDUP_TABLES:
        if not _table_exists(insp, table):
            continue
        if not _has_column(insp, table, "uid") or not _has_column(insp, table, "business_id"):
            continue
        try:
            if is_pg:
                bind.execute(text(f'''
                    WITH ranked AS (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY uid, business_id
                                   ORDER BY id DESC
                               ) AS rn
                        FROM   "{table}"
                        WHERE  uid IS NOT NULL
                    )
                    DELETE FROM "{table}"
                    WHERE  id IN (SELECT id FROM ranked WHERE rn > 1)
                '''))
            else:
                dup_ids = bind.execute(text(f'''
                    SELECT id FROM {table}
                    WHERE uid IS NOT NULL
                      AND id NOT IN (
                          SELECT MAX(id) FROM {table}
                          WHERE uid IS NOT NULL
                          GROUP BY uid, business_id
                      )
                ''')).fetchall()
                for (dup_id,) in dup_ids:
                    bind.execute(text(f"DELETE FROM {table} WHERE id = :i"), {"i": dup_id})
        except Exception:
            pass

    # Step 2: Create partial UNIQUE indexes
    for table in _UID_TABLES:
        if not _table_exists(insp, table):
            continue
        if not _has_column(insp, table, "uid"):
            continue
        idx_name = f"uix_{table}_uid_notnull"
        try:
            if is_pg:
                bind.execute(text(f'''
                    CREATE UNIQUE INDEX IF NOT EXISTS {idx_name}
                    ON "{table}" (uid)
                    WHERE uid IS NOT NULL
                '''))
            else:
                already = bind.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type='index' AND name=:n"),
                    {"n": idx_name},
                ).fetchone()
                if not already:
                    bind.execute(text(f'''
                        CREATE UNIQUE INDEX {idx_name}
                        ON {table} (uid)
                        WHERE uid IS NOT NULL
                    '''))
        except Exception:
            pass  # index may already exist under a different name


def downgrade():
    bind  = op.get_bind()
    insp  = inspect(bind)
    for table in _UID_TABLES:
        if not _table_exists(insp, table):
            continue
        idx_name = f"uix_{table}_uid_notnull"
        try:
            bind.execute(text(f"DROP INDEX IF EXISTS {idx_name}"))
        except Exception:
            pass
