"""add period close/lock log (period_locks)

Additive + backward-compatible: one brand-new append-only table. Nothing existing
is touched, so all current data and tests are unaffected. Holds the period
close/lock event log (lock/unlock events); the posting service rejects any
journal entry dated on/before the effective locked-through date.

IDEMPOTENT: because the app runs `Base.metadata.create_all()` at import, this
table may already exist before the migration runs. Every create is guarded by an
existence check, so it's safe on a fresh DB *and* on a create_all'd DB.

Revision ID: f2b9d4c1a8e3
Revises: e7a1c3f5b9d2
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "f2b9d4c1a8e3"
down_revision = "e7a1c3f5b9d2"
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
    if not _has_table("period_locks"):
        op.create_table(
            "period_locks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=True),
            sa.Column("locked_through", sa.String(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("note", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    _create_index_if_missing("ix_period_locks_id", "period_locks", ["id"])
    _create_index_if_missing("ix_period_locks_business_id", "period_locks", ["business_id"])
    _create_index_if_missing("ix_period_locks_biz", "period_locks", ["business_id", "id"])


def downgrade() -> None:
    if _has_table("period_locks"):
        op.drop_table("period_locks")
