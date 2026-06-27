"""phase_c_uid_unique_indexes  (Step 3 Phase C — part 1 of 3)

Revision ID: a1b2c3d4e5f6
Revises: ee9c2223e60a
Create Date: 2026-06-27

Step 3 Phase C, part 1 — ADDITIVE + REVERSIBLE. Adds a UNIQUE index on the
durable ``uid`` for every synced table:
  - ``(business_id, uid)`` where the table is business-scoped,
  - ``(uid)`` for the child/aux tables that have no ``business_id``.

Why a unique *index* and not a table-level ``UniqueConstraint``: a unique index
is created identically on SQLite and Postgres with ``op.create_index(...,
unique=True)`` — no ``batch_alter_table`` table rebuild on SQLite, so it is far
lower risk. It doubles as the lookup index Phase B reads on.

PRE-FLIGHT GUARDED: before creating each index this RAISES (aborts the whole
migration in its transaction) if the table still has a NULL ``uid`` or a
duplicate ``(scope, uid)`` group — creating the index would otherwise fail
mid-run. Run the Phase A/A.2 backfill (``_backfill_null_uids``) first if it trips.

EXPLICITLY OUT OF SCOPE (later Phase C parts, only after B.2 soaks):
  * part 2 — make ``uid`` NOT NULL,
  * part 3 — retire the ``?remap_ids`` natural-key fallback, the ``users``
    exclusion, and the ``id``-fallback branches in push/pull/import.

APPLY MANUALLY (NOT the startup path): ``alembic upgrade head`` on BOTH local
SQLite and cloud Postgres, after confirming the DB is stamped past the baseline
(``alembic stamp`` if needed — do NOT replay the baseline). Test local-first.
"""
from alembic import op
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "ee9c2223e60a"
branch_labels = None
depends_on = None


_UID_TABLES = [
    "customers", "vendors", "products", "invoices", "inventory", "payments",
    "purchase_orders", "purchase_invoices", "expenses", "godowns", "stock_transfers",
    "journal_entries", "period_locks",
    "invoice_line_items", "purchase_order_line_items", "purchase_invoice_line_items",
    "rate_limit_configs", "alert_configs", "stock_ledger", "product_barcodes",
    "business_settings", "invoice_payments", "shared_ledgers", "stock_transfer_line_items",
]


def _cols(insp, table) -> set:
    try:
        return {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return set()


def _index_names(insp, table) -> set:
    try:
        return {ix["name"] for ix in insp.get_indexes(table)}
    except Exception:
        return set()


def _index_name(table: str, scoped: bool) -> str:
    return f"uq_{table}_business_uid" if scoped else f"uq_{table}_uid"


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    present = set(insp.get_table_names())

    for table in _UID_TABLES:
        if table not in present:
            continue
        cols = _cols(insp, table)
        if "uid" not in cols:
            continue

        scoped = "business_id" in cols
        ix_name = _index_name(table, scoped)
        if ix_name in _index_names(insp, table):
            continue  # idempotent

        # Pre-flight: NULL uid would violate the (eventual) contract and, more
        # immediately, a duplicate would make a UNIQUE index creation fail.
        null_uids = bind.execute(
            text(f'SELECT COUNT(*) FROM "{table}" WHERE uid IS NULL')
        ).scalar() or 0
        if null_uids:
            raise RuntimeError(
                f"Phase C aborted: '{table}' has {null_uids} NULL uid(s). "
                f"Run the uid backfill (Phase A/A.2) before adding the unique index."
            )

        if scoped:
            dups = bind.execute(text(
                f'SELECT COUNT(*) FROM (SELECT business_id, uid FROM "{table}" '
                f'GROUP BY business_id, uid HAVING COUNT(*) > 1) d'
            )).scalar() or 0
        else:
            dups = bind.execute(text(
                f'SELECT COUNT(*) FROM (SELECT uid FROM "{table}" '
                f'GROUP BY uid HAVING COUNT(*) > 1) d'
            )).scalar() or 0
        if dups:
            raise RuntimeError(
                f"Phase C aborted: '{table}' has {dups} duplicate uid group(s). "
                f"De-duplicate before adding the unique index."
            )

        cols_for_index = ["business_id", "uid"] if scoped else ["uid"]
        op.create_index(ix_name, table, cols_for_index, unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    present = set(insp.get_table_names())

    for table in _UID_TABLES:
        if table not in present:
            continue
        scoped = "business_id" in _cols(insp, table)
        ix_name = _index_name(table, scoped)
        if ix_name in _index_names(insp, table):
            op.drop_index(ix_name, table_name=table)
