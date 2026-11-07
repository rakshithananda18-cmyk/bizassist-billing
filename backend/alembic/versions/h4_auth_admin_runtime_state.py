"""Durable auth, admin diagnostics, and cloud runtime state.

Additive tables: older Cloud Run revisions ignore them, so traffic rollback
requires no downgrade. Downgrade discards spent tickets, router settings and
support archives; redeploy the new revision to recover their features.
"""
from alembic import op
revision = "h4_auth_admin_runtime_state"
down_revision = "e70b5d2a4c06"
branch_labels = None
depends_on = None


def upgrade():
    from database.models import Base
    import database.runtime_state
    connection = op.get_bind()
    for name in ("spent_tickets", "revoked_sessions", "platform_settings", "client_log_archives", "schema_state", "scheduled_job_runs", "discovery_registrations"):
        Base.metadata.tables[name].create(connection, checkfirst=True)
    if connection.dialect.name == "postgresql":
        # An existing feed can be large. Build its anti-join index without
        # taking a write-blocking table lock during the release migration.
        with op.get_context().autocommit_block():
            op.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sync_feed_events_business_entity_row_uid ON sync_feed_events (business_id, entity, row_uid)')
    else:
        for index in Base.metadata.tables["sync_feed_events"].indexes:
            if index.name == "ix_sync_feed_events_business_entity_row_uid":
                index.create(connection, checkfirst=True)
    from database.security import install_security
    install_security(connection)


def downgrade():
    connection = op.get_bind()
    from database.models import Base
    if connection.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute('DROP INDEX CONCURRENTLY IF EXISTS ix_sync_feed_events_business_entity_row_uid')
    else:
        for index in Base.metadata.tables["sync_feed_events"].indexes:
            if index.name == "ix_sync_feed_events_business_entity_row_uid":
                index.drop(connection, checkfirst=True)
    for name in ("discovery_registrations", "scheduled_job_runs", "schema_state", "client_log_archives", "platform_settings", "revoked_sessions", "spent_tickets"):
        Base.metadata.tables[name].drop(connection, checkfirst=True)
