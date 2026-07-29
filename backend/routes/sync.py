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
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import text, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database.db import get_db, sync_disabled_var
from services.auth import (
    get_active_user, require_business_owner, require_plan, resolve_business_id_in_db,
)
# (M-10) Shared with the push path so the pull payload carries the SAME parent
# uid enrichment. A bare column dump leaves the receiver with raw source-database
# foreign keys and nothing to resolve them against — see the call site.
from database.models import _serialize_orm_obj
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
    TWO_SIDED_OWNER_COLUMNS,
    PULL_ONLY_TABLES,
    resolve_parent_fk_uids,
    _USER_FK_REPOINT_ENTITIES,
)
# (M-7) Post-apply invariants are SHARED with services/sync_worker.py's pull
# path. They used to be private functions in this module, which is exactly why
# the pull direction silently never ran them — see core/sync/apply_hooks.py.
from core.sync import apply_hooks as _apply_hooks


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
    # The lock/unlock history is the evidence that the books were closed. A
    # sync-borne DELETE here would erase a close event and silently re-open a
    # locked period on the destination — the books must be re-opened by an
    # explicit unlock EVENT (a new row), never by deleting the lock. (M-2)
    "period_locks",
})


# Child tables deliberately do not duplicate ``business_id``.  Every mutation
# must therefore prove ownership through its parent before an existing child can
# be updated or deleted.  RLS remains a vital database backstop, but this guard
# makes the HTTP boundary fail closed on SQLite and on any misconfigured DB role.
_CHILD_OWNER_MODELS = {
    "invoice_line_items": (InvoiceLineItem, InvoiceLineItem.invoice_id, Invoice),
    "purchase_invoice_line_items": (
        PurchaseInvoiceLineItem, PurchaseInvoiceLineItem.purchase_invoice_id, PurchaseInvoice,
    ),
    "purchase_order_line_items": (
        PurchaseOrderLineItem, PurchaseOrderLineItem.purchase_order_id, PurchaseOrder,
    ),
    "stock_transfer_line_items": (
        StockTransferLineItem, StockTransferLineItem.transfer_id, StockTransfer,
    ),
}


def _record_belongs_to_business(db: Session, entity: str, row, business_id: int) -> bool:
    """Return true only when an existing sync row belongs to this tenant."""
    direct_business_id = getattr(row, "business_id", None)
    if direct_business_id is not None:
        return int(direct_business_id) == int(business_id)

    child = _CHILD_OWNER_MODELS.get(entity)
    if child:
        _child_model, parent_fk, parent_model = child
        parent_id = getattr(row, parent_fk.key, None)
        if parent_id is None:
            return False
        return bool(
            db.query(parent_model.id)
            .filter(parent_model.id == parent_id, parent_model.business_id == business_id)
            .first()
        )

    # An entity with no verified owner relation is never mutable through generic
    # sync. Adding a new entity now requires adding its ownership proof here.
    return False


# Entities where a conflicting concurrent edit must never be resolved SILENTLY.
# For these, whenever an incoming push OVERWRITES an existing row with a
# different-timestamped local version, we record a ConflictLog(review_needed)
# capturing both sides so the owner can see it — instead of the historical
# behaviour where the "local won" branch clobbered the cloud row with no trace
# (the silent-lost-edit failure mode, review P0). Resolution behaviour is
# UNCHANGED (LWW still lands the data); we only remove the silence.
# (M-8) MOVED to core/sync/apply_hooks.py so the pull direction shares it.
# Re-exported for any existing importer; do not fork a second copy here.
FINANCIAL_ENTITIES = _apply_hooks.FINANCIAL_ENTITIES


# ── Paid-state reconciliation: MOVED to core/sync/apply_hooks.py (M-7) ──────
#
# These were private functions here, so `services/sync_worker.py` could not
# reach them and the pull direction silently never reconciled — an invoice
# pulled cloud→local kept whatever status was serialised on the cloud, showing
# "Pending" while its payment history showed the money. Re-exported under their
# original names so any existing caller/test keeps working; NEW code should call
# `apply_hooks.run_post_apply`, which runs every invariant rather than this one.
#
# Do not reintroduce a local copy. That duplication IS the bug.
def _reconcile_invoice_paid_state(db, inv) -> None:
    _apply_hooks.reconcile_invoice_paid_state(db, inv)


