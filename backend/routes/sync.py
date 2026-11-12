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
import base64
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Dict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy import text, func, or_, and_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, InternalError, DataError, StatementError, DBAPIError

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


@router.get("/api/sync/status")
def sync_status(current_user: dict = Depends(require_business_owner)):
    from core.cloud_endpoint import CLOUD_URL, CLOUD_URL_SOURCE
    from services.sync_worker import get_cloud_state
    state = get_cloud_state(current_user.get("business_id") or current_user["user_id"]) or {}
    return {"cloud_url":CLOUD_URL, "cloud_url_source":CLOUD_URL_SOURCE,
            "cloud_state":state.get("state"), "last_probe_at":state.get("last_probe_at"),
            "retry_after":state.get("retry_after")}

# (R-7) Single shared source — see database/sync_map.py
from database.sync_map import (
    MODEL_MAP as _MODEL_MAP,
    ENTITY_BROADCAST_MAP,
    TWO_SIDED_OWNER_COLUMNS,
    PULL_ONLY_TABLES,
    APPEND_ONLY_DELETE_BLOCKLIST,
    resolve_parent_fk_uids,
    _USER_FK_REPOINT_ENTITIES,
)
# (M-7) Post-apply invariants are SHARED with services/sync_worker.py's pull
# path. They used to be private functions in this module, which is exactly why
# the pull direction silently never ran them — see core/sync/apply_hooks.py.
from core.sync import apply_hooks as _apply_hooks


# APPEND_ONLY_DELETE_BLOCKLIST now lives in database/sync_map.py so the SENDER
# can honour it too — see the note there. The 422 below stays as the receiving
# side's backstop; the enqueue guard is the thing that keeps such a row out of
# the outbox in the first place.


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


# NOTE: `_resolve_business_id_by_username_legacy` lived here and was deleted
# 2026-07-31 for the same reason as its twin in routes/data_transfer.py — a
# username/JWT-id fallback chain that no longer had a caller. The active path is
# `_resolve_business_id_by_username` below. See docs/CLEANUP_PLAN_2026-07-31.md §2.



# The active resolver is shared with the import/profile/staff paths.  The
# token's numeric id is local to the issuing database; BizID is the identity
# contract across desktop and cloud.
def _resolve_business_id_by_username(user: dict, db: Session, require_public_id: bool = False) -> int:
    """Token → THIS database's integer business id.

    THE BOUNDARY. The caller's token was minted by a different database, so the
    integer ids in it mean nothing here — only the `public_id` (BizID) claim
    does. This is the one place that translation happens, and everything
    downstream may then use the returned integer freely because it is local.

    `require_public_id=True` refuses to fall back to matching on username, which
    is what keeps a token from resolving to the wrong tenant. Pass it on every
    route that reads or writes business data. See core/identity.py.
    """
    return resolve_business_id_in_db(user, db, require_public_id=require_public_id)


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

class CloudTokenBody(BaseModel):
    token: str
    enable_sync: bool = False


@router.get("/api/sync/bootstrap-state")
def bootstrap_state(current_user: dict = Depends(require_business_owner), db: Session = Depends(get_db)):
    """Attest an empty new business before permitting an empty local mirror.

    Clients cannot assert this themselves. A populated business must complete
    restoration; a brand-new Local-only registration has nothing to restore.
    """
    business_id = _resolve_business_id_by_username(current_user, db, require_public_id=True)
    from database.change_feed import _CHILD
    def owned(query, model, entity):
        if hasattr(model, "business_id"):
            return query.filter(model.business_id == business_id)
        if entity in TWO_SIDED_OWNER_COLUMNS:
            a, b = TWO_SIDED_OWNER_COLUMNS[entity]
            return query.filter(or_(getattr(model, a) == business_id, getattr(model, b) == business_id))
        if entity in _CHILD:
            parent_entity, fk = _CHILD[entity]
            parent = _MODEL_MAP[parent_entity]
            parents = owned(db.query(parent.id), parent, parent_entity)
            return query.filter(getattr(model, fk).in_(parents))
        raise HTTPException(503, "Business restore readiness could not be verified.")
    for entity, model in _MODEL_MAP.items():
        if owned(db.query(model.id), model, entity).first() is not None:
            return {"has_business_data": True}
    return {"has_business_data": False}


class RegisterDeviceBody(BaseModel):
    installation_id: UUID


@router.post("/api/sync/register-device")
def register_device(body: RegisterDeviceBody, current_user: dict = Depends(require_business_owner),
                    _plan: dict = Depends(require_plan("pro", force_enforcement=True)), db: Session = Depends(get_db)):
    from core.sync.device_series import allocate_namespace
    business_id = _resolve_business_id_by_username(current_user, db, require_public_id=True)
    try:
        namespace = allocate_namespace(db, business_id, body.installation_id)
        db.commit()
        return {"namespace": namespace}
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(409, "Device series registration changed concurrently or reached its limit. Retry device setup.") from exc


