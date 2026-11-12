"""Retain versioned nonfinancial deletions across replay and device restores."""
from alembic import op

revision = "h6_sync_reliability"
down_revision = "h5_account_identity_bootstrap"
branch_labels = None
depends_on = None


def upgrade():
    from database.models import SyncTombstone, SyncDeviceNamespace
    SyncTombstone.__table__.create(op.get_bind(), checkfirst=True)
    SyncDeviceNamespace.__table__.create(op.get_bind(), checkfirst=True)
    from database.change_feed import install_change_feed
    install_change_feed(op.get_bind())
    # Retain historical deletes of rows that are still absent. Older event
    # payloads had no deletion time; use migration time rather than guessing an
    # earlier version that could admit a stale replay.
    import json
    from sqlalchemy import select
    from database.models import SyncFeedEvent
    from database.sync_map import MODEL_MAP, APPEND_ONLY_DELETE_BLOCKLIST
    from core.sync.tombstones import record_delete, get_tombstone, normalized_version
    from services.dates import utc_now
    connection = op.get_bind()
    events = connection.execute(select(SyncFeedEvent.__table__).where(
        SyncFeedEvent.operation == "DELETE").order_by(SyncFeedEvent.revision)).mappings()
    for event in events:
        entity, uid, bid = event["entity"], event["row_uid"], event["business_id"]
        model = MODEL_MAP.get(entity)
        if model is None or entity in APPEND_ONLY_DELETE_BLOCKLIST or not hasattr(model, "uid"):
            continue
        if connection.execute(select(model.id).where(model.uid == uid)).first() or get_tombstone(connection, bid, entity, uid):
            continue
        body = json.loads(event["payload"])
        record_delete(connection, bid, entity, uid, normalized_version(body.get("_sync_deleted_at")) or utc_now())
    from database.security import install_security
    install_security(op.get_bind())


def downgrade():
    # Retained deletion versions protect live records from stale resurrection.
    # Rolling back an app binary must not discard that history.
    pass
