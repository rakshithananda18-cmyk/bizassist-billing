"""add_user_is_premium  (premium/paid-tier gating)

Revision ID: ba1f7c3e9d20
Revises: a9c4e7f1d2b8
Create Date: 2026-07-05

ADDITIVE + REVERSIBLE. Adds a non-null ``is_premium`` boolean to ``users``
(default False / free tier). Cloud-sync nudges (the cloud↔local "sync now"
popups) and other paid capabilities are gated on this flag.

Defensive: skips the ADD if the column already exists — the runtime migrator
(``database/migration.py``) is the startup mechanism and may add it first; this
keeps Alembic in parity.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "ba1f7c3e9d20"
down_revision = "a9c4e7f1d2b8"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    return column in [c["name"] for c in inspect(bind).get_columns(table)]


def upgrade() -> None:
    if not _has_column("users", "is_premium"):
        op.add_column(
            "users",
            sa.Column("is_premium", sa.Boolean(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if _has_column("users", "is_premium"):
        op.drop_column("users", "is_premium")
