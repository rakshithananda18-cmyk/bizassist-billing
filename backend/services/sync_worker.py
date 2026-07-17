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
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.db import SessionLocal, engine, sync_disabled_var
from logging_config import current_bizid_var
from database.models import (
    User, SyncQueue, SyncLog, ConflictLog,
    Base, Customer, Vendor, Product, Invoice, InvoiceLineItem,
    Inventory, LegacyPayment, StockLedger, ProductBarcode, BusinessSettings,
    InvoicePayment, B2BLedger, Expense, Godown, StockTransfer,
    StockTransferLineItem, PurchaseInvoice, PurchaseInvoiceLineItem,
    PurchaseOrder, PurchaseOrderLineItem, AlertConfig, RateLimitConfig
)
from services.auth import create_access_token
from services.dates import utc_now

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

# Businesses whose SELF-SIGNED tokens the cloud has rejected (JWT_SECRET
# mismatch). We stop self-signing for them until a cloud-issued token arrives,
# instead of spamming the cloud auth log every 15 s.
_SELF_SIGNED_REJECTED: Dict[int, bool] = {}

# Businesses the cloud has refused for lacking the Pro plan (HTTP 402 when
# SUBSCRIPTION_ENFORCED=1). We pause their sync instead of hammering the cloud
# every cycle with data it will keep rejecting. Cleared when a fresh cloud token
# arrives (store_cloud_token) — i.e. the owner logs in again after an upgrade.
_PLAN_BLOCKED: Dict[int, bool] = {}

# ── Push tuning ──────────────────────────────────────────────────────────────
# A cold free HF Space (CPU tier, embedding model loading on boot) can take far
# longer than 10 s to apply a batch. The old flat 10 s read timeout aborted the
# request mid-apply → "The read operation timed out" → the WHOLE batch was
# marked failed and re-sent every cycle, so the outbox never drained. Give reads
# a generous budget and chunk the outbox so each request completes in-window.
_PUSH_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=10.0)
_PUSH_CHUNK_SIZE = 20

# (Guard) Per-business in-flight flag so a slow push can't overlap with the next
# scheduler tick / a manual flush for the same business — overlapping pushes
# re-send the same rows concurrently, causing duplicate-key contention on the
# cloud and making every push even slower (the thundering-herd retry storm seen
# in the cloud logs). A business already pushing is simply skipped this cycle.
_PUSH_INFLIGHT: Dict[int, bool] = {}
_PUSH_INFLIGHT_LOCK = threading.Lock()


def _try_acquire_push(business_id: int) -> bool:
    with _PUSH_INFLIGHT_LOCK:
        if _PUSH_INFLIGHT.get(business_id):
            return False
        _PUSH_INFLIGHT[business_id] = True
        return True


def _release_push(business_id: int) -> None:
    with _PUSH_INFLIGHT_LOCK:
        _PUSH_INFLIGHT.pop(business_id, None)

# IMPORTANT: The local backend and HF Space MUST share the same JWT_SECRET env variable.
# If they differ, the sync worker's locally-signed tokens will be rejected by the cloud
# with HTTP 401 "Invalid token". Set JWT_SECRET to the same value in both:
#   - Local: backend/.env  -> JWT_SECRET=<your_secret>
#   - Cloud: HF Space -> Settings -> Secrets -> JWT_SECRET=<same_secret>


# ── Cloud-issued sync tokens (standard device provisioning) ──────────────────
# On owner login the frontend obtains a CLOUD-issued JWT (24 h, scoped to that
# business) and stores it here via POST /api/sync/cloud-token. The worker then
# authenticates pushes with the cloud's OWN token — no shared JWT_SECRET needed.
# Falls back to the legacy self-signed token for shared-secret setups.
# File lives in CWD: the app-data dir (packaged) / backend/ (dev).
from pathlib import Path as _Path

_TOKEN_FILE = _Path("cloud_sync_tokens.json")


