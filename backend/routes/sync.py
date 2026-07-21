"""
routes/sync.py
==============
Phase 2 – Synchronization endpoints.

Exposes:
  - POST /api/sync/push        (Cloud) Receive local mutations, apply LWW, log conflicts
  - GET  /api/sync/pull        (Cloud) Fetch changes since last_sync_at
  - GET  /api/sync/queue-depth (Local) Query count of unsynced items
  - POST /api/sync/flush       (Local) Trigger immediate outbox sync flush
"""

from services.dates import utc_now
import logging
import json
from datetime import datetime, timezone
from typing import Any, Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import text, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database.db import get_db, sync_disabled_var
from services.auth import get_active_user, require_plan
from database.models import (
    Base, User, Customer, Vendor, Product, Invoice, InvoiceLineItem,
    Inventory, LegacyPayment, ConflictLog, SyncLog, SyncQueue,
    StockLedger, ProductBarcode, BusinessSettings, InvoicePayment,
    B2BLedger, Expense, Godown, StockTransfer, StockTransferLineItem,
    PurchaseInvoice, PurchaseInvoiceLineItem, PurchaseOrder, PurchaseOrderLineItem,
    AlertConfig, RateLimitConfig
)

router = APIRouter()
logger = logging.getLogger("bizassist.routes.sync")

# (R-7) Single shared source — see database/sync_map.py
from database.sync_map import (
    MODEL_MAP as _MODEL_MAP,
    ENTITY_BROADCAST_MAP,
    resolve_parent_fk_uids,
    _USER_FK_REPOINT_ENTITIES,
)


APPEND_ONLY_DELETE_BLOCKLIST = frozenset({
    # Money/audit documents and their lines.
    "invoices",
    "invoice_line_items",
    "payments",
    "invoice_payments",
    "purchase_invoices",
    "purchase_invoice_line_items",
    "purchase_orders",
    "purchase_order_line_items",
    "expenses",
    # Stock/accounting ledgers are historical truth, not mutable state.
    "stock_ledger",
    "b2b_ledgers",
})


# Entities where a conflicting concurrent edit must never be resolved SILENTLY.
# For these, whenever an incoming push OVERWRITES an existing row with a
# different-timestamped local version, we record a ConflictLog(review_needed)
# capturing both sides so the owner can see it — instead of the historical
# behaviour where the "local won" branch clobbered the cloud row with no trace
# (the silent-lost-edit failure mode, review P0). Resolution behaviour is
# UNCHANGED (LWW still lands the data); we only remove the silence.
FINANCIAL_ENTITIES = frozenset({
    "invoices",
    "invoice_line_items",
    "payments",
    "invoice_payments",
    "purchase_invoices",
    "purchase_invoice_line_items",
    "purchase_orders",
    "purchase_order_line_items",
    "expenses",
    "stock_ledger",
    "b2b_ledgers",
})


# ---------------------------------------------------------------------------
# PYDANTIC SCHEMAS
# ---------------------------------------------------------------------------

class SyncChange(BaseModel):
    entity: str
    entity_id: int
    operation: str
    payload: Optional[Dict[str, Any]] = None
    created_at: str


class PushPayload(BaseModel):
    changes: List[SyncChange]


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    """Serialize a row/ORM object to plain dict, stripping internal SA state."""
    if hasattr(row, "__dict__"):
        d = {k: v for k, v in row.__dict__.items() if k != "_sa_instance_state"}
    else:
        d = dict(row._mapping)
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def _safe_json_load(s: Any):
    """Parse a stored JSON payload back to an object for the API; return the raw
    value (or None) if it isn't valid JSON."""
    if not s:
        return None
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return s


def _payloads_differ(incoming: dict, existing: dict) -> bool:
    """True when the incoming push carries a MEANINGFUL change vs the current
    row — compared only on the keys the push actually sends, and ignoring
    bookkeeping columns that always differ (timestamps, sync cursors) so we
    don't flag a no-op re-sync as a conflict. Values compared as strings so
    123 == "123" across the SQLite↔Postgres boundary."""
    ignore = {"updated_at", "created_at", "synced_at", "last_synced_at",
              "sync_status", "id", "_sa_instance_state"}
    for k, v in incoming.items():
        if k in ignore:
            continue
        if k not in existing:
            continue
        if str(existing.get(k)) != str(v):
            return True
    return False


