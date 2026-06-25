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

import logging
import json
from datetime import datetime, timezone
from typing import Any, Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.db import get_db, sync_disabled_var
from services.auth import get_active_user
from database.models import (
    Base, User, Customer, Vendor, Product, Invoice, InvoiceLineItem,
    Inventory, Payment, ConflictLog, SyncLog, SyncQueue,
    StockLedger, ProductBarcode, BusinessSettings, InvoicePayment,
    SharedLedger, Expense, Godown, StockTransfer, StockTransferLineItem,
    PurchaseInvoice, PurchaseInvoiceLineItem, PurchaseOrder, PurchaseOrderLineItem,
    AlertConfig, RateLimitConfig
)

router = APIRouter()
logger = logging.getLogger("bizassist.routes.sync")

# Mapping from table name to SQLAlchemy ORM model class
_MODEL_MAP: Dict[str, Any] = {
    "users": User,
    "customers": Customer,
    "vendors": Vendor,
    "products": Product,
    "invoices": Invoice,
    "invoice_line_items": InvoiceLineItem,
    "inventory": Inventory,
    "payments": Payment,
    "stock_ledger": StockLedger,
    "product_barcodes": ProductBarcode,
    "business_settings": BusinessSettings,
    "invoice_payments": InvoicePayment,
    "shared_ledger": SharedLedger,
    "expenses": Expense,
    "godowns": Godown,
    "stock_transfers": StockTransfer,
    "stock_transfer_line_items": StockTransferLineItem,
    "purchase_invoices": PurchaseInvoice,
    "purchase_invoice_line_items": PurchaseInvoiceLineItem,
    "purchase_orders": PurchaseOrder,
    "purchase_order_line_items": PurchaseOrderLineItem,
    "alert_configs": AlertConfig,
    "rate_limit_configs": RateLimitConfig,
}


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


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@router.post("/api/sync/push")
def push_changes(
    payload: PushPayload,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """
    Cloud Endpoint. Receives local changes and applies them to PostgreSQL.
    Enforces multi-tenant scoping and applies Last-Write-Wins (LWW) resolution.
    """
    business_id = int(current_user.get("parent_business_id") or current_user.get("id"))
    logger.info("sync/push: business_id=%s received %s changes", business_id, len(payload.changes))

    # Temporarily disable trigger hooks to prevent queuing writes back on the cloud
    token = sync_disabled_var.set(True)
    processed_count = 0
    entities_to_broadcast = set()

    entity_map = {
        "customers": "party",
        "vendors": "party",
        "products": "product",
        "invoices": "invoice",
        "payments": "payment",
        "invoice_payments": "payment",
        "purchase_invoices": "purchase",
        "godowns": "godown",
        "purchase_orders": "order",
        "stock_transfers": "stock",
        "stock_ledger": "stock",
        "business_settings": "settings",
    }

    try:
        for change in payload.changes:
            model_cls = _MODEL_MAP.get(change.entity)
            if not model_cls:
                logger.warning("sync/push: unknown entity %s", change.entity)
                continue

            # Scope check the existing record
            existing = db.query(model_cls).filter(model_cls.id == change.entity_id).first()
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

            # Enforce business_id in payload
            data = change.payload or {}
            if "business_id" in data:
                data["business_id"] = business_id

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

            if existing and hasattr(existing, "updated_at") and existing.updated_at and local_updated_at:
                cloud_updated_at = _parse_dt(existing.updated_at)
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
                        resolved_at=datetime.utcnow(),
                        resolution="cloud_won"
                    )
                    db.add(conflict)
                    logger.info("sync/push: LWW conflict resolved (cloud won) for %s.id=%s", change.entity, change.entity_id)
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

            if not existing:
                db.add(target_obj)
            db.flush()
            processed_count += 1
            ent_name = entity_map.get(change.entity)
            if ent_name:
                entities_to_broadcast.add(ent_name)

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
    db: Session = Depends(get_db),
):
    """
    Cloud Endpoint. Returns updates scoped to user's business_id that
    occurred after `last_sync_at`.
    """
    business_id = int(current_user.get("parent_business_id") or current_user.get("id"))
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
    business_id = int(current_user.get("parent_business_id") or current_user.get("id"))
    
    # Query pending counts
    try:
        pending_count = (
            db.query(SyncQueue)
            .filter(SyncQueue.business_id == business_id, SyncQueue.synced_at.is_(None))
            .count()
        )
    except Exception:
        pending_count = 0

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
        "pending_count": pending_count,
        "last_sync_time": last_log.synced_at.isoformat() if last_log else None,
        "last_status": last_log.status if last_log else "idle",
        "last_error": last_log.error if last_log else None,
    }


@router.post("/api/sync/flush")
def flush_sync_queue(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
):
    """
    Local Endpoint. Manually schedules immediate execution of the background sync worker.
    """
    from services.sync_worker import trigger_sync_run
    business_id = int(current_user.get("parent_business_id") or current_user.get("id"))
    background_tasks.add_task(trigger_sync_run, business_id)
    return {"status": "triggered", "business_id": business_id}
