"""add_user_counter_prefix  (multi-terminal POS §9.3a)

Revision ID: b3c1d5e7f9a2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-28

ADDITIVE + REVERSIBLE. Adds a nullable ``counter_prefix`` column to ``users``.

Per-login POS counter prefix: the owner assigns each staff (and themselves, default
"OW") a prefix that drives that account's invoice-number series (C1-0001, C2-0001…)
so two logins never collide. Defense in depth — the runtime migrator
(``database/migration.py::_COLUMN_MIGRATIONS``) is the startup mechanism and adds
this same column; this Alembic rev keeps the two in parity (the project dual-maintains
both — see SESSION_HANDOFF §1).

Defensive: skips the ADD if the column already exists (the runtime migrator may have
added it first on a given DB).

APPLY: the startup migrator handles it automatically; for an Alembic-managed DB run
``alembic upgrade head`` (after ``alembic stamp`` past the baseline if needed).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b3c1d5e7f9a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in inspect(bind).get_columns(table)]
    return column in cols


def upgrade() -> None:
    if not _has_column("users", "counter_prefix"):
        op.add_column("users", sa.Column("counter_prefix", sa.String(), nullable=True))


def downgrade() -> None:
    if _has_column("users", "counter_prefix"):
        op.drop_column("users", "counter_prefix")