def _parse_dt(dt_str: Any) -> Optional[datetime]:
    if not dt_str:
        return None
    if isinstance(dt_str, datetime):
        return dt_str
    try:
        clean_str = str(dt_str).replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str)
    except Exception:
        return None


def _resolve_business_id_by_username(user: dict, db: Session) -> int:
    """
    Resolve the ACTUAL business_id (owner's id) in THIS DB for the token's user.

    Cross-DB tokens carry ids that differ between local and cloud, so we match on
    the most stable key first (D9):
      1. BizID (public_id) **confirmed by username** — the identity spine. We
         require username to agree because BizID is minted per-DB and not yet
         globally unique; a chance collision with a different business must not
         mis-route. The username confirmation removes that risk.
      2. username — fallback for older tokens / first sync.
      3. JWT id — same-DB fallback.
    A staff member resolves to their parent (owner) business id.
    """
    username = user.get("username") or user.get("sub") or ""
    public_id = user.get("public_id")
    if public_id and username:
        try:
            row = db.execute(
                text('SELECT id, parent_business_id FROM "users" WHERE public_id = :p AND username = :u'),
                {"p": public_id, "u": username},
            ).first()
            if row:
                return int(row[1]) if row[1] is not None else int(row[0])

            # STAFF FIX (2026-07): staff tokens carry the OWNER's BizID with the
            # STAFF member's username — when the staff row was never mirrored to
            # this DB (or was mirrored under a different derived username), the
            # pair-lookup above misses even though the business itself is
            # unambiguous. The BizID is the identity spine: if an OWNER row with
            # this public_id exists, route to that business directly. This ends
            # the "BizID mismatch for username 'counter_1'" refusal loop where a
            # DIFFERENT business's staff happened to share the generic username.
            owner_row = db.execute(
                text('SELECT id FROM "users" WHERE public_id = :p AND parent_business_id IS NULL'),
                {"p": public_id},
            ).first()
            if owner_row:
                logger.info(
                    "sync: resolved business by owner BizID %s for staff '%s' "
                    "(staff row not mirrored on this DB — consider re-running staff sync)",
                    public_id, username,
                )
                return int(owner_row[0])

            # IDENTITY GUARD: the token carries a BizID but this DB has no user
            # with that BizID at all. Falling through to the username-only
            # match could write one business's data into a DIFFERENT business
            # that happens to share the username (e.g. independently-created
            # local & cloud accounts). Refuse instead — the user must link
            # accounts (fresh-device login mirrors the cloud BizID) first.
            same_name = db.execute(
                text('SELECT public_id FROM "users" WHERE username = :u'),
                {"u": username},
            ).first()
            if same_name and same_name[0] and str(same_name[0]) != str(public_id):
                logger.warning(
                    "sync: BizID mismatch for username '%s' (token=%s, db=%s) — refusing cross-business sync",
                    username, public_id, same_name[0],
                )
                raise HTTPException(
                    status_code=403,
                    detail="BizID mismatch: this account is a different business on this server. "
                           "Re-link the device (log out and back in while online) before syncing.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.debug("_resolve_business_id: public_id lookup failed — %s", exc)

    if username:
        try:
            row = db.execute(
                text('SELECT id, parent_business_id FROM "users" WHERE username = :u'),
                {"u": username},
            ).first()
            if row:
                return int(row[1]) if row[1] is not None else int(row[0])
        except Exception as exc:
            logger.debug("_resolve_business_id: username lookup failed — %s", exc)

    # Fallback: use JWT ID
    return int(user.get("parent_business_id") or user.get("id"))


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

class CloudTokenBody(BaseModel):
    token: str


@router.post("/api/sync/cloud-token")
def save_cloud_token(
    body: CloudTokenBody,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """
    (Local) Store a CLOUD-issued sync token for this business.

    Standard device provisioning: at owner login the frontend authenticates
    against the cloud once and hands the resulting 24 h business-scoped JWT
    here. The sync worker uses it for pushes — replacing the shared-JWT_SECRET
    requirement (a leaked token exposes one business for ≤24 h, not every install).
    """
    from services.sync_worker import store_cloud_token
    business_id = _resolve_business_id_by_username(current_user, db)
    store_cloud_token(business_id, body.token)
    return {"status": "ok"}


@router.post("/api/sync/push")
def push_changes(
    payload: PushPayload,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    _plan: dict = Depends(require_plan("pro")),   # 402 for free plan when SUBSCRIPTION_ENFORCED=1
    db: Session = Depends(get_db),
):
    """
    Cloud Endpoint. Receives local changes and applies them to PostgreSQL.
    Enforces multi-tenant scoping and applies Last-Write-Wins (LWW) resolution.
    """
    business_id = _resolve_business_id_by_username(current_user, db)
    logger.info("sync/push: business_id=%s received %s changes", business_id, len(payload.changes))

    blocked_delete_entities = sorted({
        change.entity
        for change in payload.changes
        if change.operation.upper() == "DELETE" and change.entity in APPEND_ONLY_DELETE_BLOCKLIST
    })
    if blocked_delete_entities:
        logger.warning(
            "sync/push: rejected append-only delete(s) for biz=%s entities=%s",
            business_id,
            blocked_delete_entities,
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "DELETE is not allowed for append-only financial entities: "
                + ", ".join(blocked_delete_entities)
            ),
        )

    # Temporarily disable trigger hooks to prevent queuing writes back on the cloud
    token = sync_disabled_var.set(True)
    processed_count = 0
    entities_to_broadcast = set()

    entity_map = ENTITY_BROADCAST_MAP

    try:
        for change in payload.changes:
            model_cls = _MODEL_MAP.get(change.entity)
            if not model_cls:
                logger.warning("sync/push: unknown entity %s", change.entity)
                continue

            data = change.payload or {}
            if "business_id" in data:
                data["business_id"] = business_id

            # register_shifts and shift_cash_movements carry a user_id FK to
            # `users` (which is NOT a synced table), so the SOURCE db's integer
            # user_id won't exist in THIS db and the insert would fail its FK
            # (NOT NULL, so it can't just be dropped). Re-point it at the resolved
            # owner (business_id) so the row lands instead of crashing. Both are
            # business-scoped; owner attribution is sufficient here.
            if change.entity in _USER_FK_REPOINT_ENTITIES and "user_id" in data:
                data["user_id"] = business_id

            existing = None
            uid_val = data.get("uid")

            # (Phase C) Prefer uid lookup for synced models, but support legacy
            # local updates when an id-only payload is received.
            if hasattr(model_cls, "uid"):
                if uid_val:
                    existing = db.query(model_cls).filter(model_cls.uid == uid_val).first()
                elif data.get("id") is not None:
                    existing = db.query(model_cls).filter(model_cls.id == change.entity_id).first()
                    if existing is None:
                        logger.warning(
                            "sync/push: payload without uid for %s will be applied as insert or id-fallback if matched",
                            change.entity,
                        )
                if "id" in data:
                    del data["id"]
            else:
                existing = db.query(model_cls).filter(model_cls.id == change.entity_id).first()

            # Scope check the existing record
            if existing:
                # Check tenant ownership
                existing_bid = getattr(existing, "business_id", None)
                if change.entity == "users":
                    if existing.id != business_id and existing.parent_business_id != business_id:
                        logger.warning("sync/push: tenant mismatch for users.id=%s", change.entity_id)
                        continue
                elif existing_bid is not None and int(existing_bid) != business_id:
                    logger.warning("sync/push: tenant mismatch for %s.id=%s", change.entity, change.entity_id)
                    continue

            if change.operation == "DELETE":
                if existing:
                    db.delete(existing)
                    processed_count += 1
                    ent_name = entity_map.get(change.entity)
                    if ent_name:
                        entities_to_broadcast.add(ent_name)
                continue

            # INSERT / UPDATE operations
            # Conflict Check: compare updated_at timestamps if available
            local_updated_at_str = data.get("updated_at")
            local_updated_at = _parse_dt(local_updated_at_str)

            if existing and hasattr(existing, "updated_at") and existing.updated_at:
                cloud_updated_at = _parse_dt(existing.updated_at)
                # (R-5) An incoming change with no updated_at cannot be proven
                # newer — keep the existing cloud row rather than blindly clobber.
                if not local_updated_at:
                    logger.warning(
                        "sync/push: %s.id=%s has no updated_at — keeping cloud version (cannot resolve LWW)",
                        change.entity, change.entity_id,
                    )
                    continue
                if cloud_updated_at and local_updated_at < cloud_updated_at:
                    # LWW conflict: cloud version is newer, discard change and log
                    conflict = ConflictLog(
                        business_id=business_id,
                        entity=change.entity,
                        entity_id=change.entity_id,
                        local_updated_at=local_updated_at,
                        cloud_updated_at=cloud_updated_at,
                        local_payload=json.dumps(data, default=str),
                        cloud_payload=json.dumps(_row_to_dict(existing), default=str),
                        resolved_at=utc_now(),
                        resolution="cloud_won"
                    )
                    db.add(conflict)
                    logger.info("sync/push: LWW conflict resolved (cloud won) for %s.id=%s", change.entity, change.entity_id)
                    continue

                # (P0) Local-wins on a FINANCIAL row = the previously-SILENT
                # overwrite. Data still lands (LWW below), but a financial record
                # being edited on two devices is something the owner must see, so
                # log a review_needed conflict capturing the cloud version BEFORE
                # we clobber it. Guarded to a genuine change (differing timestamp
                # and differing content) so normal edit→sync propagation of an
                # unchanged row doesn't spam the review list.
                if (change.entity in FINANCIAL_ENTITIES
                        and cloud_updated_at and local_updated_at > cloud_updated_at):
                    cloud_snapshot = _row_to_dict(existing)
                    if _payloads_differ(data, cloud_snapshot):
                        db.add(ConflictLog(
                            business_id=business_id,
                            entity=change.entity,
                            entity_id=change.entity_id,
                            local_updated_at=local_updated_at,
                            cloud_updated_at=cloud_updated_at,
                            local_payload=json.dumps(data, default=str),
                            cloud_payload=json.dumps(cloud_snapshot, default=str),
                            resolved_at=None,               # unreviewed
                            resolution="review_needed",
                        ))
                        logger.warning(
                            "sync/push: financial overwrite flagged for review — %s.id=%s "
                            "(local %s > cloud %s)",
                            change.entity, change.entity_id, local_updated_at, cloud_updated_at,
                        )

            # Resolve FKs via the parent's durable uid (shared helper — same logic
            # as the pull-apply worker). If a parent_uid is present but the parent
            # row isn't in this DB yet, the child is DEFERRED rather than written
            # with the source-DB integer id (wrong-row / orphan); it re-applies on
            # a later sync once the parent exists.
            if resolve_parent_fk_uids(db, model_cls, data, log_prefix=f"sync/push[{change.entity}.id={change.entity_id}]"):
                continue

            # Apply fields to model instance
            target_obj = existing if existing else model_cls()

            for key, val in data.items():
                if key in model_cls.__table__.columns:
                    col_type = model_cls.__table__.columns[key].type
                    # Handle datetime conversions
                    if hasattr(col_type, "python_type") and col_type.python_type == datetime:
                        if val:
                            val = _parse_dt(val)
                    setattr(target_obj, key, val)

            # Per-row SAVEPOINT: one bad row (e.g. a duplicate uid whose data is
            # already on the cloud, or a transient FK) must NOT abort the whole
            # batch and stall the outbox forever (the "N pending" loop). We roll
            # back just that row and keep going. A duplicate/integrity row is
            # ACKed (counted processed) so the client stops re-sending it — its
            # data is already present on the destination.
            try:
                with db.begin_nested():
                    if not existing:
                        db.add(target_obj)
                    db.flush()
                processed_count += 1
                ent_name = entity_map.get(change.entity)
                if ent_name:
                    entities_to_broadcast.add(ent_name)
            except IntegrityError as ie:
                # Most likely a concurrent insert of the same uid (two overlapping
                # pushes) — the row now EXISTS. Re-fetch by uid and UPDATE it
                # (merge) so the change actually lands instead of being dropped,
                # respecting LWW (only overwrite when the incoming row is newer).
                deduped = "skipped"
                try:
                    if uid_val and hasattr(model_cls, "uid"):
                        dup = db.query(model_cls).filter(model_cls.uid == uid_val).first()
                        if dup is not None:
                            inc_dt = _parse_dt(data.get("updated_at"))
                            cur_dt = _parse_dt(getattr(dup, "updated_at", None)) if hasattr(dup, "updated_at") else None
                            if (inc_dt is None) or (cur_dt is None) or (inc_dt >= cur_dt):
                                with db.begin_nested():
                                    for key, val in data.items():
                                        if key in model_cls.__table__.columns and key != "id":
                                            col_type = model_cls.__table__.columns[key].type
                                            if hasattr(col_type, "python_type") and col_type.python_type == datetime and val:
                                                val = _parse_dt(val)
                                            setattr(dup, key, val)
                                    db.flush()
                                deduped = "updated"
                            else:
                                deduped = "kept-newer-cloud"
                except Exception as ie2:
                    logger.warning("sync/push: dedupe-update failed for %s uid=%s: %s", change.entity, uid_val, ie2)
                logger.info(
                    "sync/push: %s.id=%s integrity-deduped by uid (%s): %s",
                    change.entity, change.entity_id, deduped, getattr(ie, "orig", ie),
                )
                processed_count += 1  # ack either way so it isn't re-sent every cycle
                continue

        db.commit()

        # Broadcast sync triggers to SSE connections in background
        from services.realtime import realtime_manager
        for ent in entities_to_broadcast:
            background_tasks.add_task(realtime_manager.broadcast, business_id, {"type": "sync.trigger", "entity": ent})

    except Exception as e:
        db.rollback()
        logger.error("sync/push: fatal error — %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Sync push failed: {e}")
    finally:
        sync_disabled_var.reset(token)

    return {"status": "success", "applied": processed_count}


@router.get("/api/sync/pull")
def pull_changes(
    last_sync_at: Optional[str] = None,
    current_user: dict = Depends(get_active_user),
    _plan: dict = Depends(require_plan("pro")),   # 402 for free plan when SUBSCRIPTION_ENFORCED=1
    db: Session = Depends(get_db),
):
    """
    Cloud Endpoint. Returns updates scoped to user's business_id that
    occurred after `last_sync_at`.
    """
    business_id = _resolve_business_id_by_username(current_user, db)
    last_sync_dt = _parse_dt(last_sync_at) or datetime(1970, 1, 1)

    changes: Dict[str, List[dict]] = {}

    for table_name, model_cls in _MODEL_MAP.items():
        try:
            cols = {c.name for c in model_cls.__table__.columns}
            query = db.query(model_cls)

            # Apply tenant isolation
            if table_name == "users":
                query = query.filter((model_cls.id == business_id) | (model_cls.parent_business_id == business_id))
            elif "business_id" in cols:
                query = query.filter(model_cls.business_id == business_id)
            else:
                continue

            # Apply updated_at filter if present
            if "updated_at" in cols:
                query = query.filter(model_cls.updated_at > last_sync_dt)

            rows = query.all()
            if rows:
                changes[table_name] = [_row_to_dict(r) for r in rows]

        except Exception as e:
            logger.warning("sync/pull: failed querying table %s — %s", table_name, e)

    return {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "changes": changes,
    }


@router.get("/api/sync/queue-depth")
def get_queue_depth(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """
    Local Endpoint. Returns number of pending queue items and latest execution stats.
    """
    business_id = _resolve_business_id_by_username(current_user, db)

    # Query pending items — fetch entity column too for breakdown
    try:
        pending_items = (
            db.query(SyncQueue.entity, SyncQueue.operation)
            .filter(SyncQueue.business_id == business_id, SyncQueue.synced_at.is_(None))
            .order_by(SyncQueue.created_at.asc())
            .all()
        )
        pending_count = len(pending_items)

        # Build per-entity counts, e.g. {"invoices": 3, "payments": 1}
        entity_counts: dict = {}
        for row in pending_items:
            entity_counts[row.entity] = entity_counts.get(row.entity, 0) + 1

        # The "next" entity is the oldest unsynced one (first in FIFO order)
        next_entity = pending_items[0].entity if pending_items else None

    except Exception:
        pending_count  = 0
        entity_counts  = {}
        next_entity    = None

    # Query last run log
    try:
        last_log = (
            db.query(SyncLog)
            .filter(SyncLog.business_id == business_id)
            .order_by(SyncLog.synced_at.desc())
            .first()
        )
    except Exception:
        last_log = None

    return {
        "pending_count":  pending_count,
        "entity_counts":  entity_counts,   # {"invoices": 3, "customers": 1, ...}
        "next_entity":    next_entity,      # entity currently at front of queue
        "last_sync_time": last_log.synced_at.isoformat() if last_log else None,
        "last_status":    last_log.status if last_log else "idle",
        "last_error":     last_log.error  if last_log else None,
    }


@router.get("/api/sync/conflicts")
def list_sync_conflicts(
    include_resolved: bool = False,
    limit: int = 100,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Surface sync conflicts for this business so the owner can review them —
    previously ConflictLog was written but never exposed anywhere. By default
    returns only the unreviewed ones (``resolution='review_needed'`` and not yet
    resolved), newest first, plus a total count for a UI badge."""
    business_id = _resolve_business_id_by_username(current_user, db)
    try:
        q = db.query(ConflictLog).filter(ConflictLog.business_id == business_id)
        if not include_resolved:
            q = q.filter(ConflictLog.resolution == "review_needed",
                         ConflictLog.resolved_at.is_(None))
        rows = q.order_by(ConflictLog.id.desc()).limit(max(1, min(limit, 500))).all()
        unreviewed = (
            db.query(func.count(ConflictLog.id))
            .filter(ConflictLog.business_id == business_id,
                    ConflictLog.resolution == "review_needed",
                    ConflictLog.resolved_at.is_(None))
            .scalar()
        ) or 0
        return {
            "unreviewed_count": int(unreviewed),
            "conflicts": [
                {
                    "id": r.id,
                    "entity": r.entity,
                    "entity_id": r.entity_id,
                    "resolution": r.resolution,
                    "local_updated_at": r.local_updated_at.isoformat() if r.local_updated_at else None,
                    "cloud_updated_at": r.cloud_updated_at.isoformat() if r.cloud_updated_at else None,
                    "local_payload": _safe_json_load(r.local_payload),
                    "cloud_payload": _safe_json_load(r.cloud_payload),
                    "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.warning("sync/conflicts: query failed for biz=%s: %s", business_id, e)
        return {"unreviewed_count": 0, "conflicts": []}


@router.post("/api/sync/conflicts/{conflict_id}/resolve")
def resolve_sync_conflict(
    conflict_id: int,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Mark a reviewed conflict as acknowledged (stamps ``resolved_at``). This
    does NOT change any business data — the winning row already stands; the owner
    is simply clearing it from their review list after looking at both versions."""
    business_id = _resolve_business_id_by_username(current_user, db)
    row = (
        db.query(ConflictLog)
        .filter(ConflictLog.id == conflict_id, ConflictLog.business_id == business_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    row.resolved_at = utc_now()
    db.commit()
    return {"ok": True, "id": conflict_id}


@router.post("/api/sync/flush")
def flush_sync_queue(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """
    Local Endpoint. Manually schedules immediate execution of the background sync worker.
    """
    from services.sync_worker import trigger_sync_run
    business_id = _resolve_business_id_by_username(current_user, db)
    background_tasks.add_task(trigger_sync_run, business_id)
    return {"status": "triggered", "business_id": business_id}
