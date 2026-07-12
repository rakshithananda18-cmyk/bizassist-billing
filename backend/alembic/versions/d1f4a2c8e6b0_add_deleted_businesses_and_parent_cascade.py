"""add deleted_businesses tombstone + parent_business_id ON DELETE CASCADE

Revision ID: d1f4a2c8e6b0
Revises: c1e4f7a9b2d6
Create Date: 2026-07-12

ORPHAN-SAFETY (follows the July 2026 "phantom counters" incident).

Two additive, reversible changes:

  1. Create ``deleted_businesses`` — a tombstone table recording retired business
     accounts (admin wipe or reclaim re-key). No FKs, so it can't block a delete
     and it outlives the row it describes. Idempotent create.

  2. Give ``users.parent_business_id`` an ``ON DELETE CASCADE`` foreign key so a
     deleted owner can't strand its staff sub-accounts at the DB level. This is
     defence-in-depth; the application already deletes staff explicitly via the
     centralized ``purge_business_data``.

     Dialect-aware:
       • PostgreSQL (cloud) — DROP then re-ADD the FK with ON DELETE CASCADE.
         Effective immediately.
       • SQLite (local desktop) — SKIPPED. Rewriting the ``users`` table in place
         to change a constraint is a full table rebuild (risky on a live file),
         and SQLite only enforces FK actions when ``PRAGMA foreign_keys=ON`` is
         set per-connection anyway. Fresh SQLite installs pick up the cascade
         natively from the model DDL (``create_all``); existing local DBs keep
         relying on the app-level purge. No data change, no rebuild.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "d1f4a2c8e6b0"
down_revision = "c1e4f7a9b2d6"
branch_labels = None
depends_on = None

_FK_NAME = "fk_users_parent_business_id_users"  # from the shared naming convention


def _has_table(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _existing_parent_fk_name():
    """Return the actual FK constraint name on users.parent_business_id, or None."""
    insp = inspect(op.get_bind())
    for fk in insp.get_foreign_keys("users"):
        if "parent_business_id" in (fk.get("constrained_columns") or []):
            return fk.get("name")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Tombstone table (idempotent).
    if not _has_table("deleted_businesses"):
        op.create_table(
            "deleted_businesses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("public_id", sa.String(), nullable=True),
            sa.Column("username", sa.String(), nullable=True),
            sa.Column("business_name", sa.String(), nullable=True),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(), nullable=False,
                      server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_deleted_businesses_public_id", "deleted_businesses", ["public_id"])
        op.create_index("ix_deleted_businesses_username", "deleted_businesses", ["username"])

    # 2. parent_business_id ON DELETE CASCADE — PostgreSQL only.
    if dialect == "postgresql":
        existing = _existing_parent_fk_name()
        if existing:
            op.drop_constraint(existing, "users", type_="foreignkey")
        op.create_foreign_key(
            _FK_NAME, "users", "users",
            ["parent_business_id"], ["id"], ondelete="CASCADE",
        )
    # SQLite: intentionally skipped (see module docstring).


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        existing = _existing_parent_fk_name()
        if existing:
            op.drop_constraint(existing, "users", type_="foreignkey")
        op.create_foreign_key(
            _FK_NAME, "users", "users",
            ["parent_business_id"], ["id"],  # no cascade — original behaviour
        )

    if _has_table("deleted_businesses"):
        op.drop_index("ix_deleted_businesses_username", table_name="deleted_businesses")
        op.drop_index("ix_deleted_businesses_public_id", table_name="deleted_businesses")
        op.drop_table("deleted_businesses")