def _register_cloud_device(token, installation):
    import httpx
    import re
    from core.cloud_endpoint import CLOUD_URL
    try:
        response = httpx.post(f"{CLOUD_URL}/api/sync/register-device", json={"installation_id": installation},
                              headers={"Authorization": f"Bearer {token}"}, timeout=5.0)
        if response.status_code in {401, 403}:
            raise HTTPException(401, "Sign in again to register this device's billing series.")
        if response.status_code == 402:
            raise HTTPException(402, "An active Pro plan is required to register this device.")
        namespace = response.json().get("namespace") if response.status_code == 200 else None
        if not isinstance(namespace, str) or not re.fullmatch(r"[0-9A-Z]{3}", namespace):
            raise HTTPException(503, "The cloud could not register this device's billing series. Update the server and retry setup.")
        return namespace
    except (httpx.HTTPError, ValueError, AttributeError):
        raise HTTPException(503, "Device series registration is temporarily unavailable. Retry cloud setup.") from None


def _read_verified_cloud_document(path: str, token: str) -> dict:
    """Only the configured cloud authority may attest a desktop credential."""
    import httpx
    from core.cloud_endpoint import CLOUD_URL
    try:
        response = httpx.get(
            f"{CLOUD_URL}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
    except httpx.HTTPError:
        raise HTTPException(503, "Cloud sync verification is temporarily unavailable. It will be retried.") from None
    if response.status_code in (401, 403):
        raise HTTPException(401, "The cloud session could not be verified. Sign in again to reconnect sync.")
    if response.status_code != 200:
        raise HTTPException(503, "Cloud sync verification is temporarily unavailable. It will be retried.")
    try:
        document = response.json()
    except (ValueError, TypeError):
        document = None
    if not isinstance(document, dict):
        raise HTTPException(503, "The cloud verification response was incomplete. It will be retried.")
    return document


@router.post("/api/sync/cloud-token")
def save_cloud_token(
    body: CloudTokenBody,
    background_tasks: BackgroundTasks,
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
    from services.sync_worker import store_cloud_token, trigger_sync_run
    from database.models import SyncCursor
    if db.get_bind().dialect.name != "sqlite":
        raise HTTPException(409, "Cloud sync credentials can only be provisioned on a local device.")
    business_id = _resolve_business_id_by_username(current_user, db, require_public_id=True)
    owner = db.query(User).filter(User.id == business_id, User.parent_business_id.is_(None)).first()
    if owner is None:
        raise HTTPException(404, "Local business owner not found.")
    try:
        initial_general = json.loads(owner.settings or "{}").get("general") or {}
        initial_mode_revision = initial_general.get("sync_mode_revision", 0)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(409, "Local business settings could not be read. Nothing was changed.") from None
    if body.enable_sync and initial_general.get("sync_local_only_explicit") is True:
        raise HTTPException(409, "Local-only was explicitly selected on this installation. Choose Local + Cloud in Settings to enable sync again.")

    # Even a store-only request must not replace this business's working token
    # with a credential belonging to a different tenant or a staff identity.
    profile = _read_verified_cloud_document("/profile", body.token)
    cloud_bizid = (profile.get("public_id") or "").strip()
    if (not cloud_bizid or cloud_bizid != (owner.public_id or "").strip()
            or (profile.get("role") or "").lower() not in {"enterprise", "owner", "admin"}):
        raise HTTPException(409, "The cloud session belongs to a different business or is not its owner.")

    subscription = None
    device_namespace = None
    local_installation = None
    if body.enable_sync:
        from types import SimpleNamespace
        from services.admin_service import effective_plan
        cloud_settings = _read_verified_cloud_document("/settings", body.token)
        subscription = cloud_settings.get("subscription")
        if not isinstance(subscription, dict):
            raise HTTPException(503, "Cloud subscription verification was incomplete. It will be retried.")
        if effective_plan(SimpleNamespace(settings=json.dumps({"subscription": subscription}))) != "pro":
            raise HTTPException(402, "Local + Cloud sync requires an active Pro plan.")
        from core.sync.device_series import installation_id
        try:
            local_installation = installation_id()
        except OSError:
            raise HTTPException(503, "The installation identity could not be saved. Check device storage before starting sync.") from None
        if initial_general.get("device_installation_id") == local_installation and initial_general.get("device_invoice_namespace"):
            device_namespace = initial_general["device_invoice_namespace"]
        else:
            device_namespace = _register_cloud_device(body.token, local_installation)

    # Verification performs no local writes. Re-read after the network round
    # trips so unrelated settings saved in the meantime are preserved.
    db.refresh(owner, attribute_names=["settings", "public_id"])
    if cloud_bizid != (owner.public_id or "").strip():
        raise HTTPException(409, "The local business identity changed. Sign in again to reconnect sync.")
    try:
        current_settings_raw = owner.settings
        settings = json.loads(owner.settings or "{}")
        general = settings.setdefault("general", {})
        if not isinstance(settings, dict) or not isinstance(general, dict):
            raise ValueError("invalid settings")
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(409, "Local business settings could not be read. Nothing was changed.") from None
    if body.enable_sync and general.get("sync_mode_revision", 0) != initial_mode_revision:
        raise HTTPException(409, "The storage choice changed while sync was starting. Your latest choice was kept.")

    # The verified credential is durable before hybrid mode can wake a worker.
    # If the settings commit fails, the token still names this same business;
    # no work is queued and the old hosting mode remains in force.
    try:
        store_cloud_token(business_id, body.token)
    except OSError:
        raise HTTPException(503, "This device could not save its cloud credential. Check device storage and try again.") from None
    if body.enable_sync:
        cursor = db.query(SyncCursor).filter(SyncCursor.business_id == business_id, SyncCursor.entity == "*").first()
        initial_pending = general.get("sync_bootstrap_pending") is True or not (
            cursor and (cursor.cursor_value or "").startswith("feed:v2:"))
        general["hosting_mode"] = "hybrid"
        general["sync_bootstrap_pending"] = initial_pending
        general["device_installation_id"] = local_installation
        general["device_invoice_namespace"] = device_namespace
        settings["subscription"] = subscription
        # A choice from another process/tab must also win after verification.
        # Compare-and-set the complete latest settings instead of overwriting a
        # concurrent Local-only save (including Local -> Local confirmations).
        changed = (db.query(User)
                   .filter(User.id == business_id, User.settings == current_settings_raw)
                   .update({User.settings: json.dumps(settings)}, synchronize_session=False))
        if changed != 1:
            db.rollback()
            raise HTTPException(409, "Business settings changed while sync was starting. Your latest choice was kept.")
        db.commit()
        background_tasks.add_task(trigger_sync_run, business_id, pull=True)
        return {"status": "ok", "hosting_mode": "hybrid", "sync_started": True,
                "initial_restore_pending": initial_pending}
    return {"status": "ok"}


@router.post("/api/sync/resume")
def resume_device_sync(background_tasks: BackgroundTasks,
                       current_user: dict = Depends(require_business_owner), db: Session = Depends(get_db)):
    """Resume from the backend's renewed credential without exposing it to JS."""
    if db.get_bind().dialect.name != "sqlite":
        raise HTTPException(409, "Device sync is available on local installations only.")
    business_id = _resolve_business_id_by_username(current_user, db, require_public_id=True)
    owner = db.get(User, business_id)
    try:
        general = (json.loads(owner.settings or "{}") or {}).get("general") or {}
        if not isinstance(general, dict):
            raise ValueError("Invalid settings")
    except (AttributeError, ValueError, TypeError):
        raise HTTPException(409, "Local business settings could not be read. Nothing was changed.") from None
    if general.get("sync_local_only_explicit") is True:
        raise HTTPException(409, "Local-only was explicitly selected. Choose Local + Cloud in Settings to resume sync.")
    from services.sync_worker import ensure_fresh_cloud_token
    credential = ensure_fresh_cloud_token(business_id)
    if not credential:
        raise HTTPException(401, "Sign in online again to reconnect this device's cloud sync.")
    return save_cloud_token(CloudTokenBody(token=credential, enable_sync=True),
                            background_tasks, current_user=current_user, db=db)


@router.post("/api/sync/heal")
def heal_sync_outbox(
    current_user: dict = Depends(require_business_owner),
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
    from core.sync import tombstones
    tombstones.lock_business(db, business_id)

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
                raise HTTPException(426, "The server needs an update for sync entity: " + change.entity)

            data = dict(change.payload or {})
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
            if change.entity in {"supplier_payments", "customer_refunds", "customer_credit_allocations"}:
                data["operator_id"] = business_id

            existing = None
            uid_val = data.get("uid")

            # Database-local integer IDs never establish cross-device identity.
            if hasattr(model_cls, "uid"):
                if uid_val:
                    existing = db.query(model_cls).filter(model_cls.uid == uid_val).populate_existing().with_for_update().first()
                elif data.get("id") is not None:
                    existing = db.query(model_cls).filter(model_cls.id == change.entity_id).first()
                if existing is None and not uid_val:
                    rejected.append({"entity": change.entity, "row_id": change.entity_id,
                                     "reason": "A durable UID is required; update or repair the sending device"})
                    processed_count += 1
                    continue
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
                try:
                    deleted_at = tombstones.delete_version(data)
                    if deleted_at is None or deleted_at > utc_now() + timedelta(minutes=5):
                        raise ValueError("Deletion requires a valid, current version timestamp")
                    if existing and tombstones.normalized_version(getattr(existing, "updated_at", None)) is not None \
                            and tombstones.normalized_version(existing.updated_at) > deleted_at:
                        skipped.append({"entity": change.entity, "row_id": change.entity_id, "reason": "newer record kept; stale deletion"})
                        continue
                    with db.begin_nested():
                        deleted = tombstones.apply_remote_delete(db, business_id, change.entity, uid_val, deleted_at, existing)
                    if not deleted:
                        skipped.append({"entity": change.entity, "row_id": change.entity_id, "reason": "newer retained deletion kept"})
                        continue
                    processed_count += 1
                    ent_name = entity_map.get(change.entity)
                    if ent_name:
                        entities_to_broadcast.add(ent_name)
                except ValueError as exc:
                    rejected.append({"entity": change.entity, "row_id": change.entity_id, "reason": str(exc)})
                    processed_count += 1
                continue

            # INSERT / UPDATE operations
            # Conflict Check: compare updated_at timestamps if available
            local_updated_at_str = data.get("updated_at")
            local_updated_at = _parse_dt(local_updated_at_str)
            if not tombstones.check_upsert(db, business_id, change.entity, uid_val, local_updated_at):
                skipped.append({"entity": change.entity, "row_id": change.entity_id, "reason": "retained newer deletion"})
                continue

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

            # Resolve FKs via the parent's durable uid (shared helper — same logic
            # as the pull-apply worker). If a parent_uid is present but the parent
            # row isn't in this DB yet, the child is DEFERRED rather than written
            # with the source-DB integer id (wrong-row / orphan); it re-applies on
            # a later sync once the parent exists.
            if resolve_parent_fk_uids(db, model_cls, data,
                business_id=business_id,
                require_uid=True,
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

            from core.sync.protected_fields import protect_history
            try:
                protect_history(change.entity, data, existing)
            except ValueError as exc:
                rejected.append({"entity": change.entity, "row_id": change.entity_id, "reason": str(exc)})
                processed_count += 1
                continue
            if existing and local_updated_at and _parse_dt(existing.updated_at) == local_updated_at \
                    and change.entity in _apply_hooks.FINANCIAL_ENTITIES \
                    and _apply_hooks.payloads_differ(data, _apply_hooks.row_to_dict(existing)):
                _apply_hooks.log_financial_conflict(db, business_id=business_id,
                    entity=change.entity, entity_id=change.entity_id, incoming=data,
                    existing_row=existing, incoming_updated_at=local_updated_at,
                    existing_updated_at=local_updated_at, log_prefix="sync/push")
                rejected.append({"entity": change.entity, "row_id": change.entity_id, "reason": "Equal-version financial conflict requires review"})
                processed_count += 1
                continue
            # Apply fields to model instance
            target_obj = existing if existing else model_cls()

            # Per-row SAVEPOINT: one bad row (e.g. a duplicate uid whose data is
            # already on the cloud, or a transient FK) must NOT abort the whole
            # batch and stall the outbox forever (the "N pending" loop). We roll
            # back just that row and keep going. A duplicate/integrity row is
            # ACKed (counted processed) so the client stops re-sending it — its
            # data is already present on the destination.
            try:
                with db.begin_nested():
                    # Compare resolved local relationships, not source-database IDs.
                    # Only records ready to apply can produce an overwrite conflict.
                    if existing and local_updated_at:
                        cloud_updated_at = _parse_dt(getattr(existing, "updated_at", None))
                        _apply_hooks.log_financial_conflict(db, business_id=business_id,
                            entity=change.entity, entity_id=change.entity_id, incoming=data,
                            existing_row=existing, incoming_updated_at=local_updated_at,
                            existing_updated_at=cloud_updated_at, log_prefix="sync/push")
                        _apply_hooks.log_master_data_conflict(db, business_id=business_id,
                            entity=change.entity, entity_id=change.entity_id, incoming=data,
                            existing_row=existing, incoming_updated_at=local_updated_at,
                            existing_updated_at=cloud_updated_at, resolution="local_won", log_prefix="sync/push")
                    for key, val in data.items():
                        if key in model_cls.__table__.columns:
                            col_type = model_cls.__table__.columns[key].type
                            if hasattr(col_type, "python_type") and col_type.python_type == datetime and val:
                                val = _parse_dt(val)
                            setattr(target_obj, key, val)
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
                        from core.sync import inbox
                        receipt = inbox.remember(db, business_id=business_id, entity=change.entity,
                            record=dict(data, _sync_repair_only=True), reason="hook-failed", error="; ".join(_hook.errors))
                        if receipt is None:
                            raise RuntimeError("Derived-state repair could not be retained")
                        db.flush()
                if _hook.ok:
                    processed_count += 1
                    from database.models import SyncInbox
                    for repair in db.query(SyncInbox).filter(SyncInbox.business_id == business_id,
                            SyncInbox.entity == change.entity, SyncInbox.uid == uid_val,
                            SyncInbox.reason == "hook-failed", SyncInbox.applied_at.is_(None)).all():
                        repair.applied_at = utc_now()
                        repair.error = None
                else:
                    deferred.append({"entity": change.entity, "row_id": change.entity_id,
                                     "uid": uid_val, "reason": "Derived financial state needs a successful repair"})
                ent_name = entity_map.get(change.entity)
                if ent_name:
                    entities_to_broadcast.add(ent_name)
            except (IntegrityError, InternalError, DataError, StatementError, ValueError, TypeError) as ie:
                if isinstance(ie, DBAPIError) and not isinstance(ie, (IntegrityError, InternalError, DataError)):
                    raise  # Connection/operational failures must retry, never acknowledge unprocessed records.
                # C-7. A Postgres TRIGGER that fires `RAISE EXCEPTION` — the
                # line-item overfill guard, database/migration.py:912 — is
                # SQLSTATE P0001, i.e. psycopg2.errors.RaiseException, which is a
                # subclass of InternalError and NOT of IntegrityError. SQLite's
                # half of the same guard uses RAISE(ABORT), which IS an
                # IntegrityError, so this handler caught it locally and every
                # test passed. On the cloud the row escaped to the batch-level
                # `except Exception` below, the whole push answered 500, and the
                # device re-sent the identical poisoned batch for ever.
                #
                # The SAVEPOINT above has already rolled this row back, so the
                # session is usable and the row is a row-level refusal like any
                # other: ack it (M-13) so the outbox drains, and report it.
                #
                # Only SQLSTATE class P0 (PL/pgSQL RAISE) qualifies. Catching
                # InternalError wholesale would swallow 25P02
                # InFailedSqlTransaction, which every remaining row in the batch
                # raises once the connection is genuinely sick — acking those
                # would discard the rest of the batch instead of retrying it.
                if isinstance(ie, InternalError) and not str(
                        getattr(ie.orig, "pgcode", "")).startswith("P0"):
                    raise
                deduped = "skipped"
                try:
                    if uid_val and hasattr(model_cls, "uid"):
                        dup = db.query(model_cls).filter(model_cls.uid == uid_val).first()
                        if dup is not None and _record_belongs_to_business(db, change.entity, dup, business_id):
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
                    logger.info(
                        "sync/push: %s.id=%s integrity-deduped by uid (%s): %s",
                        change.entity, change.entity_id, deduped, getattr(ie, "orig", ie),
                    )
                else:
                    _apply_hooks.log_apply_failure(
                        db, business_id=business_id, entity=change.entity,
                        entity_id=change.entity_id, payload=data, error=ie,
                        log_prefix="sync/push",
                    )
                    rejected.append({"entity": change.entity, "row_id": change.entity_id,
                                     "uid": uid_val,
                                     "reason": str(getattr(ie, "orig", ie)).strip().splitlines()[0]})
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


def parse_cursor(cursor_str: Optional[str]) -> tuple[Optional[datetime], Dict[str, dict]]:
    """Parse a sync cursor into (global_timestamp, per_table_cursors).

    Accepts:
      - None / empty: (None, {})
      - cursor:<urlsafe_base64_json> or raw JSON string
      - ISO datetime string (fallback for legacy sync clients)
    """
    if not cursor_str:
        return None, {}
    s = str(cursor_str).strip()
    if s.startswith("cursor:"):
        try:
            raw = base64.urlsafe_b64decode(s[7:].encode("ascii")).decode("utf-8")
            data = json.loads(raw)
            ts = _parse_dt(data.get("ts"))
            return ts, data.get("tables", {})
        except Exception:
            pass
    elif s.startswith("{"):
        try:
            data = json.loads(s)
            ts = _parse_dt(data.get("ts"))
            return ts, data.get("tables", {})
        except Exception:
            pass
    # Legacy ISO datetime string
    dt = _parse_dt(s)
    return dt, {}


def encode_cursor(global_ts: datetime, table_cursors: Dict[str, dict]) -> str:
    """Encode global_timestamp and per-table cursors into a durable cursor string."""
    payload = {
        "v": 1,
        "ts": global_ts.isoformat(),
        "tables": table_cursors,
    }
    raw = json.dumps(payload, separators=(",", ":"))
    return "cursor:" + base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


@router.get("/api/sync/pull")
def pull_changes(
    last_sync_at: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
    protocol: int = 1,
    current_user: dict = Depends(require_business_owner),
    _plan: dict = Depends(require_plan("pro")),   # 402 for free plan when SUBSCRIPTION_ENFORCED=1
    db: Session = Depends(get_db),
):
    """
    Cloud Endpoint. Returns updates scoped to user's business_id that
    occurred after `last_sync_at` / `cursor`.

    `limit` caps rows PER TABLE and is opt-in. When it truncates anything the
    response carries `has_more: true` and names the truncated tables, so the
    caller knows to pull again rather than assume it has the whole window.

    Callers must choose deliberately:

    * The **sync worker** sends a limit. Without one, a first pull (no
      `last_sync_at` → 1970) asks for every row of every table inside a 10 s
      timeout, times out, correctly declines to advance the cursor, and repeats
      that forever. A livelock, not data loss — but the device never converges.
    * The **parity audit** must NOT send one. It judges whether a local row is
      absent from the cloud, and a truncated snapshot would have it invent
      MISSING rows and queue repairs for data that is already there — the same
      absent-vs-unread confusion `failed_tables` exists to prevent.
    """
    business_id = _resolve_business_id_by_username(current_user, db, require_public_id=True)
    if protocol == 2:
        from database.change_feed import pull_feed
        return pull_feed(db, business_id, cursor or last_sync_at, max(1, min(limit or 1000, 5000)))
    if limit is not None or cursor or (last_sync_at and not last_sync_at.startswith("1970-01-01")):
        raise HTTPException(426, "Sync protocol 2 is required. Update this device; queued data and the pull cursor are retained.")
    request_start_dt = datetime.now(timezone.utc)
    cutoff_dt = request_start_dt.replace(tzinfo=None)

    raw_cursor = cursor or last_sync_at
    last_sync_dt, table_cursors = parse_cursor(raw_cursor)
    if last_sync_dt is None:
        last_sync_dt = datetime(1970, 1, 1)

    if limit is not None:
        limit = max(1, min(int(limit), 5000))

    changes: Dict[str, List[dict]] = {}
    failed_tables: List[dict] = []
    has_more = False
    truncated_tables: List[str] = []
    next_table_cursors: Dict[str, dict] = {}

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

            # Upper bound by snapshot boundary (TS-02)
            if "updated_at" in cols:
                query = query.filter(model_cls.updated_at <= cutoff_dt)

            # Apply lexicographical cursor (TS-01) or timestamp filter
            if table_name in table_cursors and "updated_at" in cols:
                tbl_info = table_cursors[table_name]
                tbl_ts = _parse_dt(tbl_info.get("t") or tbl_info.get("ts"))
                tbl_id = tbl_info.get("id")
                if tbl_ts:
                    if tbl_id is not None and "id" in cols:
                        query = query.filter(
                            or_(
                                model_cls.updated_at > tbl_ts,
                                and_(model_cls.updated_at == tbl_ts, model_cls.id > int(tbl_id))
                            )
                        )
                    else:
                        query = query.filter(model_cls.updated_at > tbl_ts)
            elif "updated_at" in cols:
                query = query.filter(model_cls.updated_at > last_sync_dt)

            # ── PAGE CAP ──────────────────────────────────────────────────────
            # Opt-in. `limit=None` keeps the historical unbounded behaviour,
            # which the parity audit REQUIRES: it decides whether a local row is
            # absent on the cloud, and a truncated snapshot would make it invent
            # MISSING rows (the same class of error `failed_tables` exists to
            # prevent — see rule 33).
            #
            # The sync worker sends a limit because it must not: a first-ever
            # pull has `last_sync_at` unset, which resolves to 1970 and selects
            # EVERY row of all %d tables in one unbounded response — against a
            # 10 s client timeout. (The parity call to this same endpoint uses
            # 180 s, which is the clearest sign the 10 s path was never sized for
            # a wide window.) The result was not data loss but a livelock: the
            # request times out, the cursor correctly does not advance, and the
            # next cycle attempts exactly the same impossible pull.
            #
            # Ordering by updated_at makes the pages deterministic, so the
            # client's cursor advances through the backlog instead of re-reading
            # the same head slice forever.
            if limit and "updated_at" in cols:
                if "id" in cols:
                    query = query.order_by(model_cls.updated_at.asc(), model_cls.id.asc())
                else:
                    query = query.order_by(model_cls.updated_at.asc())
                rows = query.limit(limit + 1).all()
                if len(rows) > limit:
                    rows = rows[:limit]
                    has_more = True
                    truncated_tables.append(table_name)
                    last_r = rows[-1]
                    next_table_cursors[table_name] = {
                        "t": last_r.updated_at.isoformat() if last_r.updated_at else cutoff_dt.isoformat(),
                        "id": getattr(last_r, "id", None)
                    }
                elif rows:
                    next_table_cursors[table_name] = {
                        "t": cutoff_dt.isoformat(),
                        "id": getattr(rows[-1], "id", None)
                    }
            else:
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

    if has_more:
        logger.info(
            "sync/pull: biz=%s truncated at limit=%s in %s table(s) %s — "
            "has_more=true, the client must pull again to drain the backlog.",
            business_id, limit, len(truncated_tables), truncated_tables,
        )

    # Determine safe global watermark for next cursor
    if has_more:
        _ts_candidates = []
        for tname in truncated_tables:
            if tname in next_table_cursors and next_table_cursors[tname].get("t"):
                t_dt = _parse_dt(next_table_cursors[tname]["t"])
                if t_dt:
                    _ts_candidates.append(t_dt)
        next_global_ts = min(_ts_candidates) if _ts_candidates else last_sync_dt
    else:
        next_global_ts = cutoff_dt

    next_cursor = encode_cursor(next_global_ts, next_table_cursors if has_more else {})

    return {
        "pulled_at": request_start_dt.isoformat(),
        "cursor": next_cursor,
        "changes": changes,
        # Rule 33: the receiver must be able to tell "no rows" from "not read".
        "failed_tables": failed_tables,
        # …and neither of those from "read, but there is more". A caller that
        # advances its cursor on a truncated page skips everything past the cap.
        "has_more": has_more,
        "truncated_tables": truncated_tables,
    }


@router.get("/api/sync/queue-depth")
def get_queue_depth(
    current_user: dict = Depends(require_business_owner),
    db: Session = Depends(get_db),
):
    """
    Local Endpoint. Returns number of pending queue items and latest execution stats.
    """
    business_id = _resolve_business_id_by_username(current_user, db)

    # Query pending items — fetch entity column too for breakdown
    status_errors = []
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
        status_errors.append("Upload queue could not be read")
        pending_count  = None
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
        status_errors.append("Sync history could not be read")
        last_log = None

    # Instant Pull state, reported from the listener thread rather than from the
    # client's own preference flag. The UI must only claim "Instant Pull active"
    # when a cloud event stream is genuinely attached — otherwise it hides the
    # countdown timer for a mechanism that is not actually running.
    try:
        from services import cloud_listener
        instant_pull = cloud_listener.get_state(business_id)
    except Exception:
        instant_pull = {"running": False, "connected": False}

    # Inbox depth — the PULL-side mirror of the outbox numbers above. Without it
    # the console reported only half the picture: a device could show a clean,
    # empty outbox while rows the cloud sent sat un-applied and invisible.
    try:
        from core.sync import inbox as _inbox_mod
        inbox_stats = _inbox_mod.stats(db, business_id)
    except Exception:
        status_errors.append("Download inbox could not be read")
        inbox_stats = {"pending_count": None, "entity_counts": {}, "status_error": "Download inbox could not be read",
                       "stuck_count": None, "deferred_count": None, "rejected_count": None}

    from services.control_outbox import control_status
    from services import sync_worker
    from database.models import SyncCursor
    owner = db.query(User).filter(User.id == business_id).first()
    try:
        general = (json.loads(owner.settings or "{}").get("general") or {}) if owner else {}
        initial_restore_pending = general.get("sync_bootstrap_pending") is True
    except (ValueError, TypeError, AttributeError):
        status_errors.append("Business restore settings could not be read")
        initial_restore_pending = True  # Unreadable is not evidence of a completed restore.
    try:
        cursor = db.query(SyncCursor).filter(SyncCursor.business_id == business_id, SyncCursor.entity == "*").first()
        initialized = bool(cursor and (cursor.cursor_value or "").startswith("feed:v2:")) and not initial_restore_pending
    except Exception:
        status_errors.append("Download position could not be read")
        initialized = None
    try:
        control = control_status(db, business_id)
    except Exception:
        status_errors.append("Account update queue could not be read")
        control = {"pending": None, "failed": None, "status_error": "Account update queue could not be read"}
    from services import sync_retry
    retry_operations = sync_retry.snapshot(business_id)
    if retry_operations.get("storage", {}).get("blocked"):
        status_errors.append("Sync retry storage could not be read")
    return {
        "status_error": "; ".join(status_errors) or None,
        "readiness": {"state": "unknown" if status_errors else "restoring" if initial_restore_pending
                      else "attention" if inbox_stats.get("pending_count") else "ready"},
        "retry_operations": retry_operations,
        "pull": {"initialized": initialized,
                 "last_pull_at": cursor.updated_at.isoformat() if initialized and cursor.updated_at else None,
                 "initial_restore_pending": initial_restore_pending,
                 "has_more": business_id in sync_worker._PULL_MORE_PENDING},
        "control_outbox": control,
        "pending_count":  pending_count,
        "entity_counts":  entity_counts,   # {"invoices": 3, "customers": 1, ...}
        "inbox":          inbox_stats,
        "next_entity":    next_entity,      # entity currently at front of queue
        "last_sync_time": last_log.synced_at.isoformat() if last_log else None,
        "last_status":    "unknown" if status_errors else last_log.status if last_log else "idle",
        "last_error":     last_log.error  if last_log else None,
        "instant_pull":   instant_pull,
        "halt":           _halt_state(business_id),
    }


# ── Why sync stopped ─────────────────────────────────────────────────────────
# Precedence, most-actionable first. Two of these NEVER recover on their own.
_HALT_ORDER = (
    ("_PROTOCOL_BLOCKED", "protocol_upgrade_required", "update_device"),
    # (flag name, reason, how the owner fixes it)
    ("_SELF_SIGNED_REJECTED", "secret_mismatch", "relogin"),
    ("_PULL_AUTH_BLOCKED",    "auth_expired",    "relogin"),
    ("_PLAN_BLOCKED",         "plan_required",   "upgrade"),
    ("_OFFLINE_STATE",        "offline",         "wait"),
)


def _halt_state(business_id: int) -> dict:
    """Why the sync worker is not running for this business, or reason=None.

    THE GAP THIS CLOSES. The worker has four halt states and this endpoint
    exposed none of them — callers had only `last_error`, the newest SyncLog
    row. But every halt SHORT-CIRCUITS BEFORE WRITING A LOG, so once one is
    set no new row ever appears and the client replays the error that preceded
    it, indefinitely. That is how a panel showed "Cloud sync requires the Pro
    plan" for hours after the plan was already Pro.

    `last_error` answers "what went wrong last time we tried". This answers
    "are we even trying", which is a different question and the one an owner is
    actually asking.

    These are per-process, in-memory flags: after a restart they are empty and
    this reports healthy until the next cycle re-detects the condition. That is
    correct — a restart genuinely clears the worker's belief, and re-detection
    takes one interval.
    """
    try:
        from services import sync_worker as _sw
    except Exception:
        return {"reason": None, "recoverable_by": None}

    for attr, reason, fix in _HALT_ORDER:
        # Truthiness, not key presence: `_OFFLINE_STATE` is explicitly set to
        # False when the cloud comes back, so `bid in dict` would report an
        # outage forever after the first one.
        if getattr(_sw, attr, {}).get(business_id):
            return {"reason": reason, "recoverable_by": fix}

    return {"reason": None, "recoverable_by": None}


@router.get("/api/sync/conflicts")
def list_sync_conflicts(
    include_resolved: bool = False,
    limit: int = 100,
    current_user: dict = Depends(require_business_owner),
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
    current_user: dict = Depends(require_business_owner),
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
    pull: bool = False,
    current_user: dict = Depends(require_business_owner),
    db: Session = Depends(get_db),
):
    """
    Local Endpoint. Manually schedules immediate execution of the background sync worker.

    `pull=false` (default) pushes the local outbox only — this is what the
    "Push to Cloud" control needs.

    `pull=true` ALSO runs a cloud → local pull in the same run. The "Pull from
    Cloud Now" control must send this: without it the button pushed the outbox
    and never fetched cloud-authored rows, so edits made on another device or on
    the web dashboard stayed invisible until the periodic pull interval elapsed.
    """
    from services.sync_worker import trigger_sync_run
    business_id = _resolve_business_id_by_username(current_user, db)
    from services.sync_policy import cloud_egress_allowed
    if db.get_bind().dialect.name == "sqlite" and not cloud_egress_allowed(business_id):
        raise HTTPException(409, "This business is set to Local-only. Enable Local + Cloud before requesting synchronization.")
    background_tasks.add_task(trigger_sync_run, business_id, pull=pull)
    return {"status": "triggered", "business_id": business_id, "pull": pull}


@router.get("/api/sync/outbox/details")
def get_outbox_details(
    limit: int = 50,
    current_user: dict = Depends(require_business_owner),
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
                    # NOTE: SyncQueue has no retry_count column. This previously
                    # read getattr(r, "retry_count", 0), which always fell back
                    # to 0 and rendered a permanently-zero "Retries" column in
                    # the Ops table. Report the real, derivable state instead.
                    "status": "failed" if r.error else "queued",
                    "last_error": r.error,
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.warning("sync/outbox/details failed for biz=%s: %s", business_id, e)
        return {"count": 0, "items": []}


@router.get("/api/sync/inbox/details")
def get_inbox_details(
    limit: int = 50,
    current_user: dict = Depends(require_business_owner),
    db: Session = Depends(get_db),
):
    """Rows the cloud sent that this database has not been able to apply.

    The pull-side counterpart of `/api/sync/outbox/details`. Its absence is why
    the two failure modes it reports went unnoticed for so long: a DEFERRED row
    was dropped without a trace, and a REJECTED one produced a CRITICAL log line
    saying it "needs a human" — in a log no human was reading.

    `reason` distinguishes them, because they need different responses:
      deferred — waiting on a parent. Usually resolves itself once the parent
                 syncs; only worth acting on if it is old.
      rejected — the apply raised. Read `last_error`; this one needs a decision.
    """
    from database.models import SyncInbox
    from core.sync import inbox as _inbox_mod

    business_id = _resolve_business_id_by_username(current_user, db)
    try:
        rows = (
            db.query(SyncInbox)
            .filter(SyncInbox.business_id == business_id,
                    SyncInbox.applied_at.is_(None))
            .order_by(SyncInbox.created_at.asc())
            .limit(max(1, min(limit, 500)))
            .all()
        )
        return {
            "count": len(rows),
            "stats": _inbox_mod.stats(db, business_id),
            "items": [
                {
                    "id": r.id,
                    "entity": r.entity,
                    "uid": r.uid,
                    "remote_id": r.remote_id,
                    "reason": r.reason,
                    "attempts": r.attempts,
                    # Past this it is no longer retried automatically. It is NOT
                    # deleted — it is waiting for the Retry button below.
                    "stuck": r.attempts >= _inbox_mod.MAX_AUTO_ATTEMPTS,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "next_attempt_at": r.next_attempt_at.isoformat() if r.next_attempt_at else None,
                    "last_error": r.error,
                }
                for r in rows
            ],
        }
    except Exception as e:
        logger.warning("sync/inbox/details failed for biz=%s: %s", business_id, e)
        return {"count": 0, "items": [], "stats": {}}


@router.post("/api/sync/inbox/{inbox_id}/retry")
def retry_inbox_item(
    inbox_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_business_owner),
    db: Session = Depends(get_db),
):
    """Clear one held row's backoff and re-attempt it now.

    Scheduling the run is the part that matters — the outbox equivalent shipped
    once WITHOUT it and was a button that blanked an error message and did
    nothing else. Same mistake is available here, so: reset, then trigger.
    """
    from core.sync import inbox as _inbox_mod
    business_id = _resolve_business_id_by_username(current_user, db)
    if not _inbox_mod.requeue(db, business_id, inbox_id):
        raise HTTPException(status_code=404,
                            detail="Inbox item not found or already applied")

    from services.sync_worker import trigger_sync_run
    background_tasks.add_task(trigger_sync_run, business_id, pull=True)
    return {"ok": True, "id": inbox_id, "requeued": True}


@router.post("/api/sync/outbox/{queue_id}/retry")
def retry_outbox_item(
    queue_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_business_owner),
    db: Session = Depends(get_db),
):
    """Clear the error on one outbox item and immediately re-attempt delivery.

    Clearing `error` alone is not a retry: the worker selects purely on
    `synced_at IS NULL`, so the row was already going to be picked up — the
    button just blanked the message and left the user waiting a full
    `sync_interval` with no visible effect. Scheduling the sync run is what
    makes "Retry Item" mean what it says.
    """
    business_id = _resolve_business_id_by_username(current_user, db)
    row = (
        db.query(SyncQueue)
        .filter(SyncQueue.id == queue_id, SyncQueue.business_id == business_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Outbox item not found")
    if row.synced_at is not None:
        return {"ok": True, "id": queue_id, "already_synced": True, "requeued": False}
    row.error = None
    db.commit()

    from services.sync_worker import trigger_sync_run
    background_tasks.add_task(trigger_sync_run, business_id)
    return {"ok": True, "id": queue_id, "requeued": True}


@router.post("/api/sync/parity")
def run_parity_check(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_business_owner),
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
    from services.sync_policy import cloud_egress_allowed
    if not cloud_egress_allowed(business_id):
        raise HTTPException(409, "A cloud audit requires Local + Cloud on this device.")

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
