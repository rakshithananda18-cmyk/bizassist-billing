"""enforce invoice-number uniqueness at the database level (M-3)

`core/billing/sequence.py` guarantees a number is never issued twice — but only
for callers that go through it. An import, a sync apply or a repair script
writing an Invoice directly can still land a duplicate, and the first anyone
would notice is a mismatched GSTR filing. Application-level uniqueness is not
uniqueness.

PARTIAL index (`WHERE invoice_id IS NOT NULL`): CSV-imported invoices may carry
no number, and multiple NULLs must not conflict with one another.

REFUSES TO CREATE OVER EXISTING DUPLICATES. Renumbering an already-issued tax
invoice is not something a migration may do silently — the number may be printed
on a customer's copy and filed in a GST return. If duplicates exist we raise with
the offending numbers listed so they are resolved deliberately.

IDEMPOTENT: guarded by an existence check, and the local SQLite path creates the
same index from `database/migration.py::_ensure_invoice_number_unique_index`
(which logs and skips instead of raising, because a boot must not be blocked).

Revision ID: c8e1b4f7d203
Revises: a7d3f0c9e514
Create Date: 2026-07-26
"""
from alembic import op
from sqlalchemy import inspect, text


revision = "c8e1b4f7d203"
down_revision = "a7d3f0c9e514"
branch_labels = None
depends_on = None

INDEX_NAME = "uix_invoices_biz_number_notnull"


def _index_exists(bind, name: str) -> bool:
    try:
        if bind.dialect.name == "postgresql":
            return bind.execute(
                text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": name}
            ).fetchone() is not None
        return bind.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='index' AND name = :n"),
            {"n": name},
        ).fetchone() is not None
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    if "invoices" not in set(inspect(bind).get_table_names()):
        return
    if _index_exists(bind, INDEX_NAME):
        return

    dupes = bind.execute(text(
        "SELECT business_id, invoice_id, COUNT(*) AS n FROM invoices "
        "WHERE invoice_id IS NOT NULL "
        "GROUP BY business_id, invoice_id HAVING COUNT(*) > 1"
    )).fetchall()
    if dupes:
        listed = "; ".join(f"business {d[0]} number '{d[1]}' x{d[2]}" for d in dupes[:50])
        raise RuntimeError(
            "Cannot enforce invoice-number uniqueness: duplicate numbers already "
            "exist. These must be resolved deliberately — an issued invoice "
            "number may be printed on a customer's copy and filed in a GST "
            f"return, so this migration will not reassign them. Duplicates: {listed}"
        )

    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
        f"ON invoices (business_id, invoice_id) WHERE invoice_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
