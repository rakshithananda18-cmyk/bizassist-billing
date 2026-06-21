"""add tamper-evident hash chain to journal_entries (prev_hash, entry_hash)

Additive + backward-compatible: two nullable String columns on journal_entries.
Existing rows keep NULL hashes (they pre-date the chain); new posted entries are
chained going forward. Nothing existing is touched.

IDEMPOTENT: because the app runs `Base.metadata.create_all()` at import, the
columns may already exist before the migration runs, so each add is guarded by a
column-existence check.

Revision ID: a3c7e9b1d2f4
Revises: f2b9d4c1a8e3
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "a3c7e9b1d2f4"
down_revision = "f2b9d4c1a8e3"
branch_labels = None
depends_on = None


def _columns(table):
    try:
        return {c["name"] for c in inspect(op.get_bind()).get_columns(table)}
    except Exception:
        return set()


def _indexes(table):
    try:
        return {ix["name"] for ix in inspect(op.get_bind()).get_indexes(table)}
    except Exception:
        return set()


def upgrade() -> None:
    cols = _columns("journal_entries")
    if "prev_hash" not in cols:
        op.add_column("journal_entries", sa.Column("prev_hash", sa.String(), nullable=True))
    if "entry_hash" not in cols:
        op.add_column("journal_entries", sa.Column("entry_hash", sa.String(), nullable=True))
    if "ix_journal_entries_entry_hash" not in _indexes("journal_entries"):
        op.create_index("ix_journal_entries_entry_hash", "journal_entries", ["entry_hash"])


def downgrade() -> None:
    if "ix_journal_entries_entry_hash" in _indexes("journal_entries"):
        op.drop_index("ix_journal_entries_entry_hash", table_name="journal_entries")
    cols = _columns("journal_entries")
    if "entry_hash" in cols:
        op.drop_column("journal_entries", "entry_hash")
    if "prev_hash" in cols:
        op.drop_column("journal_entries", "prev_hash")
