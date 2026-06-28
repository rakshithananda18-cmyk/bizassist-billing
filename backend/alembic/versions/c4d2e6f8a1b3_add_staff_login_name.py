"""add_staff_login_name  (multi-tenant staff §9.5)

Revision ID: c4d2e6f8a1b3
Revises: b3c1d5e7f9a2
Create Date: 2026-06-28

ADDITIVE + REVERSIBLE. Adds nullable ``staff_login_name`` to ``users`` — the
per-business display/login name for a staff sub-account (the bare "counter_1"),
unique only within the owner's business. The global-unique ``username`` is
auto-derived for new staff; staff log in via owner → counter, never by username.

Backfill: existing staff (``parent_business_id IS NOT NULL``) keep working — set
``staff_login_name = username`` so the new owner-scoped staff login resolves them.

Defensive: skips the ADD if the column already exists (runtime migrator may have
added it first). The runtime migrator (``database/migration.py``) is the startup
mechanism; this keeps Alembic in parity.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "c4d2e6f8a1b3"
down_revision = "b3c1d5e7f9a2"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    return column in [c["name"] for c in inspect(bind).get_columns(table)]


def upgrade() -> None:
    if not _has_column("users", "staff_login_name"):
        op.add_column("users", sa.Column("staff_login_name", sa.String(), nullable=True))
    # Backfill existing staff so the owner-scoped login keeps finding them.
    op.get_bind().execute(text(
        "UPDATE users SET staff_login_name = username "
        "WHERE parent_business_id IS NOT NULL AND staff_login_name IS NULL"
    ))


def downgrade() -> None:
    if _has_column("users", "staff_login_name"):
        op.drop_column("users", "staff_login_name")
