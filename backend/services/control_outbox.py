"""
services/control_outbox.py
==========================
Durable outbox for control-plane events (staff changes, profile updates, tombstones)
that must reliably synchronize to the cloud even when the local device is offline,
tokens are not yet available, or the application restarts. (TS-05)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session
from database.models import SyncControlOutbox, utc_now
from pydantic import BaseModel, Field


class ControlEnvelope(BaseModel):
    event_id: Optional[str] = Field(default=None, max_length=64)
    source_id: Optional[str] = Field(default=None, max_length=128)
    source_revision: Optional[int] = Field(default=None, ge=1)
    business_public_id: Optional[str] = Field(default=None, max_length=64)

logger = logging.getLogger("bizassist.sync.control_outbox")

_IS_LOCAL = os.environ.get("DATABASE_URL", "sqlite").startswith("sqlite")


def is_hybrid_cloud(business_id: int) -> bool:
    """Return True if business is configured in hybrid (Local + Cloud) mode."""
    try:
        from services.immediate_sync import syncs_to_cloud
        return syncs_to_cloud(business_id)
    except Exception:
        return False


def enqueue_control_event(
    db: Session,
    business_id: int,
    event_type: str,
    payload: dict,
    event_id: Optional[str] = None,
) -> SyncControlOutbox:
    """
    Durably record a control-plane mutation into the SQLite outbox.
    Returns the created SyncControlOutbox row.
    """
    from sqlalchemy import text
    from database.models import User
    owner = db.get(User, business_id)
    if owner is None or not owner.public_id or (owner.role or "").lower() in {"deleted", "retired"}:
        raise ValueError("A control event requires a live business identity")
    db.flush()  # mutation and intent share the command's transaction
    conn = db.connection()
    conn.execute(text("INSERT INTO sync_control_origins(business_id,business_public_id,source_id,revision) VALUES(:b,:p,:s,0) ON CONFLICT(business_id) DO NOTHING"),
                 {"b": business_id, "p": owner.public_id, "s": "device:" + uuid.uuid4().hex})
    origin = conn.execute(text("SELECT business_public_id FROM sync_control_origins WHERE business_id=:b"), {"b": business_id}).scalar()
    if origin != owner.public_id:
        purge_control_state(db, business_id)
        conn.execute(text("INSERT INTO sync_control_origins(business_id,business_public_id,source_id,revision) VALUES(:b,:p,:s,0)"),
                     {"b": business_id, "p": owner.public_id, "s": "device:" + uuid.uuid4().hex})
    row_info = conn.execute(text("UPDATE sync_control_origins SET revision=revision+1 WHERE business_id=:b RETURNING source_id,revision"), {"b": business_id}).first()
    row = SyncControlOutbox(business_id=business_id, business_public_id=owner.public_id,
        source_id=row_info[0], source_revision=row_info[1], event_type=event_type,
        event_id=event_id or uuid.uuid4().hex, payload=json.dumps(payload), status="pending", attempts=0, created_at=utc_now())
    db.add(row)
    db.flush()
    return row


def flush_control_outbox(db: Session, business_id: int) -> dict:
    """
    Attempt to deliver all pending control-plane events for `business_id`.
    Returns summary stats {"attempted": int, "completed": int, "failed": int}.
    """
    from sqlalchemy import or_, update
    from database.models import User
    if not _IS_LOCAL or not is_hybrid_cloud(business_id):
        return {"attempted": 0, "completed": 0, "failed": 0}
    from services.sync_worker import _get_cloud_token, CLOUD_URL
    from services import sync_retry
    from services.process_lock import acquire_sync_process_lease
    if not acquire_sync_process_lease() or not sync_retry.ready(business_id, "control"):
        return {"attempted": 0, "completed": 0, "failed": 0}
    import httpx
    summary = {"attempted": 0, "completed": 0, "failed": 0}
    for _ in range(20):
        if not is_hybrid_cloud(business_id):
            break
        # Never skip a predecessor in backoff. The receiver also checks a
        # contiguous per-device revision, so response loss cannot reorder writes.
        ev = db.query(SyncControlOutbox).filter(SyncControlOutbox.business_id == business_id,
            SyncControlOutbox.status == "pending").order_by(SyncControlOutbox.id).first()
        if ev is None:
            break
        now = utc_now()
        if ev.next_attempt_at and ev.next_attempt_at > now:
            break
        owner = db.get(User, business_id)
        if owner is None or (owner.role or "").lower() in {"deleted", "retired"} or not ev.business_public_id or owner.public_id != ev.business_public_id:
            ev.status = "cancelled"
            ev.error = "Retired or unverifiable business identity; event not sent"
            db.commit()
            continue
        lease = uuid.uuid4().hex
        claimed = db.execute(update(SyncControlOutbox).where(SyncControlOutbox.id == ev.id,
            SyncControlOutbox.status == "pending", or_(SyncControlOutbox.lease_until.is_(None), SyncControlOutbox.lease_until <= now))
            .values(lease_id=lease, lease_until=now + timedelta(seconds=60))).rowcount
        db.commit()
        if not claimed:
            break
        db.refresh(ev)
        summary["attempted"] += 1
        try:
            token = _get_cloud_token(business_id)
            if not token:
                raise RuntimeError("No cloud token; sign in to resume")
            req_json = json.loads(ev.payload)
            req_json.update(event_id=ev.event_id, source_id=ev.source_id,
                source_revision=ev.source_revision, business_public_id=ev.business_public_id)
            route = {"staff_mutation": "staff-push", "profile_update": "profile-push"}.get(ev.event_type)
            if route is None:
                raise RuntimeError("Unsupported control event")
            if not is_hybrid_cloud(business_id):
                ev.lease_id = ev.lease_until = None
                db.commit()
                break
            resp = httpx.post(f"{CLOUD_URL}/api/sync/{route}", json=req_json,
                headers={"Authorization": f"Bearer {token}"}, timeout=8.0)
            if resp.status_code != 200:
                sync_retry.defer(business_id, "control", resp)
                if resp.status_code == 401:
                    from services.sync_worker import _invalidate_cloud_token
                    _invalidate_cloud_token(business_id, expected_token=token)
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:150]}")
            sync_retry.success(business_id, "control")
            db.refresh(ev)
            if ev.lease_id != lease:
                break
            ev.status, ev.completed_at, ev.error = "completed", utc_now(), None
            ev.lease_id = ev.lease_until = None
            db.commit()
            summary["completed"] += 1
        except Exception as exc:
            if sync_retry.ready(business_id, "control"):
                sync_retry.defer(business_id, "control", reason=type(exc).__name__)
            db.rollback()
            ev = db.get(SyncControlOutbox, ev.id)
            if ev and ev.lease_id == lease:
                ev.attempts += 1
                ev.last_attempt_at = utc_now()
                ev.next_attempt_at = utc_now() + timedelta(seconds=min(300, 5 * 2 ** min(ev.attempts, 6)))
                ev.error = str(exc)[:400]
                ev.lease_id = ev.lease_until = None
                db.commit()
            summary["failed"] += 1
            break
    return summary


def purge_control_state(db, business_id):
    """Called inside purge/rekey's transaction; old intents must never migrate."""
    from database.models import SyncControlOrigin, SyncControlReceipt, SyncControlStream
    for model in (SyncControlOutbox, SyncControlOrigin, SyncControlReceipt, SyncControlStream):
        db.query(model).filter(model.business_id == business_id).delete(synchronize_session=False)


