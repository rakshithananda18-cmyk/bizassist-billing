"""
services/sync_worker.py
=======================
Phase 2 Background Sync worker.
Runs on SQLite local client to push local mutations to Cloud Postgres and pull cloud changes.
"""

import logging
import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.db import SessionLocal, engine, sync_disabled_var
from database.models import (
    User, SyncQueue, SyncLog, ConflictLog,
    Base, Customer, Vendor, Product, Invoice, InvoiceLineItem,
    Inventory, Payment, StockLedger, ProductBarcode, BusinessSettings,
    InvoicePayment, SharedLedger, Expense, Godown, StockTransfer,
    StockTransferLineItem, PurchaseInvoice, PurchaseInvoiceLineItem,
    PurchaseOrder, PurchaseOrderLineItem, AlertConfig, RateLimitConfig
)
from services.auth import create_access_token

logger = logging.getLogger("bizassist.sync_worker")

CLOUD_URL = os.environ.get("CLOUD_API_URL") or os.environ.get("VITE_API_URL") or "https://rakshit-dev-bizassist.hf.space"

# Keep track of last execution times in-memory
_LAST_RUN: Dict[int, datetime] = {}

# IMPORTANT: The local backend and HF Space MUST share the same JWT_SECRET env variable.
# If they differ, the sync worker's locally-signed tokens will be rejected by the cloud
# with HTTP 401 "Invalid token". Set JWT_SECRET to the same value in both:
#   - Local: backend/.env  -> JWT_SECRET=<your_secret>
#   - Cloud: HF Space -> Settings -> Secrets -> JWT_SECRET=<same_secret>


def _invalidate_cloud_token(business_id: int):
    """No-op placeholder — kept for future refresh logic."""
    pass

def _safe_broadcast(business_id: int, event: dict):
    from services.realtime import realtime_manager
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(realtime_manager.broadcast(business_id, event))
    except RuntimeError:
        # No running event loop in this thread, use asyncio.run
        try:
            asyncio.run(realtime_manager.broadcast(business_id, event))
        except Exception as e:
            logger.warning("[SYNC_WORKER] Failed to broadcast event: %s", e)
    except Exception as e:
        logger.warning("[SYNC_WORKER] Failed to broadcast event: %s", e)

# Model mapping to apply updates/inserts locally
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


def _row_to_dict(row) -> dict:
    if hasattr(row, "__dict__"):
        d = {k: v for k, v in row.__dict__.items() if k != "_sa_instance_state"}
    else:
        d = dict(row._mapping)
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def _parse_dt(dt_str) -> Optional[datetime]:
    if not dt_str:
        return None
    if isinstance(dt_str, datetime):
        return dt_str
    try:
        clean_str = str(dt_str).replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str)
    except Exception:
        return None


def run_hybrid_sync():
    """APScheduler recurring job. Runs every 5s on SQLite local backend."""
    if engine.dialect.name != "sqlite":
        # Cloud/Postgres does not sync from itself
        return

    db = SessionLocal()
    try:
        # Find all users
        users = db.query(User).all()
        for user in users:
            settings_str = user.settings
            if not settings_str:
                continue
            try:
                s = json.loads(settings_str)
                general = s.get("general", {})
                hosting_mode = general.get("hosting_mode")
                if hosting_mode != "hybrid":
                    continue

                # Check dynamic sync interval
                sync_interval = int(general.get("sync_interval", 30))
                business_id = user.id
                
                last_run = _LAST_RUN.get(business_id)
                now = datetime.utcnow()
                if last_run and (now - last_run).total_seconds() < sync_interval:
                    continue
                
                # Perform sync
                sync_business(db, user, sync_interval)
                _LAST_RUN[business_id] = now
            except Exception as e:
                logger.error("[SYNC_WORKER] Error checking settings for user %s: %s", user.username, e)
    finally:
        db.close()


