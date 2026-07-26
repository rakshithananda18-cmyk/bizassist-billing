"""b2b uid columns — durable keys for the cloud→local B2B mirror

WHY
---
B2B rows are the only rows in the system owned by TWO businesses. That makes
them fundamentally different from every other synced table:

  · An invoice has ONE owner, so local→cloud push with last-write-wins is safe.
  · A b2b_connection or b2b_order is a shared record between a buyer and a
    seller who live in DIFFERENT tenants (and often different databases). If
    both sides could author it locally and push, LWW would silently discard one
    party's edit — the exact failure mode flagged as risk #3 in the July 2026
    review, but on the one table where losing a write means losing an order.

So the cloud is the single authority for B2B, and each local install keeps a
READ-ONLY MIRROR pulled down from it (see database/sync_map.PULL_ONLY_TABLES).
The mirror exists purely so the counter can still SEE its connections and
orders when the internet drops.

A mirror needs a key that survives crossing databases — integer ids differ
between a local SQLite file and cloud Postgres. Hence `uid` on the three B2B
tables, matching the pattern every other synced table already uses.

Backfilled for existing rows so the first pull matches instead of duplicating.

IDEMPOTENT: guarded by column-existence checks, because tests build the schema
via Base.metadata.create_all() (which already includes these columns) before
the migration chain runs.

Revision ID: f6a2d8c4b1e9
Revises: e5c9a1d7b3f2
Create Date: 2026-07-25
"""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "f6a2d8c4b1e9"
down_revision = "e5c9a1d7b3f2"
branch_labels = None
depends_on = None

_TABLES = ("b2b_connections", "b2b_orders", "b2b_order_line_items")


def _has_table(table: str) -> bool:
    try:
        return inspect(op.get_bind()).has_table(table)
    except Exception:
        return False


def _cols(table: str) -> set:
    try:
        return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}
    except Exception:
        return set()


def _index_names(table: str) -> set:
    try:
        return {i["name"] for i in inspect(op.get_bind()).get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    for table in _TABLES:
        if not _has_table(table):
            continue

        if "uid" not in _cols(table):
            op.add_column(table, sa.Column("uid", sa.String(36), nullable=True))

        # Backfill. Postgres can do it in one statement; SQLite has no UUID
        # function, so we generate per row (these tables are small — a business
        # has tens of connections, not millions).
        if is_pg:
            op.execute(sa.text(
                f"UPDATE {table} SET uid = gen_random_uuid()::text WHERE uid IS NULL"
            ))
        else:
            rows = bind.execute(sa.text(f"SELECT id FROM {table} WHERE uid IS NULL")).fetchall()
            for (row_id,) in rows:
                bind.execute(
                    sa.text(f"UPDATE {table} SET uid = :u WHERE id = :i"),
                    {"u": str(uuid.uuid4()), "i": row_id},
                )

        # Unique so a re-pull can never duplicate a mirrored row. Partial on the
        # NULLs so any row the backfill missed doesn't block the index.
        idx = f"ix_{table}_uid"
        if idx not in _index_names(table):
            if is_pg:
                op.execute(sa.text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {idx} ON {table} (uid) WHERE uid IS NOT NULL"
                ))
            else:
                op.execute(sa.text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {idx} ON {table} (uid) WHERE uid IS NOT NULL"
                ))


def downgrade() -> None:
    for table in _TABLES:
        if not _has_table(table):
            continue
        idx = f"ix_{table}_uid"
        if idx in _index_names(table):
            op.drop_index(idx, table_name=table)
        if "uid" in _cols(table):
            op.drop_column(table, "uid")
