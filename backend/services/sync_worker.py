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
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import httpx
from sqlalchemy import text, func
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

# Last cloud->local PULL per business. Separate from _LAST_RUN because push runs
# on the fast tick (seconds) while the pull is deliberately slower — it exists to
# collect writes made by off-LAN counters against the cloud backend, which is a
# minutes-scale concern, not a seconds-scale one.
_LAST_PULL: Dict[int, datetime] = {}

# (R-2) Per-business pull cursor, expressed in the CLOUD's clock. We seed it from
# the cloud's own `pulled_at` response so the next `last_sync_at` we send is never
# compared across two machines' clocks — eliminating the skew that silently
# dropped freshly-updated cloud rows. In-memory: after a restart the first cycle
# falls back to the SyncLog-derived timestamp, then re-pins to the cloud clock.
_PULL_CURSOR: Dict[int, str] = {}

# M-12: how many consecutive pull cycles have ended with at least one row the
# apply path REJECTED. The cursor is HELD while this is non-zero so the failed
# rows are re-pulled instead of being skipped forever — but it is bounded,
# because a permanently-unappliable row must not stall every later row behind it.
# That trade (retry, then escalate and move on) is the same one the per-row
# SAVEPOINT makes at the row level, applied at the batch level.
_PULL_FAILED_STREAK: Dict[int, int] = {}
_PULL_MAX_FAILED_STREAK = 3

# M-20. How many consecutive pushes may defer the same rows before this stops
# being "ordering will sort itself out" and becomes "the parent is never coming".
# The rows are NEVER discarded at this point — unlike the pull side, which must
# eventually advance its cursor, the outbox can hold a row indefinitely at no
# cost but disk. The bound exists to make a stuck parent LOUD, not to give up.
_PUSH_MAX_DEFER_STREAK = 3
_DEFER_STREAK: dict = {}


# Child tables that have no own `business_id` column — the scan must JOIN through
# their parent to find the owner. Key = child table, value = (parent table, FK column).
# Kept in sync with database/models._BUSINESS_ID_VIA_PARENT; separate here because
# that dict is not importable at module level without creating a circular import.
_CHILD_TABLE_PARENT_MAP = {
    "invoice_line_items":          ("invoices",          "invoice_id"),
    "purchase_invoice_line_items": ("purchase_invoices", "purchase_invoice_id"),
    "purchase_order_line_items":   ("purchase_orders",   "purchase_order_id"),
    "stock_transfer_line_items":   ("stock_transfers",   "transfer_id"),
    # shift_cash_movements inherits business_id via register_shifts.
    # Was in _repair_stuck_child_payloads but NOT in this map, so the
    # heal scan (find_unqueued_syncable_rows) never detected missing movements.
    "shift_cash_movements":        ("register_shifts",   "shift_id"),
}


def find_unqueued_syncable_rows(db, business_id: int, entities=None, limit=200):
    """Syncable rows this device has NEVER put in the outbox.

    THE SAFETY NET FOR M-20a, and deliberately NOT a theory about its cause.

    Covers EVERY syncable entity — both top-level tables (which carry their own
    business_id column) and child/line-item tables (which inherit business_id
    from their parent via a JOIN). The previous version listed only six top-level
    tables, so invoice_line_items, purchase_invoice_line_items, etc. were never
    scanned and 0 of their rows ever reached the outbox.

    SCOPED ON PURPOSE. It only considers rows NEWER than the oldest outbox entry
    for the business. Older rows legitimately have no outbox row — they predate
    hybrid mode, or their queue entries were pruned — and queueing those would
    re-push years of history. That bound is what makes this safe to run
    automatically; without it the check would be right and useless.

    Read-only: returns what it found. Queueing is the caller's decision.

    RAW-SQL BYPASS SAFETY NET (R-11)
    ---------------------------------
    SQLAlchemy ORM listeners (_queue_change) only fire for ORM-level writes.
    Any direct ``connection.execute(text(...))`` or ``session.execute(text(...))``
    bypasses the listeners and misses the sync_queue entry. This function is the
    explicit backstop for that gap: it compares every syncable row's updated_at
    against its sync_queue entry and re-queues any row not covered. It runs at
    the start of every sync cycle so the window is bounded by the sync interval.
    Known raw-SQL paths (admin resets, migration scripts) rely on this net.
    """
    from database.models import SyncQueue as _SQ
    out = []
    if entities is None:
        # ── Top-level tables (have their own business_id column) ──────────────
        # Parents first: a missing parent strands its children.
        entities = [
            "register_shifts", "shift_cash_movements",
            "customers", "vendors", "products",
            "invoices", "purchase_invoices", "purchase_orders",
            "invoice_payments", "inventory", "stock_ledger",
            "product_barcodes", "business_settings", "payments",
            "godowns", "expenses", "stock_transfers",
            "alert_configs", "rate_limit_configs", "period_locks",
        ]
        top_level = entities
        # ── Child tables (inherit business_id from parent) ────────────────────
        child = list(_CHILD_TABLE_PARENT_MAP.keys())
    else:
        top_level = [e for e in entities if e not in _CHILD_TABLE_PARENT_MAP]
        child     = [e for e in entities if e     in _CHILD_TABLE_PARENT_MAP]

    floor = db.query(func.min(_SQ.id)).filter(_SQ.business_id == business_id).scalar()
    if floor is None:
        return out                      # nothing has ever been queued; not our call
    oldest = db.query(_SQ.created_at).filter(_SQ.id == floor).scalar()
    if oldest is None:
        return out

    # ── Scan top-level tables (direct business_id filter) ─────────────────────
    for entity in top_level:
        try:
            rows = db.execute(text(
                f"SELECT r.id FROM {entity} r "
                f"WHERE r.business_id = :bid AND r.created_at >= :since "
                f"AND NOT EXISTS (SELECT 1 FROM sync_queue q "
                f"                 WHERE q.entity = :ent AND q.entity_id = r.id) "
                f"ORDER BY r.id LIMIT :lim"),
                {"bid": business_id, "since": oldest, "ent": entity,
                 "lim": limit}).fetchall()
        except Exception as e:
            logger.warning("[SYNC_HEAL] could not scan %s for biz=%s: %s",
                           entity, business_id, e)
            continue
        for r in rows:
            out.append({"entity": entity, "row_id": int(r[0])})

    # ── Scan child tables (JOIN through parent to filter by business_id) ───────
    for entity in child:
        parent_tbl, fk_col = _CHILD_TABLE_PARENT_MAP[entity]
        try:
            rows = db.execute(text(
                f"SELECT r.id FROM {entity} r "
                f"JOIN {parent_tbl} p ON p.id = r.{fk_col} "
                f"WHERE p.business_id = :bid AND r.created_at >= :since "
                f"AND NOT EXISTS (SELECT 1 FROM sync_queue q "
                f"                 WHERE q.entity = :ent AND q.entity_id = r.id) "
                f"ORDER BY r.id LIMIT :lim"),
                {"bid": business_id, "since": oldest, "ent": entity,
                 "lim": limit}).fetchall()
        except Exception as e:
            logger.warning("[SYNC_HEAL] could not scan child table %s for biz=%s: %s",
                           entity, business_id, e)
            continue
        for r in rows:
            out.append({"entity": entity, "row_id": int(r[0])})

    return out


class PushOutcome:
    """What the cloud did with a pushed chunk, and what the device must do.

    EXTRACTED SO IT CAN BE TESTED. This decision used to live inline in a
    200-line function, so the only way to check it was to grep the source for
    strings — a test that passes on a refactor which breaks the behaviour, and
    fails on a comment reword. Both happened while M-20 was being fixed.

    Pure: no database, no network, no logging. Give it what was sent and what
    the cloud replied, and it says which rows may be acked and which must be
    kept. Every rule that lost a sale is expressible here as an assertion.
    """

    __slots__ = ("deferred", "rejected", "skipped", "applied", "sent",
                 "unaccounted", "hold_keys")

    def __init__(self, chunk_changes, body):
        body = body or {}
        self.sent = len(chunk_changes)
        self.deferred = body.get("deferred") or []
        self.rejected = body.get("rejected") or []
        self.skipped = body.get("skipped") or []
        self.applied = body.get("applied")

        # THE INVARIANT: received == applied + deferred + skipped.
        #
        # `applied` already includes rejected rows — routes/sync.py does
        # `processed_count += 1  # ack either way` in the IntegrityError branch,
        # so adding `rejected` here double-counts and yields an impossible
        # NEGATIVE shortfall (seen in production as "-3 row(s) vanished").
        #
        # `applied` absent means an older cloud: nothing can be concluded, so
        # nothing is claimed (rule 33) rather than treating it as zero.
        if isinstance(self.applied, int):
            explained = self.applied + len(self.deferred) + len(self.skipped)
            self.unaccounted = max(0, self.sent - explained)
        else:
            self.unaccounted = 0

        # Rows to KEEP queued. Deferred rows always; everything in the chunk if
        # the cloud could not account for some row, because without `deferred`
        # naming them there is no way to know WHICH — and acking the wrong one
        # destroys the last copy of a sale. Fail closed.
        self.hold_keys = {(d.get("entity"), d.get("row_id"))
                          for d in self.deferred}

    def should_hold(self, entity, row_id) -> bool:
        if self.unaccounted:
            return True
        return (entity, row_id) in self.hold_keys

    @property
    def ack_count(self) -> int:
        return sum(1 for _ in ()) if self.unaccounted else (
            self.sent - len(self.hold_keys))

    @property
    def is_clean(self) -> bool:
        """Everything the device sent is accounted for and nothing is held."""
        return not self.unaccounted and not self.deferred

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

