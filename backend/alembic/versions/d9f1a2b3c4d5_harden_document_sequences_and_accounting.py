"""harden document sequence isolation and accounting schema

Revision ID: d9f1a2b3c4d5
Revises: c8e1b4f7d203
Create Date: 2026-10-24

``document_sequences`` was added after the original tenant-policy migration,
so it needs its own forced RLS policy.  The same release adds the database
backstop for journal posting idempotency.

Applied by hand like the rest of this chain (``alembic upgrade head``), not at
boot; it stops, changing nothing, if duplicate source-backed journal entries
already exist.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "d9f1a2b3c4d5"
down_revision = "c8e1b4f7d203"
branch_labels = None
depends_on = None


BID = "nullif(current_setting('app.current_business_id', true), '')::integer"
JOURNAL_SOURCE_CONSTRAINT = "uq_journal_entries_biz_source"


def _has_table(name: str) -> bool:
    return name in set(inspect(op.get_bind()).get_table_names())


def _has_unique_key(table: str, columns: list[str]) -> bool:
    wanted = tuple(columns)
    inspector = inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints(table):
        if tuple(constraint.get("column_names") or ()) == wanted:
            return True
    for index in inspector.get_indexes(table):
        if index.get("unique") and tuple(index.get("column_names") or ()) == wanted:
            return True
    return False


def _ensure_journal_source_key() -> None:
    """Install the idempotency constraint without silently discarding history."""
    if not _has_table("journal_entries"):
        return
    columns = ["business_id", "source_type", "source_id"]
    if _has_unique_key("journal_entries", columns):
        return

    # SQL UNIQUE permits multiple NULL source_ids for manual/legacy entries.
    # Only source-backed rows must be unique; refuse migration rather than
    # choose one of two competing accounting entries to delete or rewrite.
    duplicate = op.get_bind().execute(text("""
        SELECT business_id, source_type, source_id, COUNT(*) AS n
        FROM journal_entries
        WHERE source_id IS NOT NULL
        GROUP BY business_id, source_type, source_id
        HAVING COUNT(*) > 1
        LIMIT 1
    """)).fetchone()
    if duplicate:
        raise RuntimeError(
            "Cannot add journal source idempotency constraint: duplicate "
            f"source-backed entries exist for business={duplicate[0]}, "
            f"source_type={duplicate[1]!r}, source_id={duplicate[2]}. "
            "Resolve the duplicate deliberately before retrying the migration."
        )

    with op.batch_alter_table("journal_entries", recreate="auto") as batch_op:
        batch_op.create_unique_constraint(JOURNAL_SOURCE_CONSTRAINT, columns)


def _ensure_document_sequence_rls() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql" or not _has_table("document_sequences"):
        return

    # FORCE matters: without it a table owner can bypass RLS, which defeats the
    # policy for the application's normal database role.
    op.execute("ALTER TABLE public.document_sequences ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE public.document_sequences FORCE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON public.document_sequences;")
    op.execute("DROP POLICY IF EXISTS document_sequences_tenant_isolation ON public.document_sequences;")
    op.execute(f"""
        CREATE POLICY document_sequences_tenant_isolation ON public.document_sequences
        USING (business_id = {BID})
        WITH CHECK (business_id = {BID});
    """)


def upgrade() -> None:
    _ensure_journal_source_key()
    _ensure_document_sequence_rls()


def downgrade() -> None:
    # Do not make a rollback less safe by reintroducing cross-tenant reads
    # or permitting duplicate journal postings.
    # Restoring historical behavior requires an explicit backup/restore plan.
    pass
