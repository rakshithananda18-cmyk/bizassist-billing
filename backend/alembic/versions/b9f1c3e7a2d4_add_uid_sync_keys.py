"""add uid sync keys to business-owned tables (Step 3 / R-3, Phase A)

Durable, globally-unique key for cross-DB sync/migration. The integer `id` is a
per-database autoincrement (local id=10 != cloud id=10), so matching cross-DB on
`id` causes wrong-row overwrites. Phase A is ADDITIVE ONLY: add a nullable
`uid` column to each business-owned table and backfill existing rows with a
UUID. No behaviour change — sync/migration still match on `id` until Phase B
switches the match key (with an id fallback).

Scope: the 11 tables that inherit BusinessOwnedMixin (the main entities where
id-collisions actually bite). Child/aux tables (line items, ledgers, settings)
are TimestampMixin-only and get `uid` in a follow-up (Phase A.2).

IDEMPOTENT: `Base.metadata.create_all()` at import may already have added the
column on a fresh DB, so every add is guarded by an existence check. Backfill
only touches NULL rows, so re-running is safe.

Revision ID: b9f1c3e7a2d4
Revises: d7e3a9c6f8b1
Create Date: 2026-06-27
"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b9f1c3e7a2d4"
down_revision = "d7e3a9c6f8b1"
branch_labels = None
depends_on = None


# Tables inheriting BusinessOwnedMixin (Phase A scope).
# NOTE: the runtime migration path is database/migration.py (_COLUMN_MIGRATIONS +
# _backfill_null_uids), which is what the app actually runs on startup. This
# Alembic revision is kept in parallel for parity with the repo's dual-maintained
# migration history; it is not the startup mechanism.
_TABLES = [
    "customers",
    "vendors",
    "products",
    "invoices",
    "inventory",
    "payments",
    "purchase_orders",
    "purchase_invoices",
    "expenses",
    "godowns",
    "stock_transfers",
    "journal_entries",
    "period_locks",
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
            continue  # table not created on this DB yet — create_all handles it

        # 1. add the column (guarded — create_all may have added it already)
        if not _has_column(insp, table, "uid"):
            op.add_column(table, sa.Column("uid", sa.String(length=36), nullable=True))

        # 2. backfill existing NULL rows
        if is_pg:
            # gen_random_uuid() is built in on Supabase/PG13+ (pgcrypto).
            op.execute(
                f'UPDATE "{table}" SET uid = gen_random_uuid()::text WHERE uid IS NULL'
            )
        else:
            # SQLite has no UUID function — backfill row-by-row in Python.
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