def trigger_sync_run(business_id: int):
    """Flushes queue immediately for a specific business (called by endpoint)."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == business_id).first()
        if not user:
            logger.warning("[SYNC_WORKER] trigger_sync_run: business %s not found", business_id)
            return
        
        sync_business(db, user, force=True)
        _LAST_RUN[business_id] = datetime.utcnow()
    except Exception as e:
        logger.error("[SYNC_WORKER] Manual sync flush failed for business %s: %s", business_id, e)
    finally:
        db.close()


def sync_business(db: Session, user: User, interval: int = 30, force: bool = False):
    business_id = user.id
    logger.debug("[SYNC_WORKER] Running sync for business_id=%s", business_id)

    # 1. Probe cloud endpoint health
    try:
        resp = httpx.get(f"{CLOUD_URL}/health", timeout=3.0)
        if resp.status_code != 200 or resp.json().get("status") != "ok":
            raise Exception("Cloud health probe returned non-ok status")
    except Exception as e:
        logger.warning("[SYNC_WORKER] Cloud unreachable for business %s: %s", business_id, e)
        # Log offline status to sync_logs
        log = SyncLog(
            business_id=business_id,
            status="failed",
            error=f"Cloud unreachable: {e}",
            synced_at=datetime.utcnow()
        )
        db.add(log)
        db.commit()
        return

    # 2. Query next unsynced batch
    queue_items = (
        db.query(SyncQueue)
        .filter(SyncQueue.business_id == business_id, SyncQueue.synced_at.is_(None))
        .order_by(SyncQueue.id.asc())
        .limit(100)
        .all()
    )

    # Sign a JWT locally — requires JWT_SECRET to be THE SAME on both local and cloud.
    # If you see HTTP 401 errors, ensure both share the same JWT_SECRET env variable.
    token = create_access_token({
        "id": business_id,
        "user_id": user.id,
        "username": user.username,
        "business_name": user.business_name or "Local POS",
        "role": user.role or "enterprise"
    })
    headers = {"Authorization": f"Bearer {token}"}

    if queue_items:
        # Push to cloud
        changes = []
        for item in queue_items:
            payload_dict = None
            if item.payload:
                try:
                    payload_dict = json.loads(item.payload)
                except Exception:
                    pass
            changes.append({
                "entity": item.entity,
                "entity_id": item.entity_id,
                "operation": item.operation,
                "payload": payload_dict,
                "created_at": item.created_at.isoformat()
            })

        try:
            resp = httpx.post(f"{CLOUD_URL}/api/sync/push", json={"changes": changes}, headers=headers, timeout=10.0)
            if resp.status_code != 200 or resp.json().get("status") != "success":
                raise Exception(f"HTTP {resp.status_code}: {resp.text}")
            
            # Pushed successfully! Mark synced
            now = datetime.utcnow()
            for item in queue_items:
                item.synced_at = now
                item.error = None
            
            log = SyncLog(
                business_id=business_id,
                status="success",
                synced_at=now
            )
            db.add(log)
            db.commit()
            logger.info("[SYNC_WORKER] Successfully pushed %s changes for business_id=%s", len(queue_items), business_id)
        except Exception as e:
            err_msg = str(e)
            logger.error("[SYNC_WORKER] Push failed for business_id=%s: %s", business_id, e)
            
            # If 401, invalidate cached token so next run fetches a fresh one
            if "401" in err_msg:
                _invalidate_cloud_token(business_id)
            
            # Store error on the first pending queue item
            queue_items[0].error = f"Push failed: {err_msg}"
            log = SyncLog(
                business_id=business_id,
                status="failed",
                error=f"Push failed: {err_msg}",
                synced_at=datetime.utcnow()
            )
            db.add(log)
            db.commit()
            # Abort this sync cycle to keep sequence order
            return

    # 3. Pull updates from cloud
    try:
        # Find latest successful sync timestamp before this run
        last_success = (
            db.query(SyncLog)
            .filter(SyncLog.business_id == business_id, SyncLog.status == "success")
            .order_by(SyncLog.synced_at.desc())
            .offset(1 if queue_items else 0)
            .first()
        )
        last_sync_str = last_success.synced_at.isoformat() if last_success else None

        params = {}
        if last_sync_str:
            params["last_sync_at"] = last_sync_str

        resp = httpx.get(f"{CLOUD_URL}/api/sync/pull", params=params, headers=headers, timeout=10.0)
        if resp.status_code == 401:
            _invalidate_cloud_token(business_id)
            raise Exception(f"HTTP 401: token rejected by cloud — will refresh next cycle")
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text}")
        
        pulled = resp.json().get("changes", {})
        total_pulled = sum(len(v) for v in pulled.values())
        
        if total_pulled > 0:
            logger.info("[SYNC_WORKER] Pulling %s changes from cloud for business_id=%s", total_pulled, business_id)
            
            # Temporarily disable sync triggers so writes are not re-queued
            token_var = sync_disabled_var.set(True)
            try:
                for table_name, records in pulled.items():
                    model_cls = _MODEL_MAP.get(table_name)
                    if not model_cls:
                        continue
                    
                    for record in records:
                        rec_id = record.get("id")
                        if not rec_id:
                            continue
                        
                        # Find local matching record
                        existing = db.query(model_cls).filter(model_cls.id == rec_id).first()
                        
                        # Apply Last-Write-Wins (LWW) locally
                        cloud_updated_at = _parse_dt(record.get("updated_at"))
                        
                        if existing and hasattr(existing, "updated_at") and existing.updated_at and cloud_updated_at:
                            local_updated_at = _parse_dt(existing.updated_at)
                            if local_updated_at and local_updated_at > cloud_updated_at:
                                # Local version is newer, skip cloud version
                                continue
                        
                        # Apply field updates
                        target_obj = existing if existing else model_cls()
                        for key, val in record.items():
                            if key in model_cls.__table__.columns:
                                col_type = model_cls.__table__.columns[key].type
                                if hasattr(col_type, "python_type") and col_type.python_type == datetime:
                                    if val:
                                        val = _parse_dt(val)
                                setattr(target_obj, key, val)
                        
                        if not existing:
                            db.add(target_obj)
                
                db.commit()
                
                # Broadcast local SSE sync triggers to update browser tabs!
                entities_to_broadcast = set()
                for table_name, records in pulled.items():
                    if records:
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
                        entity_name = entity_map.get(table_name)
                        if entity_name:
                            entities_to_broadcast.add(entity_name)
                
                for ent in entities_to_broadcast:
                    _safe_broadcast(business_id, {"type": "sync.trigger", "entity": ent})
            finally:
                sync_disabled_var.reset(token_var)
                
    except Exception as e:
        logger.error("[SYNC_WORKER] Pull failed for business_id=%s: %s", business_id, e)
        # Log pull failure
        log = SyncLog(
            business_id=business_id,
            status="failed",
            error=f"Pull failed: {e}",
            synced_at=datetime.utcnow()
        )
        db.add(log)
        db.commit()
