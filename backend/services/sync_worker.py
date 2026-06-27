"""
services/sync_worker.py
=======================
Phase 2 Background Sync worker — runs on the SQLite local client.

PUSH-ONLY by default: it pushes local mutations up to the cloud (backup /
local→cloud). It does **not** auto-pull cloud data down, because cloud data is
subscription-gated — a cloud→local data sync is an explicit user action
("Back up now") or part of a migration. The pull path still exists in
`sync_business(..., do_pull=True)` for those deliberate, gated cases.
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

# (R-2) Per-business pull cursor, expressed in the CLOUD's clock. We seed it from
# the cloud's own `pulled_at` response so the next `last_sync_at` we send is never
# compared across two machines' clocks — eliminating the skew that silently
# dropped freshly-updated cloud rows. In-memory: after a restart the first cycle
# falls back to the SyncLog-derived timestamp, then re-pins to the cloud clock.
_PULL_CURSOR: Dict[int, str] = {}

# (H-2) Remember the last logged connectivity state per business so we only write
# a SyncLog row on a state *change* (online↔offline), not every failed cycle.
_OFFLINE_STATE: Dict[int, bool] = {}

# IMPORTANT: The local backend and HF Space MUST share the same JWT_SECRET env variable.
# If they differ, the sync worker's locally-signed tokens will be rejected by the cloud
# with HTTP 401 "Invalid token". Set JWT_SECRET to the same value in both:
#   - Local: backend/.env  -> JWT_SECRET=<your_secret>
#   - Cloud: HF Space -> Settings -> Secrets -> JWT_SECRET=<same_secret>


def _invalidate_cloud_token(business_id: int):
    """No-op placeholder — kept for future refresh logic."""
    pass

def _safe_broadcast(business_id: int, event: dict):
    """Broadcast an SSE event from the sync-worker thread.

    (R-1) This runs in the APScheduler background thread, NOT the server loop.
    realtime_manager.broadcast_threadsafe marshals the coroutine onto the main
    loop via run_coroutine_threadsafe; the old asyncio.run() path created a
    throwaway loop whose events never reached the main-loop SSE consumers, so
    cloud→local pulls updated the DB but the browser UI never refreshed.
    """
    from services.realtime import realtime_manager
    try:
        if not realtime_manager.broadcast_threadsafe(business_id, event):
            # No main loop registered yet — last-resort fallback.
            asyncio.run(realtime_manager.broadcast(business_id, event))
    except Exception as e:
        logger.warning("[SYNC_WORKER] Failed to broadcast event: %s", e)

# (R-7) Single shared source — see database/sync_map.py
from database.sync_map import MODEL_MAP as _MODEL_MAP, ENTITY_BROADCAST_MAP, resolve_parent_fk_uids


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


def sync_business(db: Session, user: User, interval: int = 30, force: bool = False, do_pull: bool = False):
    business_id = user.id
    logger.debug("[SYNC_WORKER] Running sync for business_id=%s", business_id)

    # 1. Probe cloud endpoint health
    try:
        resp = httpx.get(f"{CLOUD_URL}/health", timeout=3.0)
        if resp.status_code != 200 or resp.json().get("status") != "ok":
            raise Exception("Cloud health probe returned non-ok status")
    except Exception as e:
        logger.warning("[SYNC_WORKER] Cloud unreachable for business %s: %s", business_id, e)
        # (H-2) Only record a SyncLog row on the online→offline transition, so an
        # extended outage doesn't append a row every interval (unbounded growth).
        if not _OFFLINE_STATE.get(business_id, False):
            log = SyncLog(
                business_id=business_id,
                status="failed",
                error=f"Cloud unreachable: {e}",
                synced_at=datetime.utcnow()
            )
            db.add(log)
            db.commit()
            _OFFLINE_STATE[business_id] = True
        return

    # Cloud is reachable — clear the offline flag so the next outage logs once.
    _OFFLINE_STATE[business_id] = False

    # 2. Query next unsynced batch
    queue_items = (
        db.query(SyncQueue)
        .filter(SyncQueue.business_id == business_id, SyncQueue.synced_at.is_(None))
        .order_by(SyncQueue.id.asc())
        .limit(100)
        .all()
    )

    token = create_access_token({
        "id": business_id,
        "user_id": user.id,
        "username": user.username,
        "public_id": user.public_id,
        "business_name": user.business_name or "Local POS",
        "role": user.role or "enterprise"
    })
    headers = {"Authorization": f"Bearer {token}"}

    if queue_items:
        # Push to cloud
        changes = []
        for item in queue_items:
            # Skip entities that aren't syncable (e.g. `users` — identity is never
            # synced as data). They'd be rejected by the cloud as "unknown entity";
            # mark them done so they drain from the queue instead of recycling.
            if item.entity not in _MODEL_MAP:
                item.synced_at = datetime.utcnow()
                continue
            payload_dict = None
            if item.payload:
                try:
                    payload_dict = json.loads(item.payload)
                except Exception as e:
                    # (R-6) A corrupt payload must NOT be pushed as null (the cloud
                    # would apply an empty/no-op write). Dead-letter the item and
                    # skip it so the rest of the batch still flows.
                    logger.warning(
                        "[SYNC_WORKER] Corrupt payload on queue id=%s (%s.%s) — dead-lettering: %s",
                        item.id, item.entity, item.entity_id, e,
                    )
                    item.error = f"Corrupt payload: {e}"
                    item.synced_at = datetime.utcnow()  # remove from the pending window
                    continue
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
            logger.info("[SYNC_WORKER] Successfully pushed %s changes for business_id=%s", len(changes), business_id)
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

    # The hybrid worker is PUSH-ONLY (local → cloud backup). Cloud data is
    # subscription-gated, so we never auto-pull it down. A cloud→local data sync
    # happens only on explicit user action ("Back up now") or during a migration.
    if not do_pull:
        return

    # 3. Pull updates from cloud  (only when explicitly requested, do_pull=True)
    try:
        # (R-2) Use the CLOUD-clock cursor captured from the previous pull's
        # `pulled_at`. Comparing a cloud-issued timestamp against cloud rows'
        # `updated_at` removes the local-vs-cloud clock skew that previously
        # caused freshly-updated cloud rows to be silently skipped. On first run
        # after a restart we fall back to the last successful SyncLog timestamp.
        last_sync_str = _PULL_CURSOR.get(business_id)
        if not last_sync_str:
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

        _resp_json = resp.json()
        pulled = _resp_json.get("changes", {})
        # Advance the cloud-clock cursor to the server's own pull timestamp.
        _cloud_cursor = _resp_json.get("pulled_at")
        if _cloud_cursor:
            _PULL_CURSOR[business_id] = _cloud_cursor
        total_pulled = sum(len(v) for v in pulled.values())
        
        if total_pulled > 0:
            logger.info("[SYNC_WORKER] Pulling %s changes from cloud for business_id=%s", total_pulled, business_id)
            
            # Temporarily disable sync triggers so writes are not re-queued
            token_var = sync_disabled_var.set(True)
            try:
                # Apply parent/master tables before child tables so the FK-uid
                # resolution below always finds the parent within the same batch
                # (parent and child are typically created and pulled together).
                # Without this, a child could process first, fail to resolve its
                # parent, and get deferred unnecessarily. Stable sort keeps the
                # server's original order within each rank.
                _child_last = (
                    "invoice_line_items", "purchase_order_line_items",
                    "purchase_invoice_line_items", "invoice_payments",
                    "stock_transfer_line_items", "product_barcodes",
                    "stock_ledger", "shared_ledgers",
                )
                _ordered = sorted(pulled.items(), key=lambda kv: 1 if kv[0] in _child_last else 0)
                for table_name, records in _ordered:
                    model_cls = _MODEL_MAP.get(table_name)
                    if not model_cls:
                        continue
                    
                    for record in records:
                        rec_uid = record.get("uid")
                        rec_id = record.get("id")
                        if not rec_id and not rec_uid:
                            continue
                        
                        existing = None
                        if rec_uid and hasattr(model_cls, "uid"):
                            existing = db.query(model_cls).filter(model_cls.uid == rec_uid).first()
                        else:
                            if rec_id:
                                existing = db.query(model_cls).filter(model_cls.id == rec_id).first()
                        
                        # Apply Last-Write-Wins (LWW) locally
                        cloud_updated_at = _parse_dt(record.get("updated_at"))

                        if existing and hasattr(existing, "updated_at") and existing.updated_at:
                            # (R-5) If the cloud row carries no timestamp we cannot
                            # prove it is newer — do NOT clobber an existing local
                            # row with a timestamp-less version.
                            if not cloud_updated_at:
                                logger.debug(
                                    "[SYNC_WORKER] Skipping %s id=%s — cloud row has no updated_at, keeping local",
                                    table_name, rec_id,
                                )
                                continue
                            local_updated_at = _parse_dt(existing.updated_at)
                            if local_updated_at and local_updated_at > cloud_updated_at:
                                # Local version is newer, skip cloud version
                                continue
                        
                        # Apply field updates inside a per-row SAVEPOINT so a
                        # single bad row (e.g. a UNIQUE/constraint clash) is
                        # skipped instead of rolling back the entire pull batch.
                        try:
                            with db.begin_nested():
                                data = dict(record)
                                
                                # Resolve foreign keys via the parent's durable uid
                                # (shared helper — same logic as push_changes). If a
                                # parent_uid is present but its row isn't local yet
                                # (child pulled before parent), DEFER this record
                                # instead of writing a stale source-DB integer id
                                # (wrong-row / orphan); it re-applies on a later pull.
                                if resolve_parent_fk_uids(db, model_cls, data, log_prefix="[SYNC_WORKER]"):
                                    continue

                                target_obj = existing if existing else model_cls()
                                
                                # If UID is present, we never overwrite or force the integer PK ID
                                if rec_uid and hasattr(model_cls, "uid") and "id" in data:
                                    del data["id"]
                                    
                                for key, val in data.items():
                                    if key in model_cls.__table__.columns:
                                        col_type = model_cls.__table__.columns[key].type
                                        if hasattr(col_type, "python_type") and col_type.python_type == datetime:
                                            if val:
                                                val = _parse_dt(val)
                                        setattr(target_obj, key, val)
                                if not existing:
                                    db.add(target_obj)
                        except Exception as row_err:
                            orig = getattr(row_err, "orig", row_err)
                            logger.warning(
                                "[SYNC_WORKER] Pull skip %s id=%s: %s",
                                table_name, rec_id, str(orig).strip().splitlines()[0],
                            )

                db.commit()
                
                # Broadcast local SSE sync triggers to update browser tabs!
                entities_to_broadcast = set()
                for table_name, records in pulled.items():
                    if records:
                        entity_name = ENTITY_BROADCAST_MAP.get(table_name)
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
