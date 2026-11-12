"""Versioned deletes remain authoritative after the business row is gone."""
from datetime import datetime, timezone
from sqlalchemy import select


def normalized_version(value):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Invalid sync version timestamp") from None
    if not isinstance(value, datetime):
        raise ValueError("Sync version must be an ISO timestamp")
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def delete_version(record):
    return normalized_version(record.get("_sync_deleted_at") or record.get("deleted_at") or record.get("updated_at"))


def _table():
    from database.models import SyncTombstone
    return SyncTombstone.__table__


def get_tombstone(db, business_id, entity, uid):
    table = _table()
    return db.execute(select(table).where(
        table.c.business_id == business_id, table.c.entity == entity, table.c.row_uid == uid,
    )).mappings().first()


def check_upsert(db, business_id, entity, uid, incoming_updated_at):
    marker = get_tombstone(db, business_id, entity, uid)
    if marker is None:
        return True
    incoming = normalized_version(incoming_updated_at)
    return incoming is not None and incoming > normalized_version(marker["deleted_at"])


def record_delete(db, business_id, entity, uid, deleted_at, *, needs_upload=False):
    if not isinstance(uid, str) or not uid.strip():
        raise ValueError("Deletion requires a durable UID")
    version = normalized_version(deleted_at)
    if version is None:
        raise ValueError("Deletion requires version metadata. Update the device before retrying.")
    table = _table()
    values = dict(business_id=business_id, entity=entity, row_uid=uid,
                  deleted_at=version, needs_upload=needs_upload)
    bind = db.get_bind() if hasattr(db, "get_bind") else db
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise RuntimeError("Unsupported sync database")
    statement = insert(table).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.business_id, table.c.entity, table.c.row_uid],
        set_={"deleted_at": version, "needs_upload": needs_upload},
        where=table.c.deleted_at < version,
    )
    db.execute(statement)
    return get_tombstone(db, business_id, entity, uid)


def apply_remote_delete(db, business_id, entity, uid, deleted_at, existing=None):
    """Apply an accepted peer deletion without echoing a local trigger marker.

    The caller owns tenant/row locking and its savepoint. Compare the retained
    version before firing DELETE: a newer local pending delete must survive.
    A receive-time trigger stamp is not a new authored version, so replace that
    stamp with the peer's accepted version in this same transaction.
    """
    version = normalized_version(deleted_at)
    if version is None:
        raise ValueError("Deletion requires version metadata")
    previous = get_tombstone(db, business_id, entity, uid)
    if previous is not None and normalized_version(previous["deleted_at"]) > version:
        return False
    if existing is not None:
        # DELETE triggers take the feed-clock lock before the tombstone lock.
        # Keep that order here rather than locking the marker before DELETE.
        db.delete(existing)
        db.flush()
    retained = record_delete(db, business_id, entity, uid, version)
    if existing is None and normalized_version(retained["deleted_at"]) > version:
        return False
    table = _table()
    db.execute(table.update().where(
        table.c.business_id == business_id, table.c.entity == entity,
        table.c.row_uid == uid,
    ).values(deleted_at=version, needs_upload=False))
    return True


def lock_business(db, business_id):
    """Serialize sync decisions for one tenant, including first-time UID inserts."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text
        db.execute(text("SELECT pg_advisory_xact_lock(1398361667, :business_id)"),
                   {"business_id": int(business_id)})


def queue_pending_deletes(db, business_id):
    import json
    from database.models import SyncQueue, SyncTombstone, queue_row_if_absent
    pending = db.query(SyncQueue.entity, SyncQueue.payload).filter(SyncQueue.business_id == business_id,
        SyncQueue.operation == "DELETE", SyncQueue.synced_at.is_(None)).all()
    queued_uids = set()
    for entity, payload in pending:
        try:
            queued_uids.add((entity, json.loads(payload or "{}").get("uid")))
        except (ValueError, TypeError):
            pass
    count = 0
    for row in db.query(SyncTombstone).filter(SyncTombstone.business_id == business_id,
            SyncTombstone.needs_upload.is_(True)).limit(100).all():
        if (row.entity, row.row_uid) in queued_uids:
            continue
        queue_row_if_absent(db, business_id=business_id, entity=row.entity, entity_id=-row.id,
            operation="DELETE", payload=json.dumps({"uid": row.row_uid,
                "_sync_deleted_at": row.deleted_at.isoformat(), "updated_at": row.deleted_at.isoformat()}))
        count += 1
    if count:
        db.commit()
    return count


def acknowledge_delete(db, business_id, entity, payload):
    table = _table()
    version = delete_version(payload)
    if version and payload.get("uid"):
        db.execute(table.update().where(table.c.business_id == business_id,
            table.c.entity == entity, table.c.row_uid == payload["uid"],
            table.c.deleted_at <= version).values(needs_upload=False))