def _reconcile_parent_invoice_of_payment(db, pay) -> None:
    _apply_hooks.reconcile_parent_invoice_of_payment(db, pay)


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
    """Serialize a row/ORM object to plain dict, stripping internal SA state.

    Delegates to the shared implementation (M-8) — a second copy here is how the
    conflict predicate drifted out of the pull path in the first place.
    """
    return _apply_hooks.row_to_dict(row)


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
    """True when the incoming push carries a MEANINGFUL change vs the current row.

    Delegates to the shared implementation (M-8) — see `_row_to_dict` above.
    """
    return _apply_hooks.payloads_differ(incoming, existing)


def _parse_dt(dt_str: Any) -> Optional[datetime]:
    """Delegates to the shared parser (M-5): an unparseable NON-empty timestamp
    is a real data defect that used to vanish silently here, stopping the row
    from ever syncing. Behaviour is unchanged; the silence is not."""
    return _apply_hooks.parse_dt(dt_str)


def _resolve_business_id_by_username_legacy(user: dict, db: Session) -> int:
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


# The active resolver is shared with the import/profile/staff paths.  The
# token's numeric id is local to the issuing database; BizID is the identity
# contract across desktop and cloud.
def _resolve_business_id_by_username(user: dict, db: Session, require_public_id: bool = False) -> int:
    return resolve_business_id_in_db(user, db, require_public_id=require_public_id)


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

class CloudTokenBody(BaseModel):
    token: str


