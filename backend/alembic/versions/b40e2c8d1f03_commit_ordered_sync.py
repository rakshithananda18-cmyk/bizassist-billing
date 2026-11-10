"""Commit-ordered feed, identity-bound control intents and constrained-role bootstrap.

Revision ID: b40e2c8d1f03
Revises: a30f1d7b9c02
"""
from alembic import op
import sqlalchemy as sa

revision = "b40e2c8d1f03"
down_revision = "a30f1d7b9c02"
branch_labels = None
depends_on = None


def upgrade():
    from database.models import (SyncControlOutbox, SyncControlOrigin, SyncControlStream,
        SyncControlReceipt, SyncFeedClock, SyncFeedEvent)
    connection = op.get_bind()
    # Anonymous bootstrap functions reference these owner fields. Older fresh
    # Alembic schemas received them only from startup's additive column map;
    # install their declarations before PostgreSQL validates the SQL functions.
    from database.migration import _COLUMN_MIGRATIONS, _portable_ddl
    for change in _COLUMN_MIGRATIONS:
        if change["table"] == "users" and change["column"] not in {
            column["name"] for column in sa.inspect(connection).get_columns("users")
        }:
            connection.execute(sa.text(_portable_ddl(change["ddl"], connection.dialect.name)))
    for model in (SyncControlOutbox, SyncControlOrigin, SyncControlStream, SyncControlReceipt, SyncFeedClock, SyncFeedEvent):
        model.__table__.create(connection, checkfirst=True)
    columns = {c["name"] for c in sa.inspect(connection).get_columns("sync_control_outbox")}
    for name, kind in (("business_public_id", sa.String()), ("source_id", sa.String()),
                       ("source_revision", sa.Integer()), ("lease_id", sa.String()), ("lease_until", sa.DateTime())):
        if name not in columns:
            op.add_column("sync_control_outbox", sa.Column(name, kind, nullable=True))
    # Old intents have no provable tenant generation/revision. Preserve a visible
    # cancelled record; never guess its identity after a rekey or migration.
    op.execute("UPDATE sync_control_outbox SET status='cancelled', error='Legacy intent has no verifiable identity; review and retry the current mutation' WHERE business_public_id IS NULL")
    from database.change_feed import install_change_feed
    install_change_feed(connection)
    from database.security import install_security
    install_security(connection)


def downgrade():
    # Downgrading must not erase acknowledged mutations or re-enable unsafe
    # timestamp clients. Roll back application binaries with protocol negotiation.
    pass