def control_status(db, business_id):
    from sqlalchemy import func
    rows = db.query(SyncControlOutbox.status, func.count()).filter(SyncControlOutbox.business_id == business_id).group_by(SyncControlOutbox.status).all()
    counts = dict(rows)
    failed = db.query(SyncControlOutbox).filter(SyncControlOutbox.business_id == business_id,
        SyncControlOutbox.status == "pending", SyncControlOutbox.attempts > 0).count()
    last_error = db.query(SyncControlOutbox.error).filter(SyncControlOutbox.business_id == business_id,
        SyncControlOutbox.error.isnot(None)).order_by(SyncControlOutbox.id.desc()).first()
    return {"pending": counts.get("pending", 0), "failed": failed + counts.get("failed", 0),
            "cancelled": counts.get("cancelled", 0), "last_error": last_error[0] if last_error else None}


def receive_control_event(db, business_id, req):
    """Lock the receiver stream and acknowledge retries in the mutation txn."""
    from fastapi import HTTPException
    from sqlalchemy import text
    from database.models import User, SyncControlReceipt, SyncControlStream
    owner = db.get(User, business_id)
    if not req.event_id or not req.source_id or req.source_revision is None:
        raise HTTPException(426, "Update this device for durable control synchronization")
    if owner is None or owner.public_id != req.business_public_id or (owner.role or "").lower() in {"deleted", "retired"}:
        raise HTTPException(409, "Control event belongs to a retired business identity")
    db.execute(text("INSERT INTO sync_control_streams(business_id,source_id,revision) VALUES(:b,:s,0) ON CONFLICT(business_id,source_id) DO NOTHING"), {"b": business_id, "s": req.source_id})
    stream = db.query(SyncControlStream).filter_by(business_id=business_id, source_id=req.source_id).with_for_update().one()
    receipt = db.query(SyncControlReceipt).filter_by(business_id=business_id, event_id=req.event_id).first()
    if receipt:
        if receipt.source_id != req.source_id or receipt.source_revision != req.source_revision:
            raise HTTPException(409, "Control event identity was reused")
        return False
    if req.source_revision != stream.revision + 1:
        raise HTTPException(409, "Control predecessor has not been acknowledged or this event is stale")
    stream.revision = req.source_revision
    db.add(SyncControlReceipt(business_id=business_id, event_id=req.event_id,
        source_id=req.source_id, source_revision=req.source_revision))
    return True


def trigger_control_flush(business_id: int) -> None:
    """Trigger an async flush of pending control events in a background thread."""
    if not _IS_LOCAL or not is_hybrid_cloud(business_id):
        return

    def _worker():
        try:
            from database.db import SessionLocal
            db = SessionLocal()
            try:
                flush_control_outbox(db, business_id)
            finally:
                db.close()
        except Exception as e:
            logger.warning("[CONTROL-OUTBOX] trigger_control_flush worker error: %s", e)

    threading.Thread(target=_worker, daemon=True).start()