# ── Sliding refresh of the stored cloud token ────────────────────────────────
# The cloud token is a normal 24 h access token, and until now it was ONLY ever
# minted at login (frontend `_provisionCloudSyncToken`). That was survivable
# while the token merely backed background sync — a lapsed token just paused the
# backup until the next login. It is NOT survivable now that the B2B proxy
# (routes/b2b_proxy.py) depends on it: B2B writes would start failing every 24 h
# until the owner happened to log in again while online.
#
# The cloud already exposes `POST /auth/refresh`, which exchanges a VALID token
# for a fresh one with claims re-read from the DB (so a role/plan/token_version
# change is picked up, and a revoked token is rejected). So we simply renew
# before expiry. A device that is online at least once a day never lapses; one
# that stays offline past expiry degrades exactly as before — reads from the
# local mirror, writes refused — and recovers at the next online login.
_REFRESH_WHEN_UNDER = timedelta(hours=6)

# Businesses whose refresh attempt failed recently, so a dead network doesn't
# mean one refresh POST per scheduler tick.
_REFRESH_BACKOFF: Dict[int, datetime] = {}
_REFRESH_RETRY_AFTER = timedelta(minutes=15)


def _token_expiry(token: str) -> Optional[datetime]:
    """Read a token's `exp` WITHOUT verifying the signature.

    Deliberate: this token was signed by the CLOUD's JWT_SECRET, which a
    packaged local install generally does NOT share. Verifying here would fail
    on exactly the installs that need the refresh most. We are not trusting the
    contents — the cloud re-verifies on /auth/refresh — we only need to know
    roughly when to renew.
    """
    try:
        import jwt as _jwt
        payload = _jwt.decode(token, options={"verify_signature": False})
        exp = payload.get("exp")
        return datetime.utcfromtimestamp(int(exp)) if exp else None
    except Exception:
        return None


