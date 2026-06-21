"""add posted double-entry journal (journal_entries + journal_lines)

Additive + backward-compatible: two brand-new append-only tables only. Nothing
existing is touched, so all current data and tests are unaffected. These hold
the POSTED journal written at transaction time (the true audit trail).

IDEMPOTENT: because the app runs `Base.metadata.create_all()` at import, these
tables may already exist (created by create_all) before this migration runs.
So every create is guarded by an existence check — the migration only fills in
what's missing and then stamps the revision. Safe on a fresh DB *and* on a DB
where create_all already made the tables.

Revision ID: e7a1c3f5b9d2
Revises: d6f2b4a8e913
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "e7a1c3f5b9d2"
down_revision = "d6f2b4a8e913"
branch_labels = None
depends_on = None


def _inspector():
    return inspect(op.get_bind())


def _has_table(name: str) -> bool:
    return name in _inspector().get_table_names()


def _existing_indexes(table: str):
    try:
        return {ix["name"] for ix in _inspector().get_indexes(table)}
    except Exception:
        return set()


def _create_index_if_missing(name, table, cols):
    if name not in _existing_indexes(table):
        op.create_index(name, table, cols)


def upgrade() -> None:
    if not _has_table("journal_entries"):
        op.create_table(
            "journal_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("entry_date", sa.String(), nullable=False),
            sa.Column("source_type", sa.String(), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=True),
            sa.Column("ref_no", sa.String(), nullable=True),
            sa.Column("narration", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    _create_index_if_missing("ix_journal_entries_id", "journal_entries", ["id"])
    _create_index_if_missing("ix_journal_entries_business_id", "journal_entries", ["business_id"])
    _create_index_if_missing("ix_journal_entries_entry_date", "journal_entries", ["entry_date"])
    _create_index_if_missing("ix_journal_entries_source_type", "journal_entries", ["source_type"])
    _create_index_if_missing("ix_journal_entries_source_id", "journal_entries", ["source_id"])
    _create_index_if_missing("ix_journal_entries_source", "journal_entries",
                             ["business_id", "source_type", "source_id"])
    _create_index_if_missing("ix_journal_entries_biz_date", "journal_entries",
                             ["business_id", "entry_date"])

    if not _has_table("journal_lines"):
        op.create_table(
            "journal_lines",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id"), nullable=False),
            sa.Column("account", sa.String(), nullable=False),
            sa.Column("debit", sa.Float(), nullable=False, server_default="0"),
            sa.Column("credit", sa.Float(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    _create_index_if_missing("ix_journal_lines_id", "journal_lines", ["id"])
    _create_index_if_missing("ix_journal_lines_entry_id", "journal_lines", ["entry_id"])
    _create_index_if_missing("ix_journal_lines_account", "journal_lines", ["account"])


def downgrade() -> None:
    if _has_table("journal_lines"):
        op.drop_table("journal_lines")
    if _has_table("journal_entries"):
        op.drop_table("journal_entries")