@router.post("/api/sync/cloud-token")
def save_cloud_token(
    body: CloudTokenBody,
    current_user: dict = Depends(require_business_owner),
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


@router.post("/api/sync/heal")
def heal_sync_outbox(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """(Local) Scan for syncable rows missing from the outbox and queue them.

    Covers EVERY syncable entity type — both top-level tables and child/line-item
    tables (invoice_line_items, purchase_invoice_line_items, etc.) that previously
    had no business_id of their own and were silently dropped from the outbox.

    Returns a JSON summary of what was found and queued, grouped by entity type.
    Idempotent: safe to call multiple times; rows already in the outbox are never
    double-queued (the scan checks NOT EXISTS in sync_queue).

    Local-only: guarded by the sqlite dialect check so it cannot run on the cloud
    Postgres backend (which has no local outbox to heal).
    """
    from database.db import engine as _engine
    if _engine.dialect.name != "sqlite":
        raise HTTPException(
            status_code=400,
            detail="Heal endpoint is local-only (SQLite). The cloud backend has no outbox.",
        )

    from services.sync_worker import find_unqueued_syncable_rows, _heal_unqueued_rows, _row_to_dict, _MODEL_MAP
    from database.models import _serialize_orm_obj
    import json as _json
    from services.dates import utc_now as _utc_now

    business_id = _resolve_business_id_by_username(current_user, db)

    # Scan first (read-only) so we can return a per-entity breakdown
    missing = find_unqueued_syncable_rows(db, business_id)

    by_entity: dict = {}
    for item in missing:
        by_entity.setdefault(item["entity"], []).append(item["row_id"])

    if not missing:
        return {
            "status": "ok",
            "message": "Outbox is complete — no missing rows found.",
            "queued": 0,
            "by_entity": {},
        }

    # Queue them (reuses the same logic as the automatic heal in sync_worker)
    queued = 0
    failed = []
    for entity, row_ids in by_entity.items():
        model_cls = _MODEL_MAP.get(entity)
        if not model_cls:
            continue
        for row_id in row_ids:
            try:
                obj = db.query(model_cls).filter(model_cls.id == row_id).first()
                if not obj:
                    continue
                payload = _json.dumps(_row_to_dict(obj), default=str)
                db.execute(
                    text(
                        "INSERT INTO sync_queue "
                        "(business_id, entity, entity_id, operation, payload, created_at) "
                        "VALUES (:bid, :ent, :eid, 'INSERT', :pay, :now)"
                    ),
                    {"bid": business_id, "ent": entity,
                     "eid": row_id,      "pay": payload,
                     "now": _utc_now()},
                )
                queued += 1
            except Exception as e:
                failed.append({"entity": entity, "row_id": row_id, "error": str(e)})

    db.commit()

    logger.info(
        "[SYNC_HEAL] manual heal for biz=%s: queued=%s failed=%s entities=%s",
        business_id, queued, len(failed),
        {e: len(ids) for e, ids in by_entity.items()},
    )

    return {
        "status": "ok",
        "message": f"Queued {queued} previously-missing row(s). They will be pushed on the next sync cycle.",
        "queued": queued,
        "failed": len(failed),
        "by_entity": {e: len(ids) for e, ids in by_entity.items()},
        "errors": failed[:10],  # cap to avoid huge responses
    }


@router.post("/api/sync/push")
def push_changes(
    payload: PushPayload,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_business_owner),
    _plan: dict = Depends(require_plan("pro")),   # 402 for free plan when SUBSCRIPTION_ENFORCED=1
    db: Session = Depends(get_db),
):
    """
    Cloud Endpoint. Receives local changes and applies them to PostgreSQL.
    Enforces multi-tenant scoping and applies Last-Write-Wins (LWW) resolution.
    """
    business_id = _resolve_business_id_by_username(current_user, db, require_public_id=True)
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

    inbound_pull_only = sorted({
        change.entity for change in payload.changes if change.entity in PULL_ONLY_TABLES
    })
    if inbound_pull_only:
        raise HTTPException(
            status_code=422,
            detail="Inbound sync is not allowed for cloud-authoritative entities: "
                   + ", ".join(inbound_pull_only),
        )

    # Temporarily disable trigger hooks to prevent queuing writes back on the cloud
    token = sync_disabled_var.set(True)
    processed_count = 0
    entities_to_broadcast = set()
    # Post-apply invariants that failed (M-2 / M-7). Collected rather than raised
    # so one bad row can't stall the outbox — but reported in the response and
    # logged at ERROR, never swallowed.
    apply_failures = []
    rejected = []          # M-13: rows the cloud REFUSED to store
    # M-20: rows the cloud DEFERRED — a THIRD state, and the one that was
    # invisible. See the deferral site below and `_defer` for the full finding.
    deferred = []
    # M-20 (arithmetic): rows the cloud deliberately SKIPPED and acked — an
    # unknown entity, or an LWW decision that the cloud's copy is newer. They are
    # correct outcomes, but they were reported nowhere, so `applied + deferred`
    # could never equal `received` and the device's reconciliation had a
    # permanent unexplained remainder. Every row must land in exactly one bucket.
    skipped = []

    entity_map = ENTITY_BROADCAST_MAP

    try:
        for change in payload.changes:
            model_cls = _MODEL_MAP.get(change.entity)
            if not model_cls:
                logger.warning("sync/push: unknown entity %s", change.entity)
                skipped.append({"entity": change.entity, "row_id": change.entity_id,
                                "reason": "unknown entity on this server"})
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
                if not _record_belongs_to_business(db, change.entity, existing, business_id):
                    logger.warning(
                        "sync/push: tenant mismatch for %s.id=%s business=%s",
                        change.entity, change.entity_id, business_id,
                    )
                    raise HTTPException(status_code=403, detail="Cross-business sync mutation denied")

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

            # (R-8) Clock-skew guard: a device with its clock set forward >5 min
            # permanently wins all LWW comparisons. Reject such rows on the cloud
            # before they land.
            if local_updated_at:
                _server_now = utc_now()
                _server_aware = _server_now.replace(tzinfo=timezone.utc) \
                    if _server_now.tzinfo is None else _server_now
                _local_aware = local_updated_at.replace(tzinfo=timezone.utc) \
                    if local_updated_at.tzinfo is None else local_updated_at
                if _local_aware > _server_aware + timedelta(minutes=5):
                    logger.warning(
                        "sync/push: %s.id=%s rejected — updated_at %s is >5 min ahead "
                        "of server time %s. Device clock may be skewed.",
                        change.entity, change.entity_id, local_updated_at, _server_now,
                    )
                    db.add(ConflictLog(
                        business_id=business_id,
                        entity=change.entity,
                        entity_id=change.entity_id,
                        local_updated_at=local_updated_at,
                        cloud_updated_at=_server_aware,
                        local_payload=json.dumps(data, default=str),
                        cloud_payload="{}",
                        resolved_at=utc_now(),
                        resolution="clock_skew",
                    ))
                    skipped.append({"entity": change.entity, "row_id": change.entity_id,
                                    "reason": "updated_at more than 5 min in the future (clock skew)"})
                    continue

            if existing and hasattr(existing, "updated_at") and existing.updated_at:
                cloud_updated_at = _parse_dt(existing.updated_at)
                # (R-5) An incoming change with no updated_at cannot be proven
                # newer — keep the existing cloud row rather than blindly clobber.
                if not local_updated_at:
                    logger.warning(
                        "sync/push: %s.id=%s has no updated_at — keeping cloud version (cannot resolve LWW)",
                        change.entity, change.entity_id,
                    )
                    skipped.append({"entity": change.entity,
                                    "row_id": change.entity_id,
                                    "reason": "no updated_at; cloud version kept"})
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
                    skipped.append({"entity": change.entity,
                                    "row_id": change.entity_id,
                                    "reason": "cloud copy is newer (LWW)"})
                    continue

                # (P0) Local-wins on a FINANCIAL row = the previously-SILENT
                # overwrite. Data still lands (LWW below), but a financial record
                # being edited on two devices is something the owner must see, so
                # a review_needed conflict capturing the cloud version is written
                # BEFORE we clobber it. Guarded to a genuine change (differing
                # timestamp AND differing content) so normal edit→sync
                # propagation of an unchanged row doesn't spam the review list.
                #
                # (M-8) The predicate and the write now live in the SHARED hooks
                # module. They used to be inline here, which is exactly why an
                # overwrite arriving by PULL was never flagged — the same
                # one-directional blind spot as M-7. Do not re-inline this.
                _apply_hooks.log_financial_conflict(
                    db,
                    business_id=business_id,
                    entity=change.entity,
                    entity_id=change.entity_id,
                    incoming=data,
                    existing_row=existing,
                    incoming_updated_at=local_updated_at,
                    existing_updated_at=cloud_updated_at,
                    log_prefix="sync/push",
                )

                # (R-9) Non-financial master-data LWW overwrite — same loss-of-
                # version risk as financial rows but lower severity. cloud_updated_at
                # is in scope here (assigned above in this same if-block).
                _apply_hooks.log_master_data_conflict(
                    db,
                    business_id=business_id,
                    entity=change.entity,
                    entity_id=change.entity_id,
                    incoming=data,
                    existing_row=existing,
                    incoming_updated_at=local_updated_at,
                    existing_updated_at=cloud_updated_at,
                    resolution="local_won",
                    log_prefix="sync/push",
                )

            # Resolve FKs via the parent's durable uid (shared helper — same logic
            # as the pull-apply worker). If a parent_uid is present but the parent
            # row isn't in this DB yet, the child is DEFERRED rather than written
            # with the source-DB integer id (wrong-row / orphan); it re-applies on
            # a later sync once the parent exists.
            if resolve_parent_fk_uids(db, model_cls, data,
                business_id=business_id,
                log_prefix=f"sync/push[{change.entity}.id={change.entity_id}]",
            ):
                # -- M-20 (CRITICAL): the row is DEFERRED, the client MUST be told --
                #
                # Deferring is correct: writing the source database's integer FK
                # would be M-9, money on the wrong customer's invoice. The
                # contract in `resolve_parent_fk_uids` is that the row "re-applies
                # on a later sync once the parent lands".
                #
                # That contract was broken on the other side. This `continue`
                # used to skip the row without recording it anywhere: it is not
                # counted in `processed_count`, and `rejected` is appended to
                # only inside the IntegrityError handler below. So the response
                # said `{"applied": 4, "rejected": []}` for five rows sent, and
                # `services/sync_worker.py` — which counts what it SENT and never
                # reads `applied` — stamped `synced_at` on all five. The outbox
                # row was gone, so the "later sync" could never happen.
                #
                # Reproduced on production 2026-07-27: a ₹641 sale (invoice 860,
                # LCL-OW-0028) deferred for a missing `register_shifts` parent,
                # acked by the client, and permanently absent from the cloud.
                #
                # A deferred row is NOT a rejected row. Rejected means "we refuse
                # this, stop sending it". Deferred means "not yet, keep it and
                # send it again". Collapsing the two loses data in one direction
                # and spins forever in the other, so they are reported separately.
                deferred.append({
                    "entity": change.entity,
                    "row_id": change.entity_id,
                    "uid": data.get("uid"),
                    "reason": "parent not resolvable in this database yet",
                })
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
                    # Payment state is server-authoritative: re-derive it from the
                    # payment ledger so a stale client can't un-pay a settled invoice.
                    # Every post-apply invariant, from the SHARED module both
                    # sync directions use (M-7). Payment state is
                    # server-authoritative (re-derived from this database's own
                    # ledger, so a stale client can't un-pay a settled invoice)
                    # and the journal is re-derived here (M-2). Adding a hook to
                    # apply_hooks enforces it in both directions at once — which
                    # is the whole point, since the paid-state reconcile used to
                    # live in this file and therefore ran on push only.
                    _hook = _apply_hooks.run_post_apply(
                        db, change.entity, target_obj, log_prefix="sync/push")
                    if not _hook.ok:
                        apply_failures.append(_hook)
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
                                    # Same shared hooks on the dedupe path — an
                                    # integrity-deduped row is still an applied
                                    # row, and skipping them here would leave
                                    # exactly the invoices that raced looking
                                    # unpaid.
                                    _dup_hook = _apply_hooks.run_post_apply(
                                        db, change.entity, dup, log_prefix="sync/push-dedupe")
                                    if not _dup_hook.ok:
                                        apply_failures.append(_dup_hook)
                                deduped = "updated"
                            else:
                                deduped = "kept-newer-cloud"
                except Exception as ie2:
                    deduped = "dedupe-failed"
                    logger.warning("sync/push: dedupe-update failed for %s uid=%s: %s", change.entity, uid_val, ie2)

                if deduped in ("updated", "kept-newer-cloud"):
                    # A genuine uid collision, resolved. The row IS represented in
                    # the cloud, so acking it is correct and nothing is lost.
                    logger.info(
                        "sync/push: %s.id=%s integrity-deduped by uid (%s): %s",
                        change.entity, change.entity_id, deduped, getattr(ie, "orig", ie),
                    )
                else:
                    # M-13 — the row was REJECTED, not deduplicated.
                    #
                    # `deduped == "skipped"` means the IntegrityError was NOT a uid
                    # collision: no uid on the payload, the model has no uid column,
                    # or no existing row carries it. So the constraint that fired was
                    # something else — a foreign key, one of the N4 money CHECKs, or
                    # the M-11 one-open-shift index — and the incoming row landed
                    # NOWHERE.
                    #
                    # This used to be `logger.info(...)` followed unconditionally by
                    # `processed_count += 1`, i.e. the row was acked and the device's
                    # outbox dropped it forever. That silently discards a LOCAL write
                    # — the shop's own sale — which is the M-12 defect pointing the
                    # other way, and the N4 constraints make it far more reachable
                    # than it used to be.
                    #
                    # The ack STAYS: refusing it would stall the outbox behind a row
                    # that can never apply, which is the same poison-row trade the
                    # per-row SAVEPOINT and `_PULL_MAX_FAILED_STREAK` already make.
                    # What changes is that acking is no longer silent — the row is
                    # recorded for review with its full payload, logged at ERROR, and
                    # returned to the caller in `rejected`, so the device knows its
                    # write did not survive.
                    _apply_hooks.log_apply_failure(
                        db,
                        business_id=business_id,
                        entity=change.entity,
                        entity_id=change.entity_id,
                        payload=data,
                        error=ie,
                        log_prefix="sync/push",
                    )
                    rejected.append({
                        "entity": change.entity,
                        "row_id": change.entity_id,
                        "uid": uid_val,
                        "reason": str(getattr(ie, "orig", ie)).strip().splitlines()[0],
                    })
                processed_count += 1  # ack either way so it isn't re-sent every cycle
                continue

        db.commit()

        # Broadcast sync triggers and instant pull_ping to SSE connections in background
        from services.realtime import realtime_manager
        for ent in entities_to_broadcast:
            background_tasks.add_task(realtime_manager.broadcast, business_id, {"type": "sync.trigger", "entity": ent})
        if entities_to_broadcast:
            background_tasks.add_task(realtime_manager.broadcast, business_id, {"type": "sync.pull_ping", "entity": "pull_ping"})

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error("sync/push: fatal error — %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Sync push failed: {e}")
    finally:
        sync_disabled_var.reset(token)

    if apply_failures:
        # Surfaced, not swallowed: the client sees it, the log records it, and
        # the books-integrity audit can act on it. The push itself still
        # succeeded — the documents landed; it is an invariant over them that
        # didn't hold, and re-pushing the same rows retries the hooks.
        logger.error("sync/push: %s post-apply invariant(s) FAILED for biz=%s: %s",
                     len(apply_failures), business_id,
                     [f"{h.entity}#{h.row_id}: {'; '.join(h.errors)}" for h in apply_failures])

    if rejected:
        # ERROR, and returned to the caller. An acked row that never stored is
        # the one failure a client cannot detect for itself (M-13).
        logger.error(
            "sync/push: %s row(s) REJECTED by the cloud for biz=%s — acked so the "
            "outbox drains, recorded for review, and reported to the device. These "
            "writes are NOT in the cloud: %s",
            len(rejected), business_id,
            [f"{r['entity']}#{r['row_id']}: {r['reason']}" for r in rejected],
        )

    if deferred:
        # WARNING, not ERROR: a deferral is a legitimate ordering outcome and is
        # expected to resolve on the next cycle. It becomes an error only if it
        # never resolves, which the CLIENT is positioned to detect (it knows how
        # many times it has re-sent the row) — see `_PUSH_MAX_DEFER_STREAK`.
        logger.warning(
            "sync/push: %s row(s) DEFERRED for biz=%s — their parent is not in "
            "this database yet. They are NOT stored and NOT acked; the device "
            "must keep them queued and re-send: %s",
            len(deferred), business_id,
            [f"{d['entity']}#{d['row_id']}: {d['reason']}" for d in deferred],
        )

    return {
        "status": "success",
        "applied": processed_count,
        "received": len(payload.changes),
        "apply_failures": [
            {"entity": h.entity, "row_id": h.row_id, "errors": h.errors}
            for h in apply_failures
        ],
        "rejected": rejected,
        # Acked and NOT stored as sent, but deliberately so. Counted separately
        # from `applied` for the device's arithmetic; NOT a failure.
        "skipped": skipped,
        # M-20. An older client that does not know this field will ignore it and
        # behave exactly as before — no worse, and the cloud-side log above still
        # records the deferral. A CURRENT client keeps these rows queued.
        "deferred": deferred,
    }


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
    business_id = _resolve_business_id_by_username(current_user, db, require_public_id=True)
    last_sync_dt = _parse_dt(last_sync_at) or datetime(1970, 1, 1)

    changes: Dict[str, List[dict]] = {}
    # Tables this pull could NOT read. Returned to the client so a missing table
    # is distinguishable from an empty one (rule 33) — see the except block.
    failed_tables: List[dict] = []

    for table_name, model_cls in _MODEL_MAP.items():
        try:
            cols = {c.name for c in model_cls.__table__.columns}
            query = db.query(model_cls)

            # Apply tenant isolation
            if table_name == "users":
                query = query.filter((model_cls.id == business_id) | (model_cls.parent_business_id == business_id))
            elif "business_id" in cols:
                query = query.filter(model_cls.business_id == business_id)
            elif table_name in TWO_SIDED_OWNER_COLUMNS:
                # B2B rows belong to BOTH parties, so they are scoped by two
                # owner columns rather than one `business_id`. Either side may
                # mirror the row down; RLS on these tables enforces the same
                # buyer-or-seller predicate server-side.
                a, b = TWO_SIDED_OWNER_COLUMNS[table_name]
                query = query.filter(
                    (getattr(model_cls, a) == business_id) | (getattr(model_cls, b) == business_id)
                )
            elif table_name == "b2b_order_line_items":
                # No owner column at all — scoped through its parent order.
                query = query.filter(
                    model_cls.order_id.in_(
                        db.query(_MODEL_MAP["b2b_orders"].id).filter(
                            (_MODEL_MAP["b2b_orders"].seller_business_id == business_id)
                            | (_MODEL_MAP["b2b_orders"].buyer_business_id == business_id)
                        )
                    )
                )
            else:
                continue

            # Apply updated_at filter if present
            if "updated_at" in cols:
                query = query.filter(model_cls.updated_at > last_sync_dt)

            rows = query.all()
            if rows:
                # (M-10) Enrich with PARENT UIDs, exactly as the push path does
                # (`database/models.py::_serialize_orm_obj`).
                #
                # This used to be a bare `_row_to_dict(r)` — a plain column dump
                # carrying raw source-database integer foreign keys and no uid at
                # all. `resolve_parent_fk_uids` on the receiving side therefore
                # had NOTHING to resolve against and fell through to writing the
                # source id verbatim, which points at whatever unrelated local row
                # happens to hold that integer.
                #
                # That is the ROOT CAUSE of the mis-attached payments found in
                # production on 26 Jul 2026: two receipts landed on the wrong
                # customers' invoices (M-9). The push direction was never affected
                # because it has always enriched; only pull was blind.
                #
                # It is also what made the M-9 guard bite: with no uid in the
                # payload, a NOT NULL child FK (invoice_line_items.invoice_id,
                # invoice_payments.invoice_id) can never be verified, so those
                # rows would defer forever. Supplying the uid fixes both — the
                # guard becomes a backstop rather than the primary mechanism.
                #
                # Cost: one small SELECT per foreign key per row. The push path
                # has always paid it; correctness on money links is worth it.
                changes[table_name] = [_serialize_orm_obj(r, db) for r in rows]

        except Exception as e:
            # ── RULE 58 ON THE PULL PATH ──────────────────────────────────────
            #
            # On Postgres a failed statement ABORTS the whole transaction, and
            # every later statement raises `InFailedSqlTransaction` until
            # someone rolls back. This loop queries ~25 tables on ONE session,
            # and nothing rolled back — so a single bad query silently took out
            # every table after it.
            #
            # Observed in production 2026-07-28 00:29: one failure cascaded
            # through shift_cash_movements, invoices, inventory, payments,
            # stock_ledger, product_barcodes, business_settings,
            # invoice_payments, expenses, godowns, stock_transfers,
            # purchase_invoices, purchase_orders, alert_configs,
            # rate_limit_configs, table_alterations, period_locks,
            # b2b_connections, b2b_orders and b2b_order_line_items — twenty
            # tables reported as "failed querying" when ONE had actually failed.
            #
            # This is the same defect as N4b-PG (§63) in the migration runner,
            # on a different path. The rule was written after that one; this is
            # it being applied where it had not yet been.
            #
            # The pull still returns whatever DID load — a partial pull is far
            # better than none — but the client is told, because a `changes`
            # dict that is missing a table is indistinguishable from a table
            # with no changes (rule 33).
            failed_tables.append({"table": table_name, "error": str(e)[:200]})
            logger.warning("sync/pull: failed querying table %s — %s", table_name, e)
            try:
                db.rollback()
            except Exception as rb:
                # Acceptable swallow (rule 13): cleanup inside an error path
                # already reported above. Logged so a dead session is not silent.
                logger.warning("sync/pull: rollback after %s failed: %s",
                               table_name, rb)

    if failed_tables:
        logger.error(
            "sync/pull: %s of %s table(s) could NOT be read for biz=%s. The "
            "client is receiving a PARTIAL pull and is told which tables are "
            "missing — an absent table is not an empty one: %s",
            len(failed_tables), len(_MODEL_MAP), business_id,
            [f["table"] for f in failed_tables],
        )

    return {
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "changes": changes,
        # Rule 33: the receiver must be able to tell "no rows" from "not read".
        "failed_tables": failed_tables,
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


@router.get("/api/sync/outbox/details")
def get_outbox_details(
    limit: int = 50,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Owner-facing endpoint to inspect detailed outbox items and failure reasons."""
    business_id = _resolve_business_id_by_username(current_user, db)
    try:
        rows = (
            db.query(SyncQueue)
            .filter(SyncQueue.business_id == business_id, SyncQueue.synced_at.is_(None))
            .order_by(SyncQueue.created_at.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
        return {
            "count": len(rows),
            "items": [
                {
                    "id": r.id,
                    "entity": r.entity,
                    "entity_id": r.entity_id,
                    "operation": r.operation,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "retry_count": r.retry_count or 0,
                    "last_error": r.last_error,
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.warning("sync/outbox/details failed for biz=%s: %s", business_id, e)
        return {"count": 0, "items": []}


@router.post("/api/sync/outbox/{queue_id}/retry")
def retry_outbox_item(
    queue_id: int,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Reset retry count and clear error for a specific outbox item so it can be re-attempted."""
    business_id = _resolve_business_id_by_username(current_user, db)
    row = (
        db.query(SyncQueue)
        .filter(SyncQueue.id == queue_id, SyncQueue.business_id == business_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Outbox item not found")
    row.retry_count = 0
    row.last_error = None
    db.commit()
    return {"ok": True, "id": queue_id}


@router.post("/api/sync/parity")
def run_parity_check(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """
    Local Endpoint. Manually triggers a UID-based cross-DB parity check between
    local SQLite and cloud Postgres for the current business.

    Detects and auto-repairs:
    - Line items / payments on the wrong cloud invoice (WRONG_INVOICE)
    - Line items / payments missing from the cloud entirely (MISSING)
    - Invoices with stale paid_amount / status on the cloud (PAID_STATE)

    The check is rate-limited to once every 6 hours automatically; this endpoint
    bypasses the rate limit so an admin can force an immediate run.
    Repairs are queued in the outbox — they push on the next sync cycle.
    """
    from services.sync_worker import _cloud_parity_check, _LAST_PARITY

    business_id = _resolve_business_id_by_username(current_user, db)

    def _run_parity(bid: int):
        # Bypass the rate-limit for a manual trigger
        _LAST_PARITY.pop(bid, None)
        db2 = db.__class__(bind=db.bind) if hasattr(db, "bind") else None
        from database.db import SessionLocal as _SL
        _db = _SL()
        try:
            from logging_config import current_bizid_var
            user_obj = _db.query(__import__("database.models", fromlist=["User"]).User).filter_by(id=bid).first()
            _t = current_bizid_var.set(getattr(user_obj, "public_id", None) or "-")
            try:
                result = _cloud_parity_check(_db, bid)
                logger.info("[PARITY] manual run complete for biz=%s: %s", bid, result)
            finally:
                current_bizid_var.reset(_t)
        except Exception as e:
            logger.error("[PARITY] manual run failed for biz=%s: %s", bid, e)
        finally:
            _db.close()

    background_tasks.add_task(_run_parity, business_id)
    return {
        "status": "triggered",
        "business_id": business_id,
        "note": "Parity check running in background. Results appear in server logs and outbox.",
    }
