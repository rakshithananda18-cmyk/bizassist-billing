"""add idempotency_keys (HTTP-level exactly-once replay guard, R7b Slice 1)

Additive + backward-compatible: one NEW table, no change to any existing table.
Stores the response of a mutating request keyed by (business_id,
client_request_id) so an offline outbox replay / network retry gets the SAME
response back instead of double-posting. See core.models.IdempotencyKey and
core.sync.idempotency.ReplayGuard.

IDEMPOTENT: `Base.metadata.create_all()` at import may already have created the
table (tests run on a fresh SQLite via create_all), so the create is guarded by
a has_table check.

Revision ID: f4a1c7e9b2d6
Revises: b5d8f2a6c3e1
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "f4a1c7e9b2d6"
down_revision = "b5d8f2a6c3e1"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    insp = inspect(op.get_bind())
    try:
        return insp.has_table(table)
    except Exception:
        return False


def upgrade() -> None:
    if _has_table("idempotency_keys"):
        return
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("business_id", sa.Integer(), nullable=False, index=True),
        sa.Column("client_request_id", sa.String(), nullable=False, index=True),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("path", sa.String(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("business_id", "client_request_id", name="uq_idempotency_biz_key"),
    )
    op.create_index(
        "ix_idempotency_biz_key", "idempotency_keys",
        ["business_id", "client_request_id"],
    )


def downgrade() -> None:
    if _has_table("idempotency_keys"):
        op.drop_index("ix_idempotency_biz_key", table_name="idempotency_keys")
        op.drop_table("idempotency_keys")