def ensure_fresh_cloud_token(business_id: int) -> Optional[str]:
    """Renew the stored cloud token when it is close to expiring.

    Returns the token now in force (possibly unchanged), or None if this
    business has no cloud identity. Never raises — a failed renewal must not
    take down the sync tick that called it.
    """
    token = _get_cloud_token(business_id)
    if not token:
        return None

    exp = _token_expiry(token)
    if exp is not None and (exp - utc_now()) > _REFRESH_WHEN_UNDER:
        return token                                    # still comfortably valid

    backoff_until = _REFRESH_BACKOFF.get(business_id)
    if backoff_until and utc_now() < backoff_until:
        return token

    try:
        resp = httpx.post(
            f"{CLOUD_URL}/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
    except Exception as e:
        _REFRESH_BACKOFF[business_id] = utc_now() + _REFRESH_RETRY_AFTER
        logger.info("[SYNC_WORKER] Cloud token refresh deferred for business %s (offline: %s)",
                    business_id, e)
        return token

    if resp.status_code == 401:
        # Already expired, or revoked server-side. Nothing to salvage — drop it
        # so we stop presenting a dead credential, and let the next online login
        # provision a new one.
        _invalidate_cloud_token(business_id)
        _REFRESH_BACKOFF.pop(business_id, None)
        return None

    if resp.status_code != 200:
        _REFRESH_BACKOFF[business_id] = utc_now() + _REFRESH_RETRY_AFTER
        logger.info("[SYNC_WORKER] Cloud token refresh returned %s for business %s",
                    resp.status_code, business_id)
        return token

    try:
        fresh = (resp.json() or {}).get("token")
    except Exception:
        fresh = None

    if not fresh:
        _REFRESH_BACKOFF[business_id] = utc_now() + _REFRESH_RETRY_AFTER
        return token

    store_cloud_token(business_id, fresh)
    _REFRESH_BACKOFF.pop(business_id, None)
    logger.info("[SYNC_WORKER] Cloud token refreshed for business %s (slid before expiry)", business_id)
    return fresh


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
# (M-7) Post-apply invariants, SHARED with routes/sync.py's push path so the two
# directions can never drift again. Includes the invoice paid-state projection
# and the journal re-derivation. See core/sync/apply_hooks.py.
from core.sync import apply_hooks as _apply_hooks


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
    """Delegates to the shared parser (M-5): an unparseable NON-empty timestamp
    is a real data defect that used to vanish silently here, stopping the row
    from ever syncing. Behaviour is unchanged; the silence is not."""
    return _apply_hooks.parse_dt(dt_str)


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

                # Slide the cloud token forward BEFORE the idle-skip below. The
                # token is a 24 h access token that was previously only minted at
                # login, and the B2B proxy now depends on it — so letting it
                # lapse would break B2B writes daily. This is a local `exp` read
                # on every tick and a network call only in the last few hours of
                # its life, so it costs nothing in the steady state.
                try:
                    ensure_fresh_cloud_token(business_id)
                except Exception as e:
                    logger.debug("[SYNC_WORKER] token refresh check failed for %s: %s", business_id, e)

                # ── Instant Pull listener lifecycle ──────────────────────────
                # Opt-in, Pro-only. Holds an SSE connection to the cloud so a
                # cloud-side edit triggers a local pull immediately instead of
                # waiting out cloud_pull_interval. The periodic pull below is
                # NOT disabled by this — it stays as the fallback, which is why
                # the UI shows the countdown whenever this is not connected.
                try:
                    from services import cloud_listener
                    from services.admin_service import effective_plan
                    # Derived, like hosting_mode: Pro + hybrid gets Instant Pull
                    # by default. `is not False` makes it an explicit OPT-OUT for
                    # anyone who does not want a held-open connection, rather than
                    # a toggle the owner has to discover before the feature does
                    # anything. It was briefly strict opt-in while no backend for
                    # it existed and the badge would otherwise have claimed an
                    # active push channel that was not there.
                    instant_wanted = (
                        general.get("cloud_push_ping_enabled") is not False
                        and effective_plan(user) == "pro"
                    )
                    if instant_wanted:
                        cloud_listener.start(business_id)
                    else:
                        cloud_listener.stop(business_id)
                except Exception as e:
                    logger.debug("[SYNC_WORKER] instant-pull lifecycle skipped for %s: %s", business_id, e)


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

                # ── Scheduled cloud → local pull ──────────────────────────────
                # Push alone is not enough once a business has counters that
                # AREN'T on the owner's LAN. Those devices fall back to the cloud
                # backend, so their invoices are written cloud-side and the
                # owner's local DB never learns about them. An empty local outbox
                # is exactly the state where that gap is invisible — so the
                # idle-skip above must not also skip the pull.
                #
                # Opt-out via settings.general.cloud_pull_enabled = false, and
                # rate-limited to its own (longer) interval so a 5s push tick
                # doesn't turn into a 5s cloud poll.
                pull_enabled = general.get("cloud_pull_enabled", True) is not False
                pull_interval = max(int(general.get("cloud_pull_interval", 120)), 30)

                # First sighting of this business: START the clock rather than
                # firing immediately. Two reasons — an idle install must stay
                # completely silent on its first tick (no cloud probe, no log
                # line), and every business waking at once on service start
                # would otherwise stampede the cloud in the same second.
                last_pull = _LAST_PULL.get(business_id)
                if last_pull is None:
                    _LAST_PULL[business_id] = now
                    last_pull = now

                due_for_pull = (
                    pull_enabled
                    and (now - last_pull).total_seconds() >= pull_interval
                )

                if pending is None and not due_for_pull:
                    _LAST_RUN[business_id] = now
                    continue

                # Perform sync (tag the worker's log lines with this business's BizID)
                _t = current_bizid_var.set(user.public_id or "-")
                try:
                    sync_business(db, user, sync_interval, do_pull=due_for_pull)
                    # ── Parity check (runs at most once every 6 h per business) ─
                    # Independent of the normal push so a parity failure never
                    # stalls outbox delivery. Rate limit is inside the function.
                    try:
                        _cloud_parity_check(db, business_id)
                    except Exception as _parity_err:
                        logger.warning(
                            "[PARITY] biz=%s: parity check raised unexpectedly (non-fatal): %s",
                            business_id, _parity_err,
                        )
                finally:
                    current_bizid_var.reset(_t)
                if due_for_pull:
                    _LAST_PULL[business_id] = now
                _LAST_RUN[business_id] = now

            except Exception as e:
                logger.error("[SYNC_WORKER] Error checking settings for user %s: %s", user.username, e)
    except Exception as e:
        # A scheduler tick must never raise into APScheduler (it would log a
        # scary traceback and, on some executors, disable the job). Contain it.
        logger.error("[SYNC_WORKER] Sync tick aborted: %s", e)
    finally:
        db.close()


def trigger_sync_run(business_id: int, *, pull: bool = False):
    """Run a specific business sync now, optionally including a cloud-to-local pull.

    Most local mutations only need their outbox pushed.  A successful B2B proxy
    write is authored in the cloud, so the local database needs an immediate
    pull to display the buyer's generated Purchase Bill without waiting for the
    regular cloud-pull interval.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == business_id).first()
        if not user:
            logger.warning("[SYNC_WORKER] trigger_sync_run: business %s not found", business_id)
            return
        
        _t = current_bizid_var.set(user.public_id or "-")
        try:
            sync_business(db, user, force=True, do_pull=pull)
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
def _heal_unqueued_rows(db: Session, business_id: int) -> int:
    """Scan for syncable rows that are missing from the outbox and queue them.

    Safety net that runs at the top of every push cycle. Catches rows whose
    `_queue_change` trigger fired correctly but whose INSERT into `sync_queue`
    silently failed, rows created before hybrid mode was enabled, and rows in
    child tables (invoice_line_items etc.) that had no `business_id` of their
    own until _BUSINESS_ID_VIA_PARENT was added.

    Uses _serialize_orm_obj with the live connection so every payload is
    enriched with parent-UID fields (invoice_id_uid, etc.). Without this the
    cloud falls back to the raw integer FK which does not exist in its DB and
    defers the row forever.

    Returns the number of rows queued so the caller can log it.
    """
    from database.models import _serialize_orm_obj
    missing = find_unqueued_syncable_rows(db, business_id)
    if not missing:
        return 0

    # Get the live connection so _serialize_orm_obj can look up parent UIDs.
    # This is what _queue_change does in models.py — we replicate the same
    # enrichment so the payload is identical to what the trigger would produce.
    try:
        conn = db.connection()
    except Exception as _conn_err:
        logger.warning("[SYNC_HEAL] could not get DB connection for enrichment: %s "
                       "— falling back to _row_to_dict (payloads will lack parent UIDs)",
                       _conn_err)
        conn = None

    queued = 0
    for item in missing:
        entity  = item["entity"]
        row_id  = item["row_id"]
        model_cls = _MODEL_MAP.get(entity)
        if not model_cls:
            continue
        try:
            obj = db.query(model_cls).filter(model_cls.id == row_id).first()
            if not obj:
                continue
            # Enriched serialisation: includes invoice_id_uid, transfer_uid, etc.
            # Falls back to plain dict if the connection is unavailable.
            if conn is not None:
                try:
                    payload = json.dumps(_serialize_orm_obj(obj, conn), default=str)
                except Exception as _ser_err:
                    logger.warning("[SYNC_HEAL] enriched serialise failed for %s#%s: %s — using plain dict",
                                   entity, row_id, _ser_err)
                    payload = json.dumps(_row_to_dict(obj), default=str)
            else:
                payload = json.dumps(_row_to_dict(obj), default=str)

            db.execute(
                text(
                    "INSERT INTO sync_queue "
                    "(business_id, entity, entity_id, operation, payload, created_at) "
                    "VALUES (:bid, :ent, :eid, 'INSERT', :pay, :now)"
                ),
                {"bid": business_id, "ent": entity,
                 "eid": row_id,      "pay": payload,
                 "now": utc_now()},
            )
            queued += 1
        except Exception as e:
            logger.warning(
                "[SYNC_HEAL] could not queue missing %s#%s for biz=%s: %s",
                entity, row_id, business_id, e,
            )
    if queued:
        db.commit()
        logger.info(
            "[SYNC_HEAL] biz=%s: queued %s previously-missing row(s) from %s entity type(s). "
            "They will be pushed this cycle.",
            business_id, queued,
            len({i['entity'] for i in missing}),
        )
    return queued


def _repair_stuck_child_payloads(db: Session, business_id: int) -> int:
    """Patch already-stuck outbox entries that are missing parent UID fields.

    When a child row (invoice_line_items, invoice_payments, etc.) was queued
    without enrichment (e.g. by an older version of _heal_unqueued_rows that
    used _row_to_dict), its payload lacks `invoice_id_uid`. The cloud then
    falls back to the raw integer FK, which does not exist in its DB, and
    defers the row forever — producing the CRITICAL deferral loop seen in logs.

    This function detects those stuck rows and patches the payload in-place
    by looking up the parent UID from the local DB. It runs on every push
    cycle but is essentially a no-op once all payloads are correct.

    Returns the number of rows patched.
    """
    child_entities = list(_CHILD_TABLE_PARENT_MAP.keys())
    if not child_entities:
        return 0

    # Build a parameterised IN clause
    placeholders = ", ".join(f":e{i}" for i in range(len(child_entities)))
    params: dict = {"bid": business_id}
    for i, ent in enumerate(child_entities):
        params[f"e{i}"] = ent

    try:
        stuck = db.execute(
            text(
                f"SELECT id, entity, entity_id, payload FROM sync_queue "
                f"WHERE synced_at IS NULL AND business_id = :bid "
                f"AND entity IN ({placeholders}) ORDER BY id"
            ),
            params,
        ).fetchall()
    except Exception as e:
        logger.warning("[SYNC_HEAL] could not query stuck child rows: %s", e)
        return 0

    if not stuck:
        return 0

    patched = 0
    parent_tbl_map = {
        "invoice_line_items":          ("invoices",          "invoice_id",          "invoice_id_uid"),
        "purchase_invoice_line_items": ("purchase_invoices", "purchase_invoice_id", "purchase_invoice_id_uid"),
        "purchase_order_line_items":   ("purchase_orders",   "purchase_order_id",   "purchase_order_id_uid"),
        "stock_transfer_line_items":   ("stock_transfers",   "transfer_id",         "transfer_id_uid"),
        "invoice_payments":            ("invoices",          "invoice_id",          "invoice_id_uid"),
        "shift_cash_movements":        ("register_shifts",   "shift_id",            "shift_id_uid"),
    }

    for row in stuck:
        sq_id, entity, entity_id, payload_str = row
        spec = parent_tbl_map.get(entity)
        if not spec:
            continue

        parent_tbl, fk_col, uid_key = spec
        pay = json.loads(payload_str) if payload_str else {}

        # Already has the uid — nothing to do
        if pay.get(uid_key):
            continue

        fk_val = pay.get(fk_col)
        if not fk_val:
            continue

        try:
            uid_row = db.execute(
                text(f'SELECT uid FROM "{parent_tbl}" WHERE id = :id'),
                {"id": fk_val},
            ).fetchone()
        except Exception as _e:
            logger.warning("[SYNC_HEAL] uid lookup for %s.%s=%s failed: %s",
                           parent_tbl, fk_col, fk_val, _e)
            continue

        if not uid_row or not uid_row[0]:
            continue

        uid_str = str(uid_row[0])
        pay[uid_key] = uid_str
        # Also set the shorter alias (invoice_uid, shift_uid, etc.) that
        # resolve_parent_fk_uids probes as a fallback.
        base = fk_col[:-3] if fk_col.endswith("_id") else fk_col
        pay[f"{base}_uid"] = uid_str

        try:
            db.execute(
                text("UPDATE sync_queue SET payload = :p WHERE id = :id"),
                {"p": json.dumps(pay), "id": sq_id},
            )
            patched += 1
        except Exception as _e2:
            logger.warning("[SYNC_HEAL] could not patch outbox row %s: %s", sq_id, _e2)

    if patched:
        db.commit()
        logger.info(
            "[SYNC_HEAL] biz=%s: patched %s stuck outbox payload(s) with missing parent UIDs. "
            "They will be retried this cycle.",
            business_id, patched,
        )
    return patched


# ── Per-business last parity-check timestamp (in-memory) ───────────────────
_LAST_PARITY: Dict[int, datetime] = {}
_PARITY_INTERVAL_HOURS = 6      # run at most once every 6 hours per business


def _cloud_parity_check(db: Session, business_id: int) -> dict:
    """UID-based cross-DB parity check: local SQLite vs cloud Postgres.

    WHY THIS EXISTS
    ---------------
    The sync push path is the primary guarantee that every local row reaches the
    cloud. But it has two known failure modes that have caused production data
    loss:

      1. A child row (invoice_line_items, invoice_payments) lands on the WRONG
         cloud invoice because its payload lacked ``invoice_id_uid`` (the M-9 /
         M-20 bug). The cloud accepted it, the local side stamped synced_at, and
         neither end reported a problem. The row was simply on the wrong account.

      2. A row was pushed, the cloud deferred it, and the local side acked it
         anyway (M-20). The outbox entry was deleted; the row never landed on
         the cloud.

    Neither failure is caught by the normal push/pull cycle: the push considers
    a row "done" once synced_at is set, and the pull only reads cloud→local.

    This function adds an independent safety net: it pulls ALL child-row UIDs
    from the cloud for this business and compares them against the local DB.
    It then queues corrective actions for every mismatch:

      * WRONG_INVOICE  → queue an UPDATE with the correct ``invoice_id_uid``
                         so the cloud's resolve_parent_fk_uids re-links it.
      * MISSING        → queue an INSERT so the row is pushed again.

    It also recalculates ``paid_amount`` / ``status`` for any invoice where the
    cloud's payment sum doesn't match the stored column (the stale-header
    symptom that made the invoice list show wrong Outstanding amounts).

    SAFETY DESIGN
    -------------
    * Read-only toward the cloud: uses the /api/sync/pull endpoint (no writes).
    * All repairs go through the normal outbox, so every fix is idempotent,
      ordered, and auditable.
    * Rate-limited to _PARITY_INTERVAL_HOURS per business; cheap to call but
      not worth running every 15-second tick.
    * Best-effort: every error is logged and skipped. A failure here must never
      stall the main push cycle.

    Returns a summary dict for the caller / admin endpoint.
    """
    from database.models import _serialize_orm_obj

    summary = {
        "business_id":  business_id,
        "wrong_invoice": 0,
        "missing":       0,
        "paid_state":    0,
        "errors":        [],
    }

    # ── Rate-limit ────────────────────────────────────────────────────────────
    now = utc_now()
    last = _LAST_PARITY.get(business_id)
    if last and (now - last).total_seconds() < _PARITY_INTERVAL_HOURS * 3600:
        logger.debug(
            "[PARITY] biz=%s: skipping — last check was %s min ago",
            business_id,
            int((now - last).total_seconds() / 60),
        )
        return summary

    logger.info("[PARITY] biz=%s: starting cloud parity check", business_id)
    _LAST_PARITY[business_id] = now

    # ── 1. Load local invoice uid→id map for this business ────────────────────
    local_inv_rows = db.execute(text(
        "SELECT id, uid FROM invoices WHERE business_id=:bid AND uid IS NOT NULL"
    ), {"bid": business_id}).fetchall()
    local_inv_uid_to_id = {r[1]: r[0] for r in local_inv_rows}
    local_inv_id_to_uid = {r[0]: r[1] for r in local_inv_rows}

    # ── 2. Load local child-row uid→parent_uid maps ───────────────────────────
    # We only check invoice_line_items and invoice_payments (the two tables that
    # had cross-invoice mis-links in production). Extend the list as needed.
    CHILD_SPECS = [
        # (local_table, fk_col, parent_table, uid_key_in_payload)
        ("invoice_line_items", "invoice_id", "invoices", "invoice_id_uid"),
        ("invoice_payments",   "invoice_id", "invoices", "invoice_id_uid"),
    ]

    local_child = {}   # table -> {uid: correct_parent_uid}
    for table, fk_col, parent_tbl, _ in CHILD_SPECS:
        rows = db.execute(text(
            f"SELECT c.uid, p.uid as parent_uid "
            f"FROM {table} c JOIN {parent_tbl} p ON p.id = c.{fk_col} "
            f"WHERE p.business_id = :bid AND c.uid IS NOT NULL"
        ), {"bid": business_id}).fetchall()
        local_child[table] = {r[0]: r[1] for r in rows}

    # ── 3. Ask the cloud for its child-row state via pull (scoped to 2020+) ───
    token = _get_cloud_token(business_id)
    if not token:
        token = ensure_fresh_cloud_token(business_id)
    if not token:
        summary["errors"].append("no cloud token")
        logger.warning("[PARITY] biz=%s: no cloud token — skipping", business_id)
        return summary

    try:
        resp = httpx.get(
            f"{CLOUD_URL}/api/sync/pull",
            params={"since": "2020-01-01T00:00:00"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0),
        )
    except Exception as e:
        summary["errors"].append(f"pull request failed: {e}")
        logger.warning("[PARITY] biz=%s: pull request failed: %s", business_id, e)
        return summary

    if resp.status_code != 200:
        summary["errors"].append(f"pull HTTP {resp.status_code}")
        logger.warning("[PARITY] biz=%s: pull returned %s", business_id, resp.status_code)
        return summary

    try:
        body = resp.json()
    except Exception as e:
        summary["errors"].append(f"pull JSON decode failed: {e}")
        return summary

    # The cloud pull response wraps all table data under a "changes" key
    # (see sync_worker line: pulled = _resp_json.get("changes", {})).
    # Reading the top-level body directly returns None for every table lookup,
    # which caused every local UID to be flagged as MISSING (false positive).
    cloud_data: dict = body.get("changes", {}) if isinstance(body, dict) else {}

    # ── 3b. Refuse to judge absence from an INCOMPLETE snapshot ───────────────
    # The pull endpoint reports `failed_tables` precisely because "a table that
    # was not read is not a table with no rows" (rule 33). Parity's whole job is
    # deciding whether a local row is absent on the cloud — a judgement it cannot
    # make from a partial answer without inventing MISSING rows and queueing
    # repairs for data that is already there.
    #
    # Seen in production: the cloud returned 2 of 29 tables unread
    # (shift_cash_movements, b2b_orders, both InFailedSqlTransaction) while parity
    # went ahead and queued 80 invoice_line_items repairs, every one of which the
    # cloud then skipped as "cloud copy is newer (LWW)".
    failed_tables = body.get("failed_tables") or [] if isinstance(body, dict) else []
    if failed_tables:
        names = [f.get("table") if isinstance(f, dict) else str(f) for f in failed_tables]
        summary["errors"].append(f"partial cloud snapshot, tables unread: {names}")
        logger.warning(
            "[PARITY] biz=%s: SKIPPING — the cloud could not read %s table(s) %s, so "
            "this snapshot cannot distinguish 'absent on cloud' from 'not read'. "
            "Judging MISSING from it would queue repairs for rows that already exist.",
            business_id, len(names), names,
        )
        return summary

    # ── 4. Build cloud uid lookup maps ────────────────────────────────────────
    # cloud_inv_uid_to_id: cloud uid -> cloud integer id
    cloud_invs = cloud_data.get("invoices", [])
    cloud_inv_uid_to_id = {}
    for inv in cloud_invs:
        uid = inv.get("uid")
        if uid:
            cloud_inv_uid_to_id[uid] = inv.get("id")

    # ── 5. Compare child tables ───────────────────────────────────────────────
    try:
        conn = db.connection()
    except Exception:
        conn = None

    for table, fk_col, parent_tbl, uid_key in CHILD_SPECS:
        cloud_rows = cloud_data.get(table, [])
        cloud_uid_to_inv_uid: dict = {}
        # Every uid the cloud reported for this table, INDEPENDENT of whether we
        # could resolve its parent. "Missing" means absent from THIS set.
        #
        # The bug this fixes: the code below asked
        #   cloud_parent_uid = cloud_uid_to_inv_uid.get(local_uid)
        #   if cloud_parent_uid is None: -> MISSING
        # which cannot tell an ABSENT key from a key whose stored VALUE is None.
        # `parent_uid` is None whenever the child's parent invoice was not found
        # in `cloud_invs`, so a row that exists perfectly well on the cloud was
        # reported MISSING and queued for INSERT. The cloud then answered
        # "LWW conflict resolved (cloud won)" because its copy was newer, acked
        # the row, changed nothing — and the next parity run queued the very same
        # rows again. A livelock: 80 repairs queued every couple of minutes,
        # pushed, deliberately skipped, re-detected, forever.
        cloud_uids_present = set()
        # Rows the cloud has but whose parent we could not pin down. NOT missing,
        # and NOT judgeable — recorded so the count is honest.
        indeterminate = 0

        for crow in cloud_rows:
            cuid = crow.get("uid")
            if not cuid:
                # A cloud row with no uid cannot be matched by uid at all. It is
                # emphatically NOT evidence that the local row is absent, so it
                # must not silently drop out of the comparison.
                indeterminate += 1
                continue
            cloud_uids_present.add(cuid)
            # The cloud row carries the cloud integer invoice_id; resolve back
            # to its uid via the cloud invoice list.
            cloud_inv_id = crow.get(fk_col) or crow.get("invoice_id")
            # Find the parent uid for this cloud_inv_id
            parent_uid = None
            for inv in cloud_invs:
                if inv.get("id") == cloud_inv_id:
                    parent_uid = inv.get("uid")
                    break
            cloud_uid_to_inv_uid[cuid] = parent_uid

        if indeterminate:
            logger.warning(
                "[PARITY] biz=%s: %s cloud row(s) in %s carry no uid — cannot be "
                "matched, so they are counted as indeterminate rather than as "
                "evidence the local row is missing.",
                business_id, indeterminate, table,
            )

        local_map = local_child.get(table, {})

        for local_uid, correct_parent_uid in local_map.items():
            present_on_cloud = local_uid in cloud_uids_present
            cloud_parent_uid = cloud_uid_to_inv_uid.get(local_uid)

            if present_on_cloud and cloud_parent_uid is None:
                # On the cloud, but its parent did not resolve in this snapshot.
                # Re-queueing would be the livelock described above.
                summary.setdefault("indeterminate", 0)
                summary["indeterminate"] += 1
                logger.debug(
                    "[PARITY] biz=%s: %s uid=%r present on cloud but parent "
                    "unresolved in this snapshot — no repair queued.",
                    business_id, table, local_uid,
                )
                continue

            if not present_on_cloud:
                # ── MISSING: row is in local but not on cloud ─────────────────
                correct_local_inv_id = local_inv_uid_to_id.get(correct_parent_uid)
                if not correct_local_inv_id:
                    continue
                model_cls = _MODEL_MAP.get(table)
                if not model_cls:
                    continue
                try:
                    obj = db.query(model_cls).filter(model_cls.uid == local_uid).first()
                    if not obj:
                        continue
                    if conn is not None:
                        try:
                            payload = json.dumps(_serialize_orm_obj(obj, conn), default=str)
                        except Exception:
                            from database.models import _row_to_dict
                            payload = json.dumps(_row_to_dict(obj), default=str)
                    else:
                        from database.models import _row_to_dict
                        payload = json.dumps(_row_to_dict(obj), default=str)
                    db.execute(text(
                        "INSERT OR IGNORE INTO sync_queue "
                        "(business_id, entity, entity_id, operation, payload, created_at) "
                        "VALUES (:bid, :ent, :eid, 'INSERT', :pay, :now)"
                    ), {"bid": business_id, "ent": table,
                        "eid": obj.id, "pay": payload, "now": utc_now()})
                    summary["missing"] += 1
                    logger.warning(
                        "[PARITY] biz=%s: %s uid=%r MISSING on cloud — queued INSERT",
                        business_id, table, local_uid,
                    )
                except Exception as e:
                    summary["errors"].append(f"missing-queue {table} {local_uid}: {e}")
                    logger.warning("[PARITY] biz=%s: could not queue missing %s %r: %s",
                                   business_id, table, local_uid, e)

            elif cloud_parent_uid != correct_parent_uid:
                # ── WRONG INVOICE: cloud row is linked to the wrong parent ─────
                model_cls = _MODEL_MAP.get(table)
                if not model_cls:
                    continue
                try:
                    obj = db.query(model_cls).filter(model_cls.uid == local_uid).first()
                    if not obj:
                        continue
                    if conn is not None:
                        try:
                            pay_dict = _serialize_orm_obj(obj, conn)
                        except Exception:
                            from database.models import _row_to_dict
                            pay_dict = _row_to_dict(obj)
                    else:
                        from database.models import _row_to_dict
                        pay_dict = _row_to_dict(obj)
                    # Ensure the correct parent uid is in the payload
                    pay_dict[uid_key] = correct_parent_uid
                    db.execute(text(
                        "INSERT OR IGNORE INTO sync_queue "
                        "(business_id, entity, entity_id, operation, payload, created_at) "
                        "VALUES (:bid, :ent, :eid, 'UPDATE', :pay, :now)"
                    ), {"bid": business_id, "ent": table,
                        "eid": obj.id, "pay": json.dumps(pay_dict, default=str),
                        "now": utc_now()})
                    summary["wrong_invoice"] += 1
                    logger.warning(
                        "[PARITY] biz=%s: %s uid=%r on WRONG cloud invoice "
                        "(cloud_parent=%r, correct=%r) — queued corrective UPDATE",
                        business_id, table, local_uid, cloud_parent_uid, correct_parent_uid,
                    )
                except Exception as e:
                    summary["errors"].append(f"wrong-queue {table} {local_uid}: {e}")
                    logger.warning("[PARITY] biz=%s: could not queue wrong-invoice %s %r: %s",
                                   business_id, table, local_uid, e)

    # ── 6. Commit queued repairs ───────────────────────────────────────────────
    if summary["missing"] or summary["wrong_invoice"]:
        try:
            db.commit()
        except Exception as e:
            summary["errors"].append(f"commit failed: {e}")
            logger.error("[PARITY] biz=%s: commit of queued repairs failed: %s", business_id, e)

    # ── 7. Invoice paid_amount / status parity ────────────────────────────────
    # Compare the cloud's stored paid_amount against its actual payment sum.
    # If they differ, push a corrective UPDATE for the invoice header so the
    # cloud's reconcile_invoice_paid_state hook re-derives it.
    cloud_pays = cloud_data.get("invoice_payments", [])
    cloud_pay_sum: Dict[int, float] = {}   # cloud_invoice_id -> sum of payments
    for p in cloud_pays:
        inv_id = p.get("invoice_id")
        if inv_id:
            cloud_pay_sum[inv_id] = cloud_pay_sum.get(inv_id, 0.0) + float(p.get("amount_paid") or 0)

    for inv in cloud_invs:
        cloud_inv_id  = inv.get("id")
        inv_uid       = inv.get("uid")
        stored_paid   = float(inv.get("paid_amount") or 0)
        actual_paid   = round(cloud_pay_sum.get(cloud_inv_id, 0.0), 2)
        total_amount  = float(inv.get("total_amount") or 0)

        if abs(stored_paid - actual_paid) < 0.05:
            continue                    # within rounding tolerance — fine

        if inv_uid not in local_inv_uid_to_id:
            continue                    # cloud-only invoice, not our business

        local_inv_id = local_inv_uid_to_id[inv_uid]
        try:
            from database.models import Invoice as _Inv
            local_inv = db.query(_Inv).filter(_Inv.id == local_inv_id).first()
            if not local_inv:
                continue
            # Queue an UPDATE of the invoice header; the cloud post-apply hook
            # will call reconcile_invoice_paid_state which re-derives paid_amount
            # and status from its own payment ledger.
            if conn is not None:
                try:
                    pay_dict = _serialize_orm_obj(local_inv, conn)
                except Exception:
                    from database.models import _row_to_dict
                    pay_dict = _row_to_dict(local_inv)
            else:
                from database.models import _row_to_dict
                pay_dict = _row_to_dict(local_inv)
            db.execute(text(
                "INSERT OR IGNORE INTO sync_queue "
                "(business_id, entity, entity_id, operation, payload, created_at) "
                "VALUES (:bid, 'invoices', :eid, 'UPDATE', :pay, :now)"
            ), {"bid": business_id, "eid": local_inv_id,
                "pay": json.dumps(pay_dict, default=str), "now": utc_now()})
            summary["paid_state"] += 1
            logger.warning(
                "[PARITY] biz=%s: cloud invoice uid=%r has stale paid_amount "
                "(stored=%.2f, actual=%.2f) — queued UPDATE to trigger recalc",
                business_id, inv_uid, stored_paid, actual_paid,
            )
        except Exception as e:
            summary["errors"].append(f"paid-state {inv_uid}: {e}")

    if summary["paid_state"]:
        try:
            db.commit()
        except Exception as e:
            summary["errors"].append(f"paid-state commit failed: {e}")

    total = summary["missing"] + summary["wrong_invoice"] + summary["paid_state"]
    if total:
        logger.info(
            "[PARITY] biz=%s: queued %s repair(s) — wrong_invoice=%s missing=%s paid_state=%s",
            business_id, total,
            summary["wrong_invoice"], summary["missing"], summary["paid_state"],
        )
    else:
        logger.info("[PARITY] biz=%s: cloud parity OK — no drift detected", business_id)

    return summary


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

    # M-12: rows the pull's apply path REJECTED. Declared at FUNCTION scope, not
    # inside the pull block, because the cursor decision at the end of this
    # function has to be able to read it on every path — including the paths
    # where the pull block never ran. A NameError there would be caught by the
    # outer handler and turn this whole guard back into a silent skip.
    _pull_row_failures: list = []

    # M-13: rows the CLOUD refused to store, reported back in the push response.
    # Function scope for the same reason as above — the summary below must be able
    # to read it on every path.
    _push_rejected: list = []
    _push_deferred: list = []      # M-20: kept in the outbox, re-sent next cycle
    _push_unaccounted = 0          # M-20: shortfall an older cloud did not explain

    # 0. Subscription check: if the user does not have a Pro plan and subscription is enforced,
    # background sync is paused (only required login/identity is synced during auth).
    from services.auth import subscription_enforced
    from services.admin_service import effective_plan
    if subscription_enforced() and effective_plan(user) != "pro":
        logger.debug("[SYNC_WORKER] Plan is not Pro — pausing background sync for business %s", business_id)
        return

    logger.debug("[SYNC_WORKER] Running sync for business_id=%s", business_id)

    # ── Safety-net heal: queue any rows this device has never pushed ──────────
    # Runs before the outbox query so newly-queued rows are included in THIS
    # cycle rather than waiting for the next tick. Cheap and idempotent.
    try:
        _heal_unqueued_rows(db, business_id)
    except Exception as _heal_err:
        # Heal is best-effort; a failure must never block the push.
        logger.warning("[SYNC_HEAL] biz=%s heal scan failed (non-fatal): %s",
                       business_id, _heal_err)

    # ── Repair stuck child payloads (missing parent UID fields) ───────────────
    # Fixes outbox rows that were queued without enrichment (e.g. by an older
    # _heal_unqueued_rows using _row_to_dict). Without this, the cloud defers
    # them forever because the raw integer FK doesn't exist in its DB.
    try:
        _repair_stuck_child_payloads(db, business_id)
    except Exception as _repair_err:
        logger.warning("[SYNC_HEAL] biz=%s repair scan failed (non-fatal): %s",
                       business_id, _repair_err)

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

    # Must have a valid public_id (BizID) to sync to cloud — local integer ID
    # alone across network boundary is a multi-tenant security hazard.
    if not (user.public_id or "").strip():
        logger.warning("[SYNC_WORKER] Business %s has no public_id (BizID) — pausing cloud sync until device is linked", business_id)
        return

    # Prefer the CLOUD-issued token provisioned at login (standard device flow).
    # Self-signed fallback works only when local & cloud share JWT_SECRET.
    _cloud_token = _get_cloud_token(business_id)
    used_self_signed = _cloud_token is None
    if used_self_signed and _SELF_SIGNED_REJECTED.get(business_id):
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
            if not item.payload:
                # (R-6 gap) A NULL payload took the SAME dangerous path the
                # corrupt-payload branch below exists to prevent: it fell
                # through with `payload_dict = None` and was pushed as
                # `payload: null`. The cloud then applies `data = payload or {}`
                # — an empty write, which for a row with NOT NULL columns comes
                # back as a rejection and for one without would create a blank
                # record.
                #
                # The guard below was written for `json.loads` failing and never
                # fired for a payload that was never there. Found on 2026-07-28
                # when a requeue tool inserted outbox rows without one.
                #
                # Dead-lettered like a corrupt payload: a row with no payload
                # cannot be sent, and pretending otherwise is how an empty write
                # reaches a money table.
                logger.warning(
                    "[SYNC_WORKER] queue id=%s (%s.%s) has NO payload - "
                    "dead-lettering. It cannot be pushed, and pushing it empty "
                    "would apply a blank row on the cloud.",
                    item.id, item.entity, item.entity_id,
                )
                item.error = "No payload: cannot be pushed"
                item.synced_at = utc_now()
                continue
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

                # M-13 — the cloud ACKS rows it rejected, so a 200 does NOT mean
                # every row stored. It acks deliberately (refusing would stall the
                # outbox behind an unappliable row), and reports what it refused in
                # `rejected`. Reading that field is the only way this device can
                # learn its own write did not survive; ignoring it is what made the
                # loss silent on this side too.
                _push_body = resp.json() or {}
                _rejected = _push_body.get("rejected") or []
                _pf = _push_body.get("apply_failures") or []
                if _rejected:
                    logger.error(
                        "[SYNC_WORKER] the cloud REJECTED %s of %s pushed row(s) for "
                        "biz=%s. They are acked (so the queue drains) but they are "
                        "NOT stored in the cloud and are in its conflicts review "
                        "list: %s",
                        len(_rejected), len(chunk_changes), business_id,
                        [f"{r.get('entity')}#{r.get('row_id')}: {r.get('reason')}"
                         for r in _rejected],
                    )
                    _push_rejected.extend(_rejected)
                if _pf:
                    logger.error(
                        "[SYNC_WORKER] %s pushed row(s) landed in the cloud but "
                        "their derived state (paid status and/or journal entry) did "
                        "not, for biz=%s: %s",
                        len(_pf), business_id, _pf,
                    )

                # -- M-20 (CRITICAL): DEFERRED rows must stay in the outbox ----────────
                #
                # This block used to stamp `synced_at` on EVERY row in the chunk
                # and add `len(chunk_changes)` to the count, unconditionally. So
                # a row the cloud had DEFERRED — held back because its parent was
                # not there yet, expecting the device to send it again — was
                # marked done and deleted from the only place it still existed.
                #
                # Reproduced on production 2026-07-27: a ₹641 sale deferred for a
                # missing `register_shifts` parent, acked here, gone forever.
                #
                # A deferral is NOT a rejection. Rejected means "stop sending
                # this". Deferred means "not yet — keep it". So these rows keep
                # `synced_at = NULL` and go again next cycle.
                _deferred = _push_body.get("deferred") or []
                _defer_keys = {(d.get("entity"), d.get("row_id")) for d in _deferred}
                if _deferred:
                    _push_deferred.extend(_deferred)
                    logger.warning(
                        "[SYNC_WORKER] the cloud DEFERRED %s of %s pushed row(s) "
                        "for biz=%s — their parent is not on the cloud yet. They "
                        "are being KEPT in the outbox and re-sent next cycle: %s",
                        len(_deferred), len(chunk_changes), business_id,
                        [f"{d.get('entity')}#{d.get('row_id')}: {d.get('reason')}"
                         for d in _deferred],
                    )
                    # Auto-heal: a deferred row's parent may also be missing from
                    # the outbox. Trigger the heal scan for the parent entity types
                    # so the parent is queued in the SAME cycle and unblocks the
                    # child on the next push, instead of deferring indefinitely.
                    _deferred_parents = set()
                    for _d in _deferred:
                        _reason = (_d.get("reason") or "").lower()
                        # Cloud returns: "parent register_shifts id=X not in this DB yet"
                        for _parent_ent in list(_MODEL_MAP.keys()):
                            if _parent_ent in _reason:
                                _deferred_parents.add(_parent_ent)
                                break
                    if _deferred_parents:
                        try:
                            _parent_missing = find_unqueued_syncable_rows(
                                db, business_id, entities=list(_deferred_parents))
                            if _parent_missing:
                                logger.warning(
                                    "[SYNC_HEAL] biz=%s: auto-heal found %s missing "
                                    "parent row(s) that explain the deferral: %s — "
                                    "queueing them now.",
                                    business_id, len(_parent_missing),
                                    [f"{m['entity']}#{m['row_id']}" for m in _parent_missing[:5]],
                                )
                                _heal_unqueued_rows(db, business_id)
                        except Exception as _auto_heal_err:
                            logger.warning(
                                "[SYNC_HEAL] biz=%s auto-heal for deferred parents failed: %s",
                                business_id, _auto_heal_err,
                            )

                # ARITHMETIC CHECK. The cloud reports how many rows it actually
                # applied; this compares that against what was sent and accounts
                # for every difference. Had this existed, M-20 was a one-line
                # discrepancy on the very first push: sent 5, applied 4.
                # THE ARITHMETIC, corrected. My first version added the
                # `rejected` count on top of `applied`, and produced
                # "-3 row(s) vanished" on the first real push - a NEGATIVE
                # shortfall, which is impossible and was the tell.
                #
                # `applied` (processed_count) ALREADY INCLUDES rejected rows:
                # `routes/sync.py` does `processed_count += 1  # ack either way`
                # inside the IntegrityError handler, because a refused row is
                # still acked so it cannot stall the queue. Adding `rejected`
                # again double-counts it.
                #
                # And the cloud has a third acked-but-not-stored outcome it was
                # not reporting at all — an unknown entity, or an LWW decision
                # that the cloud copy is newer. Those `continue`d silently, so
                # the sum could never close even after removing the double count.
                # `skipped` now carries them.
                #
                # The invariant is therefore exactly:
                #     received == applied + deferred + skipped
                _outcome = PushOutcome(chunk_changes, _push_body)
                _applied = _outcome.applied
                _skipped = _outcome.skipped
                if isinstance(_applied, int):
                    _explained = _applied + len(_deferred) + len(_skipped)
                    if _skipped:
                        logger.info(
                            "[SYNC_WORKER] the cloud SKIPPED %s row(s) for biz=%s "
                            "deliberately (acked, not an error): %s",
                            len(_skipped), business_id,
                            [f"{s.get('entity')}#{s.get('row_id')}: {s.get('reason')}"
                             for s in _skipped][:10],
                        )
                    if _explained != len(chunk_changes):
                        logger.error(
                            "[SYNC_WORKER] UNACCOUNTED ROWS for biz=%s: sent %s, "
                            "cloud applied %s (incl. %s rejected), deferred %s, "
                            "skipped %s - %s row(s) unexplained. They are being "
                            "KEPT in the outbox rather than acked.",
                            business_id, len(chunk_changes), _applied,
                            len(_rejected), len(_deferred), len(_skipped),
                            len(chunk_changes) - _explained,
                        )
                        # Fail CLOSED: if the cloud cannot account for a row, the
                        # device keeps its copy. An unexplained row is exactly the
                        # case where acking destroys the last copy of a sale.
                        _unaccounted = True
                        _push_unaccounted += len(chunk_changes) - _explained
                    else:
                        _unaccounted = False
                else:
                    # An older cloud does not send `applied`. Nothing can be
                    # concluded, so nothing is claimed (rule 33) — behave as
                    # before rather than inventing a verdict.
                    _unaccounted = False

                # Chunk pushed — mark synced ONLY the rows the cloud accounted for
                # as stored (or explicitly refused). Deferred and unaccounted rows
                # keep synced_at NULL so they are re-sent.
                now = utc_now()
                _acked = 0
                for (it, _c) in chunk:
                    # ONE decision function, shared with the tests (PushOutcome).
                    if _outcome.should_hold(_c["entity"], _c["entity_id"]):
                        it.error = ("deferred by cloud: parent not present yet"
                                    if (_c["entity"], _c["entity_id"]) in _defer_keys
                                    else "cloud did not account for this row; kept queued")
                        continue
                    it.synced_at = now
                    it.error = None
                    _acked += 1
                db.commit()
                total_pushed += _acked

                # Broadcast progress AFTER success so UI reflects shrinking queue.
                # `rejected` rides along so the UI can distinguish "queue drained"
                # from "queue drained and everything stored" (M-13), and
                # `deferred` so it can distinguish both of those from "still
                # queued, waiting on a parent" (M-20) — three different states
                # that all used to render as a shrinking number.
                _safe_broadcast(business_id, {
                    "type":    "sync.progress",
                    "phase":   "push",
                    "rejected": len(_push_rejected),
                    "deferred": len(_push_deferred),
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

        # ── M-20: a durable record of what did NOT reach the cloud ─────────────
        #
        # Rejections and deferrals were logged at ERROR/WARNING and broadcast to
        # the UI, and that was all. `sync_logs` had rows for cloud outages and
        # auth failures but none for "the cloud did not store this sale", so the
        # only surviving evidence of a lost write was a log line that rotates
        # away — which is how the ₹641 sale took a full investigation to find.
        #
        # Money that failed to sync must be a QUERY, not an archaeology exercise.
        for _kind, _rows in (("rejected", _push_rejected),
                             ("deferred", _push_deferred)):
            for _r in _rows[:50]:      # bounded: a stuck parent must not flood
                db.add(SyncLog(
                    business_id=business_id,
                    entity=_r.get("entity"),
                    entity_id=_r.get("row_id"),
                    operation="push",
                    status=f"push_{_kind}",
                    error=(f"{_kind}: {_r.get('reason')}"
                           f"{' uid=' + str(_r.get('uid')) if _r.get('uid') else ''}"),
                    synced_at=utc_now(),
                ))
        if _push_rejected or _push_deferred:
            db.commit()

        unsynced_count = (
            db.query(SyncQueue)
            .filter(SyncQueue.business_id == business_id, SyncQueue.synced_at.is_(None))
            .count()
        )

        # A deferral that never resolves is a stuck parent, and the retry alone
        # will spin forever without telling anyone. Bounded the same way the pull
        # side bounds its retries (M-12): report loudly, keep the data.
        # `_push_unaccounted` counts the OLD-CLOUD case: a cloud that has not yet
        # been upgraded sends no `deferred` field, so the shortfall is detected
        # by the arithmetic instead. The rows are held either way, but without
        # `deferred` we cannot tell WHICH rows failed, so the whole chunk is
        # kept and re-sent every cycle. That is safe and it is also a spin, so it
        # must escalate exactly like a deferral rather than logging forever.
        if _push_deferred or _push_unaccounted:
            _streak = _DEFER_STREAK.get(business_id, 0) + 1
            _DEFER_STREAK[business_id] = _streak
            if _push_unaccounted and not _push_deferred:
                logger.warning(
                    "[SYNC_WORKER] biz=%s: the cloud did not account for %s "
                    "row(s) and did not say why. It is probably running a build "
                    "older than the `deferred` field; until it is updated the "
                    "WHOLE chunk is held and re-sent each cycle. Deploy the "
                    "cloud side to narrow this to just the blocked rows.",
                    business_id, _push_unaccounted,
                )
            if _streak >= _PUSH_MAX_DEFER_STREAK:
                logger.critical(
                    "[SYNC_WORKER] biz=%s: %s row(s) have been DEFERRED by the "
                    "cloud on %s consecutive pushes. Their parent is not arriving "
                    "on its own. The rows are SAFE and still queued locally, but "
                    "they are NOT on the cloud and will not get there until the "
                    "parent does. This needs a human: %s",
                    business_id, len(_push_deferred), _streak,
                    [f"{d.get('entity')}#{d.get('row_id')}: {d.get('reason')}"
                     for d in _push_deferred[:10]],
                )
        else:
            _DEFER_STREAK.pop(business_id, None)

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

    # Pull is opt-in per call. The scheduler now sets do_pull on its own slower
    # cadence (see run_hybrid_sync) so cloud-authored rows — off-LAN counters'
    # invoices, and the B2B mirror — reach the owner's local DB without anyone
    # pressing "Back up now". Explicit user action and migrations still pass
    # do_pull=True directly.
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
            raise Exception("HTTP 401: token rejected by cloud — will refresh next cycle")
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text}")

        _resp_json = resp.json()
        pulled = _resp_json.get("changes", {})
        # Capture the server's own pull timestamp, but DON'T advance the cursor
        # yet — we advance it only AFTER the batch is applied & committed below
        # (see end of this try). Advancing here risked skipping rows if the apply
        # step failed after the cursor had already moved past them.
        _cloud_cursor = _resp_json.get("pulled_at")
        # Tables the cloud could not read this cycle. An absent table is NOT an
        # empty one, so the cursor must not advance past them (see below).
        _pull_failed_tables = _resp_json.get("failed_tables") or []
        if _pull_failed_tables:
            logger.error(
                "[SYNC_WORKER] the cloud reported %s UNREADABLE table(s) for "
                "biz=%s; this pull is PARTIAL: %s",
                len(_pull_failed_tables), business_id,
                [f"{t.get('table')}: {str(t.get('error'))[:80]}"
                 for t in _pull_failed_tables][:10])
        total_pulled = sum(len(v) for v in pulled.values())
        
        if total_pulled > 0:
            logger.info("[SYNC_WORKER] Pulling %s changes from cloud for business_id=%s", total_pulled, business_id)
            
            # Temporarily disable sync triggers so writes are not re-queued
            # Reset the per-table suppress counter so this cycle's summary is fresh.
            from database.models import _PULL_APPLY_SUPPRESS_SEEN
            _PULL_APPLY_SUPPRESS_SEEN.clear()
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
                    # B2B line items hang off b2b_orders, which must land first.
                    "b2b_order_line_items",
                )
                _ordered = sorted(pulled.items(), key=lambda kv: 1 if kv[0] in _child_last else 0)

                # Pre-compute total for progress reporting
                _pull_total    = sum(len(recs) for _, recs in _ordered if recs)
                _pull_done     = 0
                # Post-apply invariants that failed (M-2 / M-7). Collected,
                # logged at ERROR after the batch, and never swallowed — a
                # document whose journal or paid state is missing means this
                # database is showing wrong money, which has to be visible
                # rather than buried in a warning.
                _apply_failures = []
                _pull_row_failures.clear()   # M-12: rejected rows, this cycle
                # (M-8) Financial overwrites flagged for the owner to review.
                _conflicts_logged = 0

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

                        # (R-8) Clock-skew guard on pull path: reject cloud rows
                        # whose updated_at is >5 min ahead of local time.
                        if cloud_updated_at:
                            _now = datetime.now(tz=timezone.utc)
                            _c_aware = cloud_updated_at.replace(tzinfo=timezone.utc) \
                                if cloud_updated_at.tzinfo is None else cloud_updated_at
                            if _c_aware > _now + timedelta(minutes=5):
                                logger.warning(
                                    "[SYNC_WORKER] %s id=%s pull-skipped — cloud updated_at %s "
                                    "is >5 min in the future (local_now=%s). Clock skew suspected.",
                                    table_name, rec_id, cloud_updated_at, _now,
                                )
                                continue

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

                            # (M-8) The cloud version is newer and is about to
                            # overwrite a LOCAL financial row. LWW is correct and
                            # unchanged — but a money record edited in two places
                            # must not have one version vanish without trace.
                            # Snapshot the losing side BEFORE we clobber it.
                            #
                            # This check existed on the push path only, so an
                            # overwrite arriving by PULL was silently lost — the
                            # same one-directional blind spot as M-7.
                            if _apply_hooks.log_financial_conflict(
                                db,
                                business_id=business_id,
                                entity=table_name,
                                entity_id=getattr(existing, "id", rec_id),
                                incoming=dict(record),
                                existing_row=existing,
                                incoming_updated_at=cloud_updated_at,
                                existing_updated_at=local_updated_at,
                                log_prefix="[SYNC_WORKER]",
                            ):
                                _conflicts_logged += 1

                            # (R-9) Non-financial master-data: log the losing
                            # local version before the cloud version lands.
                            if _apply_hooks.log_master_data_conflict(
                                db,
                                business_id=business_id,
                                entity=table_name,
                                entity_id=getattr(existing, "id", rec_id),
                                incoming=dict(record),
                                existing_row=existing,
                                incoming_updated_at=cloud_updated_at,
                                existing_updated_at=local_updated_at,
                                resolution="cloud_won",
                                log_prefix="[SYNC_WORKER]",
                            ):
                                _conflicts_logged += 1


                        # Apply field updates inside a per-row SAVEPOINT so a
                        # single bad row (e.g. a UNIQUE/constraint clash) is
                        # skipped instead of rolling back the entire pull batch.
                        try:
                            with db.begin_nested():
                                data = dict(record)

                                # (R-12) Business ID Pinning: Ensure the pulled row's
                                # business_id is locked to the target business_id so it can
                                # never be cross-assigned or detached to a different business.
                                if "business_id" in data and hasattr(model_cls, "business_id"):
                                    data["business_id"] = business_id

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
                                db.flush()   # need the LOCAL id for the hooks

                            # (M-7) The SAME post-apply invariants the cloud runs
                            # on push. These used to live as private functions in
                            # routes/sync.py, unreachable from here, so the pull
                            # direction silently ran NONE of them — which is why
                            # an invoice pulled cloud→local showed "Pending"
                            # while its payment history showed the money.
                            #
                            # Note the ordering interaction: invoice_payments is
                            # in _child_last, so an invoice is applied BEFORE its
                            # payments. Reconciling at invoice time correctly
                            # finds an empty ledger and does nothing; the fix
                            # lands when the payment arrives and reconciles its
                            # parent. Both hooks are required — neither alone
                            # closes the bug.
                            #
                            # Outside the savepoint above deliberately: the hooks
                            # open their own, so a row whose invariants fail
                            # still lands and only the derived state is missing.
                            _hook = _apply_hooks.run_post_apply(
                                db, table_name, target_obj, log_prefix="[SYNC_WORKER]")
                            if not _hook.ok:
                                _apply_failures.append(_hook)
                        except Exception as row_err:
                            # M-12: a rejected row is a MISSING row, not a log
                            # line. Recorded for review, counted, and the cursor
                            # is held below so it is re-pulled — it used to be a
                            # WARNING that was then counted as applied and
                            # skipped forever.
                            _pull_row_failures.append({
                                "entity": table_name,
                                "row_id": rec_id,
                                "error": str(getattr(row_err, "orig", row_err)
                                             ).strip().splitlines()[0],
                            })
                            _apply_hooks.log_apply_failure(
                                db,
                                business_id=business_id,
                                entity=table_name,
                                entity_id=rec_id,
                                payload=dict(record),
                                error=row_err,
                                log_prefix="[SYNC_WORKER]",
                            )

                    if records:
                            # Successes only. Adding len(records) here regardless
                            # is what let the progress bar reach 100% on a batch
                            # that had dropped rows (M-12).
                            _pull_done += max(
                                0, len(records)
                                - sum(1 for f in _pull_row_failures
                                      if f["entity"] == table_name))

                if _pull_row_failures:
                    logger.error(
                        "[SYNC_WORKER] %s row(s) were REJECTED and are MISSING "
                        "from this database for biz=%s — recorded in the "
                        "conflicts review list; the pull cursor is held so they "
                        "are retried next cycle: %s",
                        len(_pull_row_failures), business_id,
                        [f"{f['entity']}#{f['row_id']}: {f['error']}"
                         for f in _pull_row_failures],
                    )

                if _apply_failures:
                    logger.error(
                        "[SYNC_WORKER] %s post-apply invariant(s) FAILED for biz=%s — "
                        "these rows landed but their derived state (paid status "
                        "and/or journal entry) is missing, so this database is "
                        "showing wrong money until they re-apply: %s",
                        len(_apply_failures), business_id,
                        [f"{h.entity}#{h.row_id}: {'; '.join(h.errors)}"
                         for h in _apply_failures],
                    )

                db.commit()

                # Final progress event. `done == total` clears the banner as a
                # clean success, so it must NOT be sent when rows were rejected —
                # that is the green banner over missing data (M-12). Report the
                # applied count and the failure count instead, and let the UI
                # say so.
                if _pull_total > 0:
                    _safe_broadcast(business_id, {
                        "type":     "sync.progress",
                        "phase":    "pull",
                        "entities": [],
                        "done":     _pull_total if not _pull_row_failures else _pull_done,
                        "total":    _pull_total,
                        "chunk_size": 0,
                        "failed":   len(_pull_row_failures),
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
                # Emit a one-line summary of suppressed re-queue attempts instead
                # of one DEBUG line per row (which flooded the logs at 100+ lines
                # per pull cycle when large table_alterations batches came down).
                if _PULL_APPLY_SUPPRESS_SEEN:
                    logger.debug(
                        "[SYNC_QUEUE] pull-apply suppressed re-queue for biz=%s: %s row(s) "
                        "across %s table(s) \u2014 correct, they came from cloud.",
                        business_id,
                        sum(_PULL_APPLY_SUPPRESS_SEEN.values()),
                        {tbl: cnt for tbl, cnt in _PULL_APPLY_SUPPRESS_SEEN.items()},
                    )
                sync_disabled_var.reset(token_var)

        # The batch has now been applied & committed above (or there was nothing
        # to pull). ONLY NOW is it safe to advance the cursor. If the fetch timed
        # out or the apply raised, we never reach here — so the same window is
        # re-pulled next cycle instead of being silently skipped.
        # M-12 — the cursor is the difference between "retried" and "lost".
        # It used to advance unconditionally, so any row the apply path rejected
        # was never seen again. Now it is HELD while rows are failing, bounded by
        # _PULL_MAX_FAILED_STREAK so one permanently-unappliable row cannot stall
        # every later row behind it forever.
        if _cloud_cursor:
            _failed_now = len(_pull_row_failures)
            if _failed_now:
                streak = _PULL_FAILED_STREAK.get(business_id, 0) + 1
                _PULL_FAILED_STREAK[business_id] = streak
                if streak < _PULL_MAX_FAILED_STREAK:
                    logger.error(
                        "[SYNC_WORKER] HOLDING the pull cursor for biz=%s "
                        "(attempt %s/%s) so the %s rejected row(s) are re-pulled.",
                        business_id, streak, _PULL_MAX_FAILED_STREAK, _failed_now)
                else:
                    logger.critical(
                        "[SYNC_WORKER] biz=%s: %s row(s) still REJECTED after %s "
                        "attempts. Advancing the cursor so later rows are not "
                        "blocked — THESE ROWS REMAIN MISSING and are in the "
                        "conflicts review list. They need a human.",
                        business_id, _failed_now, streak)
                    _PULL_FAILED_STREAK[business_id] = 0
                    _PULL_CURSOR[business_id] = _cloud_cursor
            elif _pull_failed_tables:
                # ── PARTIAL PULL: hold the cursor (rule 58 / M-12 shape) ──────
                #
                # The cloud could not read some tables — on Postgres, one failed
                # query aborts the transaction and every later table dies with
                # InFailedSqlTransaction, so a single failure can cost twenty
                # tables. `changes` then simply has no key for them, which is
                # indistinguishable from "that table had no changes".
                #
                # Advancing the cursor here would move `last_sync_at` past rows
                # this device NEVER RECEIVED, and they would never be offered
                # again. That is M-12 exactly, on the read side.
                #
                # So the cursor is HELD and the same window is re-pulled next
                # cycle. Unlike a rejected row, this needs no bound: a table that
                # fails forever is a cloud-side defect that must be fixed, and
                # re-reading a window costs nothing but a query.
                logger.error(
                    "[SYNC_WORKER] PARTIAL PULL for biz=%s: the cloud could not "
                    "read %s table(s) — %s. HOLDING the pull cursor so the same "
                    "window is re-pulled; advancing it would skip rows this "
                    "device never received.",
                    business_id, len(_pull_failed_tables),
                    [t.get("table") for t in _pull_failed_tables][:10],
                )
            else:
                _PULL_FAILED_STREAK[business_id] = 0
                _PULL_CURSOR[business_id] = _cloud_cursor

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
