"""add telemetry_events table (persistent telemetry store)

The JSONL telemetry files are ephemeral on the HF Space (container FS is wiped
on every restart). This table is the durable, queryable copy — Supabase
Postgres on the cloud, SQLite on local installs.

Revision ID: a9c4e7f1d2b8
Revises: f78e8836b7b1
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a9c4e7f1d2b8"
down_revision = "f78e8836b7b1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "telemetry_events" in insp.get_table_names():
        return  # already present (fresh DBs get it from Base.metadata.create_all)

    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("at", sa.String(), nullable=True),
        sa.Column("source", sa.String(40), nullable=False, server_default="unknown"),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("app_version", sa.String(20), nullable=True),
        sa.Column("platform", sa.String(20), nullable=True),
        sa.Column("bizid", sa.String(64), nullable=True),
        sa.Column("level", sa.String(10), nullable=False, server_default="info"),
        sa.Column("event", sa.String(80), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("relay_device", sa.String(64), nullable=True),
        sa.Column("relayed_at", sa.String(), nullable=True),
    )
    op.create_index("ix_telemetry_events_device_id", "telemetry_events", ["device_id"])
    op.create_index("ix_telemetry_events_bizid", "telemetry_events", ["bizid"])
    op.create_index("ix_telemetry_events_event", "telemetry_events", ["event"])
    op.create_index("ix_telemetry_bizid_received", "telemetry_events", ["bizid", "received_at"])
    op.create_index("ix_telemetry_received", "telemetry_events", ["received_at"])


def downgrade():
    op.drop_table("telemetry_events")