def _load_token_map() -> Dict[str, str]:
    try:
        return json.loads(_TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_token_map(m: Dict[str, str]) -> None:
    try:
        _TOKEN_FILE.write_text(json.dumps(m), encoding="utf-8")
    except Exception as e:
        logger.warning("[SYNC_WORKER] Could not persist cloud token map: %s", e)


def store_cloud_token(business_id: int, token: str) -> None:
    m = _load_token_map()
    m[str(business_id)] = token
    _save_token_map(m)
    # A fresh cloud-issued token clears the self-signed backoff and any Pro-plan
    # pause — a re-login is exactly how an upgraded account resumes sync.
    _SELF_SIGNED_REJECTED.pop(business_id, None)
    _PLAN_BLOCKED.pop(business_id, None)
    logger.info("[SYNC_WORKER] Cloud sync token stored for business %s", business_id)


def _get_cloud_token(business_id: int) -> Optional[str]:
    return _load_token_map().get(str(business_id))


def _invalidate_cloud_token(business_id: int):
    """Drop a rejected/expired cloud token — the next owner login provisions a fresh one."""
    m = _load_token_map()
    if m.pop(str(business_id), None) is not None:
        _save_token_map(m)
        logger.info(
            "[SYNC_WORKER] Cloud token invalidated for business %s — refreshes on next login",
            business_id,
        )

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
from database.sync_map import (
    MODEL_MAP as _MODEL_MAP,
    ENTITY_BROADCAST_MAP,
    resolve_parent_fk_uids,
    _USER_FK_REPOINT_ENTITIES,
)


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


# ============================================================================
# ── SCHEDULER RECURRING SYNC JOB ──
# ============================================================================
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
                now = utc_now()
                if last_run and (now - last_run).total_seconds() < sync_interval:
                    continue

                # Idle-skip: if this business has nothing queued, do NOT probe the
                # cloud or emit a log line every tick. A hybrid business with an
                # empty outbox is the steady state — silently mark it checked so
                # idle installs produce zero network + zero log noise (the "why is
                # the scheduler doing things when nothing's happening" confusion).
                pending = (
                    db.query(SyncQueue)
                    .filter(SyncQueue.business_id == business_id,
                            SyncQueue.synced_at.is_(None))
                    .first()
                )
                if pending is None:
                    _LAST_RUN[business_id] = now
                    continue

                # Perform sync (tag the worker's log lines with this business's BizID)
                _t = current_bizid_var.set(user.public_id or "-")
                try:
                    sync_business(db, user, sync_interval)
                finally:
                    current_bizid_var.reset(_t)
                _LAST_RUN[business_id] = now
            except Exception as e:
                logger.error("[SYNC_WORKER] Error checking settings for user %s: %s", user.username, e)
    except Exception as e:
        # A scheduler tick must never raise into APScheduler (it would log a
        # scary traceback and, on some executors, disable the job). Contain it.
        logger.error("[SYNC_WORKER] Sync tick aborted: %s", e)
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
        
        _t = current_bizid_var.set(user.public_id or "-")
        try:
            sync_business(db, user, force=True)
        finally:
            current_bizid_var.reset(_t)
        _LAST_RUN[business_id] = utc_now()
    except Exception as e:
        logger.error("[SYNC_WORKER] Manual sync flush failed for business %s: %s", business_id, e)
    finally:
        db.close()


# ============================================================================
# ── SYNC BUSINESS TRANSACTION LOGIC ──
# ============================================================================
def sync_business(db: Session, user: User, interval: int = 30, force: bool = False, do_pull: bool = False):
    """Guarded entry point: ensures only one push runs per business at a time."""
    business_id = user.id
    if not _try_acquire_push(business_id):
        logger.debug(
            "[SYNC_WORKER] push already in-flight for business_id=%s — skipping this cycle",
            business_id,
        )
        return
    try:
        return _sync_business_impl(db, user, interval=interval, force=force, do_pull=do_pull)
    finally:
        _release_push(business_id)


def _sync_business_impl(db: Session, user: User, interval: int = 30, force: bool = False, do_pull: bool = False):
    business_id = user.id

    # 0. Subscription check: if the user does not have a Pro plan and subscription is enforced,
    # background sync is paused (only required login/identity is synced during auth).
    from services.auth import subscription_enforced
    from services.admin_service import effective_plan
    if subscription_enforced() and effective_plan(user) != "pro":
        logger.debug("[SYNC_WORKER] Plan is not Pro — pausing background sync for business %s", business_id)
        return

    logger.debug("[SYNC_WORKER] Running sync for business_id=%s", business_id)

    # 1. Probe cloud endpoint health
    try:
        resp = httpx.get(f"{CLOUD_URL}/health", timeout=10.0)
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
                synced_at=utc_now()
            )
            db.add(log)
            db.commit()
            _OFFLINE_STATE[business_id] = True
        return

    # Cloud is reachable — clear the offline flag so the next outage logs once.
    _OFFLINE_STATE[business_id] = False

    # Pro-plan pause: the cloud already refused this business's sync (402). Don't
    # keep pushing data it will reject — wait until the owner re-logs in after an
    # upgrade (store_cloud_token clears this flag).
    if _PLAN_BLOCKED.get(business_id):
        return

    # 2. Query next unsynced batch
    queue_items = (
        db.query(SyncQueue)
        .filter(SyncQueue.business_id == business_id, SyncQueue.synced_at.is_(None))
        .order_by(SyncQueue.id.asc())
        .limit(100)
        .all()
    )

    # Prefer the CLOUD-issued token provisioned at login (standard device flow).
    # Self-signed fallback works only when local & cloud share JWT_SECRET.
    _cloud_token = _get_cloud_token(business_id)
    used_self_signed = _cloud_token is None
    if used_self_signed and _SELF_SIGNED_REJECTED.get(business_id):
        # The cloud already rejected our self-signed tokens (secrets differ —
        # the default on packaged installs). Retrying every cycle only floods
        # the cloud auth log with "Token rejected — invalid token". Wait until
        # the next owner login provisions a cloud-issued token.
        return
    token = _cloud_token or create_access_token({
        "id": business_id,
        "user_id": user.id,
        "username": user.username,
        "public_id": user.public_id,
        "business_name": user.business_name or "Local POS",
        "role": user.role or "enterprise"
    })
    headers = {"Authorization": f"Bearer {token}"}

    if queue_items:
        # Build (queue_item -> change) pairs, draining non-syncable / corrupt
        # rows in place so they leave the pending window instead of recycling.
        pairs = []  # list[(SyncQueue, dict)]
        for item in queue_items:
            # Skip entities that aren't syncable (e.g. `users` — identity is never
            # synced as data). They'd be rejected by the cloud as "unknown entity";
            # mark them done so they drain from the queue instead of recycling.
            if item.entity not in _MODEL_MAP:
                item.synced_at = utc_now()
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
                    item.synced_at = utc_now()  # remove from the pending window
                    continue
            pairs.append((item, {
                "entity": item.entity,
                "entity_id": item.entity_id,
                "operation": item.operation,
                "payload": payload_dict,
                "created_at": item.created_at.isoformat()
            }))

        # Persist the drained skip/dead-letter items even if nothing is pushable.
        db.commit()

        # Push in CHUNKS so each request finishes well within the read timeout
        # even on a cold free HF Space. Items are marked synced per chunk, so a
        # timeout on chunk N still banks chunks 1..N-1 (the outbox shrinks each
        # cycle) instead of the all-or-nothing batch that stalled at "N pending".
        total_pushed = 0
        total_pairs  = len(pairs)
        for start in range(0, total_pairs, _PUSH_CHUNK_SIZE):
            chunk = pairs[start:start + _PUSH_CHUNK_SIZE]
            chunk_changes = [c for (_it, c) in chunk]

            # Collect entity names in this chunk for the progress broadcast
            chunk_entities = sorted({c["entity"] for c in chunk_changes})

            # Broadcast progress BEFORE sending so UI reflects "in flight" state
            _safe_broadcast(business_id, {
                "type":          "sync.progress",
                "phase":         "push",
                "entities":      chunk_entities,
                "done":          total_pushed,
                "total":         total_pairs,
                "chunk_size":    len(chunk_changes),
            })

            try:
                resp = httpx.post(
                    f"{CLOUD_URL}/api/sync/push",
                    json={"changes": chunk_changes},
                    headers=headers,
                    timeout=_PUSH_TIMEOUT,
                )
                if resp.status_code != 200 or resp.json().get("status") != "success":
                    raise Exception(f"HTTP {resp.status_code}: {resp.text}")

                # Chunk pushed successfully — mark just this chunk synced.
                now = utc_now()
                for (it, _c) in chunk:
                    it.synced_at = now
                    it.error = None
                db.commit()
                total_pushed += len(chunk_changes)

                # Broadcast progress AFTER success so UI reflects shrinking queue
                _safe_broadcast(business_id, {
                    "type":    "sync.progress",
                    "phase":   "push",
                    "entities": chunk_entities,
                    "done":    total_pushed,
                    "total":   total_pairs,
                    "chunk_size": len(chunk_changes),
                })
            except Exception as e:
                err_msg = str(e)

                # 402 = the cloud enforces Pro and this business is on the free
                # plan. This is NOT an error/outage — pause sync (so we stop
                # retrying every cycle) and surface a clear, actionable message
                # instead of a scary "Push failed" loop. Resumes on next login
                # after an upgrade (store_cloud_token clears _PLAN_BLOCKED).
                if "402" in err_msg:
                    _PLAN_BLOCKED[business_id] = True
                    logger.info(
                        "[SYNC_WORKER] Cloud sync paused for business %s — Pro plan required "
                        "(free account). Resumes after upgrade + re-login.",
                        business_id,
                    )
                    chunk[0][0].error = "Cloud sync requires the Pro plan"
                    db.add(SyncLog(
                        business_id=business_id,
                        status="failed",
                        error="Cloud sync requires the Pro plan — upgrade to enable Local + Cloud.",
                        synced_at=utc_now(),
                    ))
                    db.commit()
                    return

                logger.error("[SYNC_WORKER] Push failed for business_id=%s: %s", business_id, e)

                # If 401, invalidate cached token so next run fetches a fresh one.
                # If the REJECTED token was self-signed, stop self-signing for this
                # business until a cloud-issued token is provisioned (owner login) —
                # otherwise we'd spam the cloud with invalid tokens every cycle.
                if "401" in err_msg:
                    _invalidate_cloud_token(business_id)
                    if used_self_signed and not _SELF_SIGNED_REJECTED.get(business_id):
                        _SELF_SIGNED_REJECTED[business_id] = True
                        logger.error(
                            "[SYNC_WORKER] Cloud rejected our SELF-SIGNED token for business %s — "
                            "local & cloud JWT_SECRETs differ (normal on packaged installs). "
                            "Hybrid sync pauses until the owner logs in again (which provisions "
                            "a cloud-issued sync token), or set the same JWT_SECRET on both ends.",
                            business_id,
                        )

                # Store error on the first still-pending item of this chunk.
                chunk[0][0].error = f"Push failed: {err_msg}"
                log = SyncLog(
                    business_id=business_id,
                    status="failed",
                    error=f"Push failed: {err_msg}",
                    synced_at=utc_now()
                )
                db.add(log)
                db.commit()
                # Abort remaining chunks this cycle to keep sequence order; the
                # chunks already committed above stay synced (progress preserved).
                return

        unsynced_count = (
            db.query(SyncQueue)
            .filter(SyncQueue.business_id == business_id, SyncQueue.synced_at.is_(None))
            .count()
        )
        if total_pushed or unsynced_count == 0:
            last_success = (
                db.query(SyncLog)
                .filter(SyncLog.business_id == business_id, SyncLog.status == "success")
                .order_by(SyncLog.synced_at.desc())
                .first()
            )
            if last_success:
                last_success.synced_at = utc_now()
                last_success.error = None
            else:
                last_success = SyncLog(
                    business_id=business_id,
                    status="success",
                    synced_at=utc_now()
                )
                db.add(last_success)
            db.commit()

            if total_pushed:
                logger.info("[SYNC_WORKER] Successfully pushed %s changes for business_id=%s", total_pushed, business_id)
            else:
                logger.info("[SYNC_WORKER] Already fully in sync for business_id=%s. Updated last synced timestamp.", business_id)

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
                    "stock_ledger", "b2b_ledgers", "shift_cash_movements",
                )
                _ordered = sorted(pulled.items(), key=lambda kv: 1 if kv[0] in _child_last else 0)

                # Pre-compute total for progress reporting
                _pull_total    = sum(len(recs) for _, recs in _ordered if recs)
                _pull_done     = 0

                for table_name, records in _ordered:
                    model_cls = _MODEL_MAP.get(table_name)
                    if not model_cls:
                        continue

                    if records:
                        # Broadcast progress at the start of each entity batch
                        _safe_broadcast(business_id, {
                            "type":     "sync.progress",
                            "phase":    "pull",
                            "entities": [table_name],
                            "done":     _pull_done,
                            "total":    _pull_total,
                            "chunk_size": len(records),
                        })
                    
                    for record in records:
                        rec_uid = record.get("uid")
                        rec_id = record.get("id")
                        if not rec_id and not rec_uid:
                            continue
                        
                        existing = None
                        if hasattr(model_cls, "uid"):
                            if not rec_uid:
                                logger.warning(
                                    "[SYNC_WORKER] Skipping %s id=%s — no uid present (Phase C strict enforcement)",
                                    table_name, rec_id
                                )
                                continue
                            existing = db.query(model_cls).filter(model_cls.uid == rec_uid).first()

                            # (DEDUP) If uid lookup found nothing, try a natural-key fallback
                            # before inserting a new row. This prevents duplicates when:
                            #   • A local row was created before uid backfill (uid=NULL).
                            #   • A cloud→local pull fires after data was already created locally
                            #     and pushed up, but the local row's uid was not yet recorded.
                            # On a match we UPDATE the existing row AND write the cloud uid to it
                            # so future pulls use the fast uid path.
                            if existing is None:
                                cols = {c.name for c in model_cls.__table__.columns}
                                biz_id_val = record.get("business_id") or business_id

                                if table_name == "invoices" and "invoice_id" in cols:
                                    # Invoices: match by human-readable invoice number
                                    inv_id_str = record.get("invoice_id")
                                    if inv_id_str:
                                        existing = (
                                            db.query(model_cls)
                                            .filter(
                                                model_cls.business_id == biz_id_val,
                                                model_cls.invoice_id  == inv_id_str,
                                            )
                                            .first()
                                        )
                                        if existing:
                                            logger.info(
                                                "[SYNC_WORKER] Dedup pull: matched invoices.invoice_id=%s — updating uid %s→%s",
                                                inv_id_str,
                                                getattr(existing, "uid", None),
                                                rec_uid,
                                            )

                                elif table_name == "invoice_payments" and "idempotency_key" in cols:
                                    # Payments: match by idempotency key (exact-once guarantee)
                                    idem = record.get("idempotency_key")
                                    if idem:
                                        existing = (
                                            db.query(model_cls)
                                            .filter(
                                                model_cls.business_id     == biz_id_val,
                                                model_cls.idempotency_key == idem,
                                            )
                                            .first()
                                        )
                                        if existing:
                                            logger.info(
                                                "[SYNC_WORKER] Dedup pull: matched invoice_payments.idempotency_key=%s — updating uid",
                                                idem,
                                            )

                                elif table_name == "customers" and "phone" in cols:
                                    # Customers: match by (business_id, phone) — phone is
                                    # the most stable unique identifier for a customer.
                                    phone = record.get("phone")
                                    name  = record.get("name")
                                    if phone:
                                        existing = (
                                            db.query(model_cls)
                                            .filter(
                                                model_cls.business_id == biz_id_val,
                                                model_cls.phone       == phone,
                                            )
                                            .first()
                                        )
                                    elif name:
                                        # Fallback: name match (less reliable but better than dup)
                                        existing = (
                                            db.query(model_cls)
                                            .filter(
                                                model_cls.business_id == biz_id_val,
                                                model_cls.name        == name,
                                            )
                                            .first()
                                        )
                                    if existing:
                                        logger.info(
                                            "[SYNC_WORKER] Dedup pull: matched customers id=%s by phone/name — updating uid",
                                            existing.id,
                                        )

                                elif table_name == "vendors" and "phone" in cols:
                                    # Vendors: match by (business_id, phone) same logic as customers
                                    phone = record.get("phone")
                                    name  = record.get("name")
                                    if phone:
                                        existing = (
                                            db.query(model_cls)
                                            .filter(
                                                model_cls.business_id == biz_id_val,
                                                model_cls.phone       == phone,
                                            )
                                            .first()
                                        )
                                    elif name:
                                        existing = (
                                            db.query(model_cls)
                                            .filter(
                                                model_cls.business_id == biz_id_val,
                                                model_cls.name        == name,
                                            )
                                            .first()
                                        )
                                    if existing:
                                        logger.info(
                                            "[SYNC_WORKER] Dedup pull: matched vendors id=%s by phone/name — updating uid",
                                            existing.id,
                                        )

                                elif table_name == "products" and "name" in cols:
                                    # Products: match by (business_id, name) — product names
                                    # within a business are typically unique.
                                    pname = record.get("name")
                                    if pname:
                                        existing = (
                                            db.query(model_cls)
                                            .filter(
                                                model_cls.business_id == biz_id_val,
                                                model_cls.name        == pname,
                                            )
                                            .first()
                                        )
                                    if existing:
                                        logger.info(
                                            "[SYNC_WORKER] Dedup pull: matched products id=%s by name='%s' — updating uid",
                                            existing.id, pname,
                                        )

                                elif table_name == "purchase_invoices" and "invoice_number" in cols:
                                    # Purchase bills: match by invoice number from supplier
                                    inv_num = record.get("invoice_number")
                                    if inv_num:
                                        existing = (
                                            db.query(model_cls)
                                            .filter(
                                                model_cls.business_id    == biz_id_val,
                                                model_cls.invoice_number == inv_num,
                                            )
                                            .first()
                                        )
                                    if existing:
                                        logger.info(
                                            "[SYNC_WORKER] Dedup pull: matched purchase_invoices.invoice_number=%s — updating uid",
                                            inv_num,
                                        )

                                elif table_name == "expenses" and "idempotency_key" in cols:
                                    # Expenses: match by idempotency key if present
                                    idem = record.get("idempotency_key")
                                    if idem:
                                        existing = (
                                            db.query(model_cls)
                                            .filter(
                                                model_cls.business_id     == biz_id_val,
                                                model_cls.idempotency_key == idem,
                                            )
                                            .first()
                                        )
                                    if existing:
                                        logger.info(
                                            "[SYNC_WORKER] Dedup pull: matched expenses by idempotency_key — updating uid",
                                        )
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

                                # Same user_id→owner re-point as the push path:
                                # register_shifts / shift_cash_movements carry a
                                # user_id FK to the non-synced `users` table, so
                                # the source DB's integer id won't exist here.
                                if table_name in _USER_FK_REPOINT_ENTITIES and "user_id" in data:
                                    data["user_id"] = business_id

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

                    if records:
                            _pull_done += len(records)

                db.commit()

                # Final progress event — done == total clears the banner in 2.5 s
                if _pull_total > 0:
                    _safe_broadcast(business_id, {
                        "type":     "sync.progress",
                        "phase":    "pull",
                        "entities": [],
                        "done":     _pull_total,
                        "total":    _pull_total,
                        "chunk_size": 0,
                    })

                
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
            synced_at=utc_now()
        )
        db.add(log)
        db.commit()
