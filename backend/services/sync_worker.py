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
from sqlalchemy import text, func, or_
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

# (R-2) Per-business pull cursor, expressed in the CLOUD's clock. Seeded from the
# cloud's own `pulled_at` response so the next `last_sync_at` we send is never
# compared across two machines' clocks — eliminating the skew that silently
# dropped freshly-updated cloud rows.
#
# NOW WRITE-THROUGH TO `sync_cursors`. It was previously in-memory only, and the
# restart path was the hole: with the dict empty, the cursor was re-derived from
#
#     SyncLog … .filter(status == "success")
#               .order_by(synced_at.desc())
#               .offset(1 if queue_items else 0)
#
# which is a PROXY for what was applied, not a record of it — and `sync_logs`
# carries push rows too. Whenever that proxy resolves LATER than the last row
# actually applied, every row in between is skipped and never offered again.
# That is M-12, reintroduced by any process restart, on a code path that only
# runs when something has already gone wrong.
#
# The dict is kept as a read-through cache so the hot path stays a dict lookup.
_PULL_CURSOR: Dict[int, str] = {}

# M-12: how many consecutive pull cycles have ended with at least one row the
# apply path REJECTED. The cursor is HELD while this is non-zero so the failed
# rows are re-pulled instead of being skipped forever — but it is bounded,
# because a permanently-unappliable row must not stall every later row behind it.
# That trade (retry, then escalate and move on) is the same one the per-row
# SAVEPOINT makes at the row level, applied at the batch level.
_PULL_FAILED_STREAK: Dict[int, int] = {}
_PULL_MAX_FAILED_STREAK = 3

# Rows per table per pull. Bounds the response so a wide window cannot exceed
# the client timeout. Unbounded was a livelock: a first pull (no cursor → 1970)
# asked for every row of every table inside 10 s, timed out, correctly refused to
# advance the cursor, and re-attempted the identical impossible request forever.
_PULL_PAGE_LIMIT = 1000

# Was 10.0 while the same endpoint was called by the parity audit with 180.0 —
# the discrepancy was the tell that 10 s never fitted a wide window. Now that
# pages are bounded this is generous rather than load-bearing.
_PULL_TIMEOUT = 60.0

# Businesses whose last pull came back truncated (`has_more`). run_hybrid_sync
# pulls these again on the NEXT tick instead of waiting out cloud_pull_interval,
# so a backlog drains in seconds rather than one page every two minutes.
_PULL_MORE_PENDING: set = set()

# Sentinel for "this business has been looked up and has no stored cursor", so a
# genuine absence is not re-queried on every cycle. `None` cannot express it —
# it is indistinguishable from "not looked up yet", which is the same
# absent-vs-unread confusion rule 33 is about, in miniature.
_NO_CURSOR = "\x00none"


def _get_pull_cursor(db: Session, business_id: int) -> Optional[str]:
    """Read the durable pull cursor, falling back to the in-memory cache."""
    cached = _PULL_CURSOR.get(business_id)
    if cached is _NO_CURSOR:
        return None
    if cached:
        return cached
    try:
        from database.models import SyncCursor
        row = (
            db.query(SyncCursor)
            .filter(SyncCursor.business_id == business_id, SyncCursor.entity == "*")
            .first()
        )
    except Exception as e:
        # A cursor we cannot READ must not become a cursor we INVENT. Returning
        # None here means "start from the SyncLog fallback", which re-reads a
        # window — cheap and safe. Guessing a later value would skip rows.
        logger.warning("[SYNC_WORKER] biz=%s: could not read stored pull cursor: %s",
                       business_id, e)
        return None
    if row and row.cursor_value:
        _PULL_CURSOR[business_id] = row.cursor_value
        return row.cursor_value
    _PULL_CURSOR[business_id] = _NO_CURSOR
    return None


def _set_pull_cursor(db: Session, business_id: int, value: str) -> None:
    """Advance the pull cursor, in memory AND on disk.

    Committed immediately and separately from the pull batch: the batch is
    already committed by the time this is called, so a cursor that failed to
    persist would mean the same window is re-pulled after a restart. Re-pulling
    is idempotent (uid-keyed upserts); skipping is not recoverable.
    """
    _PULL_CURSOR[business_id] = value
    try:
        from database.models import SyncCursor
        row = (
            db.query(SyncCursor)
            .filter(SyncCursor.business_id == business_id, SyncCursor.entity == "*")
            .first()
        )
        if row is None:
            row = SyncCursor(business_id=business_id, entity="*")
            db.add(row)
        row.cursor_value = value
        row.failed_streak = 0
        row.updated_at = utc_now()
        db.commit()
    except Exception as e:
        db.rollback()
        # Non-fatal by design: the in-memory value still advances, so this
        # process keeps making progress. Only a restart re-reads the window.
        logger.warning(
            "[SYNC_WORKER] biz=%s: pull cursor advanced in memory but NOT "
            "persisted (%s). A restart will re-pull this window — idempotent, "
            "but slower.", business_id, e,
        )

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

# Businesses whose PULL the cloud has rejected with 401. The push side has had
# `_SELF_SIGNED_REJECTED` from the start; the pull side had nothing, and the
# asymmetry showed:
#
#   push 401 -> flag set -> one ERROR, then quiet          (biz 133, 19:38:09)
#   pull 401 -> retry forever -> an ERROR every cycle      (biz 126, 19:40, 19:43, …)
#
# Worse, the pull's own message promised a recovery it had just made impossible:
# it called `_invalidate_cloud_token` (which DELETES the token) and then said
# "will refresh next cycle" — but `ensure_fresh_cloud_token` opens with
# `if not token: return None`. There was nothing left to refresh. A token can
# only come back from an owner login, so that is what the log must say.
#
# Cleared by `store_cloud_token`, exactly like the two flags above: a re-login
# is how a device resumes.
_PULL_AUTH_BLOCKED: Dict[int, bool] = {}

# ── Push tuning ──────────────────────────────────────────────────────────────
# A cold free HF Space (CPU tier, embedding model loading on boot) can take far
# longer than 10 s to apply a batch. The old flat 10 s read timeout aborted the
# request mid-apply → "The read operation timed out" → the WHOLE batch was
# marked failed and re-sent every cycle, so the outbox never drained. Give reads
# a generous budget and chunk the outbox so each request completes in-window.
_PUSH_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=10.0)
_PUSH_CHUNK_SIZE = 20

# Outbox backoff for rows the cloud HELD (deferred / unaccounted). Doubling from
# one minute, capped at an hour: a parent that is a few seconds behind its child
# still lands on the next cycle, while a parent that is never coming stops
# costing a push every cycle. The cap is deliberate — the row must keep retrying
# forever, because the parent CAN still arrive (a later sync, a repair script),
# and a row that gave up permanently is a lost write.
_PUSH_BACKOFF_BASE_SEC = 60
_PUSH_BACKOFF_MAX_SEC  = 3600


def _push_backoff(attempts: int) -> timedelta:
    """Delay before a held outbox row is offered again. attempts >= 1."""
    seconds = min(_PUSH_BACKOFF_BASE_SEC * (2 ** max(0, attempts - 1)),
                  _PUSH_BACKOFF_MAX_SEC)
    return timedelta(seconds=seconds)

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
from pathlib import Path as _Path


def _resolve_token_file() -> _Path:
    """One location per INSTALL, not one per invocation directory (C-13 item 2).

    This was `_Path("cloud_sync_tokens.json")` — relative, so it resolved against
    whatever CWD the process happened to start in. In both real deployments that
    was already correct (packaged: `server_entry` chdirs to BIZASSIST_DATA_DIR;
    dev: uvicorn runs from `backend/`), so nothing about the running app changes
    here.

    What it fixes is every OTHER entry point. `_get_cloud_token` is called from
    `core/identity.py`, `core/api/staff.py`, `routes/b2b_proxy.py` and two
    scripts, and an audit or repair script imported from the repo root wrote a
    SECOND, empty token file at the root — where `.gitignore` did not match it
    until item 1 was fixed, one `git add -A` away from committing live cloud
    bearer JWTs. Reproduced accidentally while writing the 08-03 audit.

    Resolving absolutely means a script cannot create a stray store, and cannot
    read an empty one and conclude the device has no token.
    """
    data_dir = os.environ.get("BIZASSIST_DATA_DIR")
    if data_dir:
        return _Path(data_dir) / "cloud_sync_tokens.json"
    # Dev and scripts: backend/ is the parent of this services/ package. NOT cwd.
    return _Path(__file__).resolve().parent.parent / "cloud_sync_tokens.json"


_TOKEN_FILE = _resolve_token_file()

# Last reported state of the store, so the line below is logged when the answer
# CHANGES rather than on every read. `_load_token_map` runs on each sync tick
# (15 s) — an unconditional log here is four entries a minute for ever, which is
# how the real signal gets buried.
_TOKEN_STORE_LAST_STATE: Optional[str] = None


def token_store_path() -> _Path:
    """Where THIS process reads cloud tokens from. Scripts should say it out
    loud: 'no cloud token' and 'I looked in the wrong place' are the same
    sentence to a user, and only one of them is worth acting on."""
    return _TOKEN_FILE


def _note_store_state(state: str, level, msg: str, *args) -> None:
    global _TOKEN_STORE_LAST_STATE
    if state == _TOKEN_STORE_LAST_STATE:
        return
    _TOKEN_STORE_LAST_STATE = state
    level(msg, *args)


def _load_token_map() -> Dict[str, str]:
    """Read the store. ABSENT and UNREADABLE are different answers (rule 33).

    Both used to return `{}` silently, so a corrupt or permission-denied token
    file was indistinguishable from a device that had simply never been
    provisioned — and the visible symptom of both is "sync is quiet", which is
    also what a healthy idle install looks like.
    """
    if not _TOKEN_FILE.exists():
        _note_store_state(
            "absent", logger.info,
            "[SYNC_WORKER] No cloud token store at %s — no device provisioned "
            "here yet. It is written at owner login.", _TOKEN_FILE)
        return {}
    try:
        m = json.loads(_TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        _note_store_state(
            "unreadable", logger.error,
            "[SYNC_WORKER] Cloud token store at %s could NOT be read (%s). This "
            "is UNREADABLE, not empty — sync will now behave exactly as if no "
            "device were provisioned. Fix or delete the file.", _TOKEN_FILE, e)
        return {}
    _note_store_state(
        "ok", logger.info,
        "[SYNC_WORKER] Cloud token store %s read — %s business(es) provisioned.",
        _TOKEN_FILE, len(m))
    return m


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
    _PULL_AUTH_BLOCKED.pop(business_id, None)
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
        # Unverified decode is the POINT here — see the docstring. A local
        # install does not hold the cloud's JWT_SECRET, so verifying would fail
        # on exactly the installs that need renewal most. Nothing from this
        # payload is trusted: the only value read is `exp`, and the only thing
        # it decides is WHEN to ask the cloud to renew. The cloud verifies the
        # signature itself on /auth/refresh and rejects a forged or revoked
        # token there. A tampered `exp` can therefore make this device renew too
        # early or too late — it cannot authenticate anything.
        #
        # The marker must be a TRAILING comment on the reported line; Sonar
        # ignores it on any other line, which is why the block above did nothing.
        payload = _jwt.decode(token, options={"verify_signature": False})  # NOSONAR python:S5659
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
from core.sync import inbox as _inbox


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
                    and (
                        (now - last_pull).total_seconds() >= pull_interval
                        # A truncated page means the cloud has more waiting RIGHT
                        # NOW. Waiting out the full interval between pages would
                        # drain a backlog one page per cloud_pull_interval — 1000
                        # rows every two minutes by default. Follow up on the next
                        # tick instead; this clears itself the moment a pull comes
                        # back complete.
                        or business_id in _PULL_MORE_PENDING
                    )
                )

                if pending is None and not due_for_pull:
                    _LAST_RUN[business_id] = now
                    continue

                # Perform sync (tag the worker's log lines with this business's BizID)
                _t = current_bizid_var.set(user.public_id or "-")
                try:
                    sync_business(db, user, sync_interval, do_pull=due_for_pull)
                    # NOTE: the parity check used to run HERE, inline. It does a
                    # full `since=2020-01-01` cloud pull with a 180 s read
                    # timeout, inside a job registered at `seconds=15` with
                    # `max_instances=1`. One slow parity therefore starved every
                    # subsequent tick — the observed symptom being an unbroken
                    # run of
                    #   Execution of job "Hybrid Sync Engine" skipped:
                    #   maximum number of running instances reached (1)
                    # every 15 s for minutes after each restart, during which NO
                    # business pushed or pulled anything at all. The comment that
                    # sat here claimed parity was "independent of the normal push
                    # so a parity failure never stalls outbox delivery"; being a
                    # blocking call on the same thread, it was the opposite.
                    #
                    # It now runs as its own scheduler job — see
                    # `run_cloud_parity_sweep` below. Do not call it from this
                    # loop again.
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


def run_cloud_parity_sweep():
    """APScheduler job. Runs the cloud parity check for every hybrid business.

    WHY THIS IS A SEPARATE JOB
    --------------------------
    `_cloud_parity_check` issues a full `since=2020-01-01` pull of every synced
    table with a 180 s read timeout. That is a legitimate cost for a drift audit
    that runs twice a day — and a fatal one on the 15 s push tick, where
    `max_instances=1` turns each slow parity into minutes of totally stalled
    sync. It used to be called inline from `run_hybrid_sync`; it is not any more.

    This job carries its OWN session and its OWN `max_instances=1`, so a parity
    run that overruns delays only the next parity run.

    The per-business 6 h rate limit inside `_cloud_parity_check` still applies —
    this sweep may fire more often than that and will simply no-op, which is what
    makes a restart cheap.
    """
    if engine.dialect.name != "sqlite":
        return   # cloud does not run parity against itself

    db = SessionLocal()
    try:
        for user in db.query(User).all():
            if not user.settings:
                continue
            try:
                general = (json.loads(user.settings) or {}).get("general", {})
            except Exception:
                continue
            if general.get("hosting_mode") != "hybrid":
                continue

            _t = current_bizid_var.set(user.public_id or "-")
            try:
                _cloud_parity_check(db, user.id)
            except Exception as e:
                # Best-effort by contract. A parity failure must never propagate:
                # it is an audit, and the outbox is not waiting on it.
                logger.warning(
                    "[PARITY] biz=%s: parity check raised unexpectedly (non-fatal): %s",
                    user.id, e,
                )
            finally:
                current_bizid_var.reset(_t)
    except Exception as e:
        logger.error("[PARITY] sweep aborted: %s", e)
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

# Money tolerance, matching the stored-vs-actual check further down and
# `core/accounting/db_invariants.py`. Below this, a difference is rounding.
_FIT_TOLERANCE = 0.05


def _cloud_only_row_fits(db, business_id, table, crow, cloud_invs,
                         local_inv_uid_to_id):
    """May this cloud-only row be imported, or would it break an invariant?

    Returns `(fits, reason_if_not)`.

    THE PROBLEM THIS SOLVES
    -----------------------
    "On the cloud, absent here" has two histories and the row does not say
    which:

        (a) it never arrived            → importing it is the repair.
        (b) it arrived and was deleted  → importing it UNDOES the repair.

    There is no tombstone for these tables — `repair_line_items_by_invariant.py`
    deletes over a raw connection, so `after_delete` never fires and nothing is
    queued for the cloud. So (b) leaves exactly the same evidence as (a).

    Rather than guess, this asks a question that IS answerable: **would this row
    still be consistent with the invoice it belongs to?** A payment that pushes
    `paid_amount` past the invoice total, or a line item that pushes line value
    past what was billed, is not a missing row — it is a duplicate, whichever
    history produced it. Withhold it and say so.

    That also settles LCL-OW-0037 correctly. The cloud's ₹124 Bank settlement
    would make ₹248 on a ₹124 invoice, so it is NOT auto-imported. Which of the
    two payments is real is a question about what happened at the counter.
    """
    # Resolve the cloud row's parent invoice to the LOCAL invoice id. Without a
    # parent here there is nothing to measure against, so decline — a row whose
    # invoice is not in this database is not a row this database is missing.
    cloud_inv_id = crow.get("invoice_id")
    parent_uid = None
    for inv in cloud_invs:
        if inv.get("id") == cloud_inv_id:
            parent_uid = inv.get("uid")
            break
    if not parent_uid:
        return False, "its cloud invoice could not be resolved in this snapshot"

    local_inv_id = local_inv_uid_to_id.get(parent_uid)
    if not local_inv_id:
        return False, "its invoice does not exist in this database"

    try:
        inv_row = db.execute(text(
            "SELECT total_amount, cash_discount, round_off FROM invoices "
            "WHERE id = :iid"
        ), {"iid": local_inv_id}).fetchone()
    except Exception as e:
        return False, f"could not read the local invoice ({e})"
    if inv_row is None:
        return False, "its invoice does not exist in this database"

    total = float(inv_row[0] or 0)
    if total <= 0:
        # A zero-total invoice cannot bound anything; refuse rather than treat
        # "no ceiling" as "any amount is fine".
        return False, "the local invoice has no total to measure against"

    incoming = float(crow.get("amount_paid") if table == "invoice_payments"
                     else crow.get("line_total") or 0)

    if table == "invoice_payments":
        current = float(db.execute(text(
            "SELECT COALESCE(SUM(amount_paid), 0) FROM invoice_payments "
            "WHERE invoice_id = :iid"
        ), {"iid": local_inv_id}).scalar() or 0)
        ceiling = total
        if current + incoming > ceiling + _FIT_TOLERANCE:
            return False, (
                f"it would make paid {current + incoming:.2f} on a "
                f"{total:.2f} invoice"
            )
        return True, ""

    if table == "invoice_line_items":
        # The system's own invariant, from core/accounting/db_invariants.py:
        #   SUM(line_total) == total_amount + cash_discount - round_off
        current = float(db.execute(text(
            "SELECT COALESCE(SUM(line_total), 0) FROM invoice_line_items "
            "WHERE invoice_id = :iid"
        ), {"iid": local_inv_id}).scalar() or 0)
        ceiling = total + float(inv_row[1] or 0) - float(inv_row[2] or 0)
        if current + incoming > ceiling + _FIT_TOLERANCE:
            return False, (
                f"it would make line value {current + incoming:.2f} against "
                f"{ceiling:.2f} billed"
            )
        return True, ""

    # Any table without an invariant we can check here. Import is not obviously
    # safe and not obviously wrong, so it is not done silently either way.
    return False, f"no fit rule is defined for {table}"


def _parity_presence_tables() -> list:
    """Synced tables this sweep can compare by presence, cheapest-first.

    A table qualifies when it carries BOTH `uid` (the only cross-database row
    identity — core/identity.py) and `business_id` (so the local side can be
    scoped without a join). The line-item and b2b tables are excluded here
    because they carry neither a tenant column nor a direct scope; two of them
    are already covered by `CHILD_SPECS`, and the rest need the parent join that
    §5 does.

    Derived from MODEL_MAP rather than hard-coded, so a newly synced table is
    compared automatically instead of silently sitting outside the sweep — which
    is how 23 of 25 tables came to be uncompared in the first place.
    """
    out = []
    for name, model in _MODEL_MAP.items():
        cols = {c.name for c in model.__table__.columns}
        if "uid" in cols and "business_id" in cols:
            out.append(name)
    return sorted(out)


def _parity_presence_sweep(db: Session, business_id: int, cloud_data: dict,
                           summary: dict) -> None:
    """Does each side hold the same ROWS? Detection only — repairs nothing.

    WHY THIS EXISTS
    ---------------
    Before 2026-08-03 the sweep compared exactly two tables — `invoice_line_items`
    and `invoice_payments` (`CHILD_SPECS`) — plus a paid-state check on invoices.
    Everything else was outside every question it asked, so a whole missing
    INVOICE, product, customer or expense was invisible to the only continuous
    cross-database check the system has. The summary still said
    "cloud parity OK — no drift detected", which is rule 33 in the one component
    whose entire job is telling "absent" from "not looked at".

    WHY IT IS FREE
    --------------
    The pull above already downloads EVERY synced table (no `limit`, deliberately
    — see §3). The rows are in `cloud_data` whether or not anyone looks at them.
    Comparing more tables costs no extra network I/O, only local set arithmetic.

    WHY IT DOES NOT REPAIR
    ----------------------
    Deliberate, and it is the §7b.5 lesson. The cloud-only scan for line items
    needed `_cloud_only_row_fits` to avoid re-importing 31 invoices' worth of
    duplicates that had been deleted locally on purpose — "absent here" has two
    histories and the row does not say which. That judgement is invariant-shaped
    for invoice children and does NOT generalise: there is no equivalent of
    "would this still foot?" for a customer or a product. Auto-repairing 19 more
    tables on a rule nobody has written would be a bigger defect than the one it
    closes. So: count it, name it, show it — and let a human decide.

    SYNC LAG IS NOT DIVERGENCE
    --------------------------
    A row written locally two seconds ago has not been pushed yet. Counting it as
    "missing on the cloud" would make this sweep cry wolf on every healthy
    system. Rows still sitting unsent in `sync_queue` are therefore excluded: a
    local-only row that is NOT queued is one sync will never deliver on its own,
    and that is the thing worth reporting.
    """
    tables = _parity_presence_tables()
    per_table: dict = {}

    for table in tables:
        try:
            # Local rows for this business that are NOT still waiting in the
            # outbox. Plain SQL, portable on both engines (no `INSERT OR IGNORE`
            # lesson repeated here).
            rows = db.execute(text(
                f"SELECT uid FROM {table} "
                f"WHERE business_id = :bid AND uid IS NOT NULL "
                f"AND id NOT IN ("
                f"  SELECT entity_id FROM sync_queue "
                f"  WHERE entity = :tbl AND synced_at IS NULL AND entity_id IS NOT NULL"
                f")"
            ), {"bid": business_id, "tbl": table}).fetchall()
            local_uids = {r[0] for r in rows}
        except Exception as e:
            # Unreadable is NOT empty (rule 33). Record and skip the table rather
            # than reporting every cloud row as missing here.
            summary["errors"].append(f"presence {table}: {e}")
            logger.warning("[PARITY] biz=%s: presence scan could not read %s: %s",
                           business_id, table, e)
            continue

        cloud_rows = cloud_data.get(table) or []
        cloud_uids = {r.get("uid") for r in cloud_rows if r.get("uid")}
        no_uid = sum(1 for r in cloud_rows if not r.get("uid"))

        local_only = local_uids - cloud_uids
        cloud_only = cloud_uids - local_uids

        summary["presence_no_uid"] += no_uid
        summary["presence_local_only"] += len(local_only)
        summary["presence_cloud_only"] += len(cloud_only)
        summary["tables_compared"] += 1

        if local_only or cloud_only or no_uid:
            per_table[table] = {
                "local_only": len(local_only),
                "cloud_only": len(cloud_only),
                "no_uid": no_uid,
            }
            # An ENTIRE table present here and absent there is a different
            # statement from N missing rows — it is what an older cloud that does
            # not know the table looks like. Say so, rather than reporting every
            # row as a divergence.
            if local_uids and not cloud_uids:
                logger.warning(
                    "[PARITY] biz=%s: the cloud returned NO %s rows at all while "
                    "this device holds %s. That may be a genuinely empty table on "
                    "the cloud, or a cloud build that does not sync %s — the "
                    "snapshot cannot tell them apart. Reported, not repaired.",
                    business_id, table, len(local_uids), table,
                )
            else:
                logger.warning(
                    "[PARITY] biz=%s: %s — %s row(s) here not on the cloud, "
                    "%s row(s) on the cloud not here%s. Detection only; nothing "
                    "was queued or imported. local_only=%s cloud_only=%s",
                    business_id, table, len(local_only), len(cloud_only),
                    f", {no_uid} cloud row(s) carry no uid and cannot be matched"
                    if no_uid else "",
                    sorted(local_only)[:5], sorted(cloud_only)[:5],
                )

    summary["presence_by_table"] = per_table


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
        "missing":       0,     # here, not on the cloud
        "cloud_only":    0,     # on the cloud, not here (added 2026-08-01)
        "cloud_only_withheld": 0,   # …and would break an invariant if imported
        "over_paid":     0,     # cloud payments sum to MORE than the invoice total
        "paid_state":    0,
        # ── Presence sweep (added 2026-08-03) ────────────────────────────────
        # Detection-only row comparison across every business-scoped synced
        # table. `tables_compared` / `tables_total` are the DENOMINATOR: an
        # all-clear that does not say how much it looked at is the failure this
        # sweep was guilty of for months (2 of 25 tables, reported as
        # "cloud parity OK"). Anything rendering this must show both numbers.
        "tables_compared":     0,
        "tables_total":        len(_MODEL_MAP),
        "presence_local_only": 0,   # here, not on the cloud, and NOT queued
        "presence_cloud_only": 0,   # on the cloud, not here
        "presence_no_uid":     0,   # cloud rows that cannot be matched at all
        "presence_by_table":   {},
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

    # ── The parameter name matters, and it was wrong ──────────────────────────
    # This read `params={"since": "2020-01-01T00:00:00"}` until 2026-08-01.
    # `/api/sync/pull` has no `since` parameter — its signature is
    # `pull_changes(last_sync_at, limit, ...)` — and FastAPI silently drops
    # unknown query params. So `last_sync_at` arrived as None, the endpoint fell
    # through to `datetime(1970, 1, 1)`, and the "2020" in that string had never
    # had any effect in the lifetime of this function.
    #
    # The behaviour was accidentally correct (parity DOES want everything, see
    # below) which is why nothing caught it. It is fixed because the next person
    # to narrow that window would have watched their change do nothing.
    #
    # NO `limit` — deliberate, and the endpoint's own docstring says so. Parity
    # decides whether a local row is ABSENT from the cloud, and absence cannot
    # be read off a page that stopped early; the `has_more` guard below refuses
    # to judge a truncated snapshot for exactly that reason.
    #
    # The cost is a large request. It timed out at 180 s against the live Space
    # on 2026-08-01, which is the same request shape that was failing when the
    # LCL-OW-0037 payment was lost. `/health` is pinged first so a sleeping HF
    # Space wakes on a cheap call instead of burning the read budget on a cold
    # start — the difference between "the Space was asleep" and "the endpoint
    # cannot answer", which are not the same problem.
    try:
        httpx.get(f"{CLOUD_URL}/health", timeout=10.0)
    except Exception:
        pass        # best-effort warm-up; the real request reports the failure
    try:
        resp = httpx.get(
            f"{CLOUD_URL}/api/sync/pull",
            params={"last_sync_at": "1970-01-01T00:00:00"},
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
    # A TRUNCATED snapshot is as unusable here as an unread table, for exactly
    # the same reason: parity's job is deciding whether a local row is absent on
    # the cloud, and "absent" cannot be read off a page that stopped early. The
    # request above deliberately sends no `limit`, so this should never fire —
    # it is the guard for the day someone adds a server-side default.
    if isinstance(body, dict) and body.get("has_more"):
        summary["errors"].append("truncated cloud snapshot (has_more)")
        logger.warning(
            "[PARITY] biz=%s: SKIPPING — the cloud truncated this snapshot "
            "(tables: %s). Judging MISSING from a partial page would queue "
            "repairs for rows that are simply on the next page.",
            business_id, body.get("truncated_tables"),
        )
        return summary

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
                        # Plain INSERT, not `INSERT OR IGNORE`: that is SQLite-only
                        # syntax and a hard SyntaxError on Postgres, which then
                        # ABORTS THE WHOLE TRANSACTION (rule 58) — and the handler
                        # below only logs, so every later statement on this session
                        # died with InFailedSqlTransaction. Proven by CI on
                        # 2026-08-03. `sync_queue` has no unique constraint, so
                        # OR IGNORE never suppressed anything: dropping it is
                        # behaviour-identical on SQLite and portable.
                        "INSERT INTO sync_queue "
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
                        # Plain INSERT, not `INSERT OR IGNORE`: that is SQLite-only
                        # syntax and a hard SyntaxError on Postgres, which then
                        # ABORTS THE WHOLE TRANSACTION (rule 58) — and the handler
                        # below only logs, so every later statement on this session
                        # died with InFailedSqlTransaction. Proven by CI on
                        # 2026-08-03. `sync_queue` has no unique constraint, so
                        # OR IGNORE never suppressed anything: dropping it is
                        # behaviour-identical on SQLite and portable.
                        "INSERT INTO sync_queue "
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

        # ── 5b. CLOUD-ONLY: on the cloud, never landed here ───────────────────
        #
        # Everything above iterates `local_map` — LOCAL rows — and asks what the
        # cloud is missing. So parity could only ever see one of the two ways
        # these databases diverge. The other way is what LCL-OW-0037 cost:
        #
        #   30 Jul 11:43 UTC  a ₹124 settlement is recorded ON THE CLOUD.
        #   30 Jul 11:43:26   the pull starts timing out (10s HTTP timeout at the
        #                     time) and keeps failing for the next hour.
        #   ...               the row never reaches this database.
        #   31 Jul 18:58      the invoice still reads Pending / ₹0 paid here, so
        #                     the owner settles it AGAIN, by cheque. That pushes.
        #   →                 the cloud now holds ₹248 against a ₹124 invoice.
        #
        # Parity ran throughout and reported nothing, because a cloud row absent
        # locally was outside the only question it asked. A one-directional
        # consistency check is not a consistency check; it is half of one, and
        # the missing half is the half that lets money be paid twice.
        #
        # The recovery is the INBOX, not a write from here. `inbox.drain` calls
        # `_apply_pulled_row` — the same single apply path the pull uses — so the
        # row still gets the uid dedup, the FK-by-uid resolution, the LWW rules
        # and the post-apply hooks. A direct INSERT from parity would be a
        # second, untested apply path for financial rows, which is how M-9
        # happened. Parity's job here is only to NOTICE and hand over.
        #
        # This is also the only way these rows can ever arrive: the pull cursor
        # is long past their `updated_at`, so no ordinary cycle will re-offer
        # them. Without this they are permanently invisible to both directions.
        #
        # ── WHY "ABSENT HERE" IS NOT THE SAME AS "NEVER ARRIVED" ──────────────
        #
        # A row on the cloud and not here has TWO possible histories, and this
        # scan cannot tell them apart from the data alone:
        #
        #   (a) it never arrived            — the LCL-OW-0037 case. Import it.
        #   (b) it arrived and was DELETED  — a repair ran here. Importing it
        #                                     UNDOES the repair.
        #
        # (b) is not hypothetical. `scripts/repair_line_items_by_invariant.py`
        # deletes duplicate `invoice_line_items`, and it does so over a RAW
        # connection — so `Mapper.after_delete` never fires and no DELETE is
        # queued for the cloud. The cloud keeps its copies. Measured on the
        # cloud's own boot log, 2026-08-01: **31 invoices and 2 b2b_orders still
        # hold more line value than was billed**, while the local database is
        # down to 3 rows worth ₹0.04 — precisely because the repair ran HERE and
        # not there. Every one of those cloud line items is "absent here".
        #
        # Importing them would re-corrupt this database on the next sweep, and
        # keep doing it after every repair, for ever. That is a worse defect
        # than the one this scan was written to fix.
        #
        # There is no tombstone to distinguish (a) from (b), so the rule is:
        # NEVER let the recovery path violate the invariant the rest of the
        # system enforces. A row is imported only if it FITS.
        local_uids_present = set(local_map.keys())
        _cloud_only = [u for u in cloud_uids_present if u not in local_uids_present]
        if _cloud_only:
            _by_uid = {r.get("uid"): r for r in cloud_rows if r.get("uid")}
            _handed_over, _withheld = 0, []
            for _cuid in sorted(_cloud_only):
                _crow = _by_uid.get(_cuid)
                if _crow is None:
                    continue
                _fits, _why = _cloud_only_row_fits(
                    db, business_id, table, _crow, cloud_invs, local_inv_uid_to_id)
                if not _fits:
                    _withheld.append((_cuid, _why))
                    continue
                if _inbox.remember(
                    db,
                    business_id=business_id,
                    entity=table,
                    record=_crow,
                    reason="cloud-only",
                    error="present on the cloud, absent here — the pull never "
                          "delivered it and the cursor has moved past it",
                ) is not None:
                    _handed_over += 1
            summary.setdefault("cloud_only", 0)
            summary["cloud_only"] += _handed_over
            summary.setdefault("cloud_only_withheld", 0)
            summary["cloud_only_withheld"] += len(_withheld)
            logger.error(
                "[PARITY] biz=%s: %s %s row(s) exist on the CLOUD but not in "
                "this database. Handed %s to the inbox; WITHHELD %s that would "
                "break an invariant here. uids=%s%s",
                business_id, len(_cloud_only), table, _handed_over,
                len(_withheld), sorted(_cloud_only)[:10],
                " (truncated)" if len(_cloud_only) > 10 else "",
            )
            for _cuid, _why in _withheld[:10]:
                logger.error(
                    "[PARITY] biz=%s: WITHHELD %s uid=%r — %s. Either it was "
                    "deleted here on purpose or it is a duplicate on the cloud; "
                    "importing it would re-create corruption. Needs a human.",
                    business_id, table, _cuid, _why,
                )

    # ── 5c. Presence sweep across every business-scoped table ─────────────────
    # Runs on the snapshot already downloaded above, so it adds no network cost.
    # Detection only — see the function docstring for why it deliberately does
    # not repair. Wrapped because parity is an audit: a failure here must not
    # cost the caller the findings §5 already produced.
    try:
        _parity_presence_sweep(db, business_id, cloud_data, summary)
    except Exception as e:
        summary["errors"].append(f"presence sweep failed: {e}")
        logger.warning("[PARITY] biz=%s: presence sweep failed (non-fatal): %s",
                       business_id, e)

    # ── 6. Commit queued repairs ───────────────────────────────────────────────
    # `cloud_only` is in this condition because `inbox.remember` only db.add()s —
    # it deliberately does not commit, so it can be called from inside the
    # pull-apply loop's transaction. Without it here, the handed-over rows would
    # be rolled back and parity would re-discover them every run for ever.
    if summary["missing"] or summary["wrong_invoice"] or summary["cloud_only"]:
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

        # ── OVER-PAYMENT on the cloud ─────────────────────────────────────────
        # This block used to read `total_amount` and never reference it again,
        # and the whole check below is stored-vs-actual — two numbers that agree
        # perfectly when the SAME invoice has been settled twice. LCL-OW-0037:
        # cloud stored_paid 248.00, cloud actual_paid 248.00, invoice total
        # 124.00. Consistent, reconciled, and twice the money that was owed.
        #
        # Reported, never auto-repaired: which of the two payments is the real
        # one is a question about what happened at the counter, and deleting a
        # payment row is not a decision a background sweep gets to make. It is
        # surfaced so a human can void the duplicate.
        if total_amount > 0 and actual_paid > total_amount + 0.05:
            summary["over_paid"] += 1
            logger.error(
                "[PARITY] biz=%s: cloud invoice uid=%r (%s) has payments summing "
                "to %.2f against a total of %.2f — OVER-PAID by %.2f. This is "
                "usually the same invoice settled on both sides while the pull "
                "was down. Needs a human to void the duplicate; not auto-repaired.",
                business_id, inv_uid, inv.get("invoice_id"),
                actual_paid, total_amount, actual_paid - total_amount,
            )

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
                # Plain INSERT — see the note at the `missing` queue site above:
                # `INSERT OR IGNORE` is SQLite-only and aborts a Postgres
                # transaction. sync_queue has no unique constraint to conflict on.
                "INSERT INTO sync_queue "
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

    # `cloud_only` and `over_paid` are counted here so "parity OK" cannot be
    # logged over a database that is missing cloud rows or holding a double
    # payment. The old total covered only the three local→cloud repairs, so the
    # sweep printed "no drift detected" throughout the LCL-OW-0037 divergence.
    total = (summary["missing"] + summary["wrong_invoice"] + summary["paid_state"]
             + summary["cloud_only"] + summary["cloud_only_withheld"]
             + summary["over_paid"]
             # Presence findings count too. They are not repaired, but an
             # all-clear logged over rows one side is missing is exactly the
             # false reassurance finding 15 was.
             + summary["presence_local_only"] + summary["presence_cloud_only"])

    # THE DENOMINATOR IS NOT OPTIONAL. "No drift detected" means nothing without
    # "…across how much?" — this sweep spent months reporting parity OK while
    # comparing 2 of 25 tables. Every all-clear now states its own coverage.
    coverage = f"{summary['tables_compared']}+2 of {summary['tables_total']} tables"

    if total:
        logger.info(
            "[PARITY] biz=%s: %s finding(s) across %s — wrong_invoice=%s "
            "missing=%s paid_state=%s cloud_only=%s withheld=%s over_paid=%s "
            "presence_local_only=%s presence_cloud_only=%s no_uid=%s",
            business_id, total, coverage,
            summary["wrong_invoice"], summary["missing"], summary["paid_state"],
            summary["cloud_only"], summary["cloud_only_withheld"],
            summary["over_paid"],
            summary["presence_local_only"], summary["presence_cloud_only"],
            summary["presence_no_uid"],
        )
    else:
        logger.info(
            "[PARITY] biz=%s: cloud parity OK — no drift detected across %s",
            business_id, coverage,
        )

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




class _Applied:
    """Outcome of applying ONE pulled row.

    A bare bool is what let a DEFERRED row look identical to an applied one, and
    that ambiguity is the data loss this refactor exists to close.

    status:
      "applied"  — the row is in this database.
      "skipped"  — not applied. See `reason`: SOME skips are decisions and some
                   are failures, and the caller has to be able to tell them
                   apart (see RECOVERABLE_SKIPS below).
      "deferred" — the row is CORRECT but its parent is not local yet. The caller
                   MUST persist it (core/sync/inbox). The cloud will not offer it
                   again once the cursor moves past it.

    WHY `reason` EXISTS (found 2026-08-01, LCL-OW-0037)
    ---------------------------------------------------
    This class shipped asserting that every skip was deliberate and that
    "nothing is lost, so this is NOT inbox material". That was true of three of
    the five skip paths and false of two, and the two are the ones that matter:

      * `no-uid`      — the row cannot be matched, so we decline to write it.
                        The row is REAL and still on the cloud. Declining is
                        right; forgetting is not.
      * `clock-skew`  — the cloud timestamp is >5 min in the future. That is a
                        clock problem, not a data problem, and the very same row
                        applies cleanly once the clocks agree — but only if
                        someone still has it.

    In both, the cursor advances past a row this database never received and the
    cloud never offers it again. That is M-12 exactly, in the branch that said
    it was exempt. The caller now inboxes those two, and only those two.

    The other three ARE decisions and must NOT be retried: `no-identity` (the
    row has neither id nor uid — retrying cannot make it identifiable),
    `lww-local-newer` and `no-updated-at` (we looked at both copies and kept
    ours; re-offering it would just re-lose the same comparison in a loop).
    """
    __slots__ = ("status", "conflicts", "hook_failure", "reason")

    # Skip reasons where the row is real, absent here, and would come back if
    # tried again. `core.sync.inbox` retries with backoff, so a permanent
    # failure costs a bounded number of attempts and then shows up in Ops.
    RECOVERABLE_SKIPS = frozenset({"no-uid", "clock-skew"})

    def __init__(self, status, conflicts=0, hook_failure=None, reason=None):
        self.status = status
        self.conflicts = conflicts
        self.hook_failure = hook_failure
        self.reason = reason

    @property
    def is_lost(self) -> bool:
        """True when this outcome means the row is on the cloud and NOT here."""
        return self.status == "skipped" and self.reason in self.RECOVERABLE_SKIPS

    def __repr__(self):
        return "_Applied(%r, reason=%r, conflicts=%s)" % (
            self.status, self.reason, self.conflicts)


def _apply_pulled_row(db, business_id: int, table_name: str, model_cls, record: dict) -> "_Applied":
    """Apply ONE row pulled from the cloud. THE single apply path.

    Two callers, and that is the whole point:
      * the pull-apply loop, for rows arriving in this cycle;
      * `core.sync.inbox.drain`, for rows held from an earlier cycle.

    One function for both is the same rule `resolve_parent_fk_uids` states for
    itself — "single source of truth for both apply paths ... so the
    resolution/deferral logic can never drift". A separate implementation for
    the drain would mean a second copy of the dedup fallbacks, the LWW rules and
    the conflict hooks, and they would not stay in step.

    RAISES on failure. Recording a rejected row is the caller's job; this
    function does not get to decide the failure was acceptable.
    """
    _conflicts = 0
    _hook_failure = None
    rec_uid = record.get("uid")
    rec_id = record.get("id")
    if not rec_id and not rec_uid:
        return _Applied("skipped", reason="no-identity")

    existing = None
    if hasattr(model_cls, "uid"):
        if not rec_uid:
            logger.warning(
                "[SYNC_WORKER] %s id=%s has NO uid — declining to write it "
                "(Phase C strict enforcement) and holding it in the inbox. The "
                "row exists on the cloud; without a uid we cannot tell an INSERT "
                "from an UPDATE of a row we already have, and guessing wrong "
                "duplicates money.",
                table_name, rec_id
            )
            return _Applied("skipped", reason="no-uid")
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
            return _Applied("skipped", reason="clock-skew")

    if existing and hasattr(existing, "updated_at") and existing.updated_at:
        # (R-5) If the cloud row carries no timestamp we cannot
        # prove it is newer — do NOT clobber an existing local
        # row with a timestamp-less version.
        if not cloud_updated_at:
            logger.debug(
                "[SYNC_WORKER] Skipping %s id=%s — cloud row has no updated_at, keeping local",
                table_name, rec_id,
            )
            return _Applied("skipped", reason="no-updated-at")
        local_updated_at = _parse_dt(existing.updated_at)
        if local_updated_at and local_updated_at > cloud_updated_at:
            # Local version is newer, skip cloud version
            return _Applied("skipped", reason="lww-local-newer")

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
            # On the PULL path `incoming` is the CLOUD row and `existing`
            # is this device's. Without this the ConflictLog columns —
            # and the "This device / Cloud" labels in Ops — come out
            # backwards.
            incoming_is_local=False,
            log_prefix="[SYNC_WORKER]",
        ):
            _conflicts += 1

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
            # Same as the financial hook above: on PULL, `incoming` is the
            # CLOUD row and `existing` is this device's.
            incoming_is_local=False,
            log_prefix="[SYNC_WORKER]",
        ):
            _conflicts += 1


    # Apply field updates inside a per-row SAVEPOINT so a
    # single bad row (e.g. a UNIQUE/constraint clash) is
    # skipped instead of rolling back the entire pull batch.
    with db.begin_nested():
        data = dict(record)

        # (R-12) Business ID Pinning: Ensure the pulled row's
        # business_id is locked to the target business_id so it can
        # never be cross-assigned or detached to a different business.
        #
        # THE BOUNDARY, on the apply side. The incoming `business_id` is the
        # SENDING database's integer and means nothing here — the same business
        # is 7 locally and 42 on the cloud. Re-pinning it to the id this database
        # resolved from the BizID is what makes a synced row land on the right
        # tenant. Writing the foreign integer through would attach the row to
        # whichever local business happens to hold that number.
        # See core/identity.py.
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
        # `business_id=` is passed for the same reason routes/sync.py:593 passes
        # it: without it the UID branch of resolve_parent_fk_uids skips its
        # `AND business_id = :business_id` clause entirely, so a child could
        # resolve its parent through ANOTHER tenant's row. The push path has
        # always been scoped; the pull path was not, and the asymmetry is the
        # thing `resolve_parent_fk_uids` says about itself — "single source of
        # truth for both apply paths … so the resolution/deferral logic can never
        # drift".
        #
        # The raw-FK branch was only half-covered before: it falls back to
        # `data.get("business_id")`, which the re-pin above sets — but line-item
        # tables carry no `business_id` column, so it resolved to None and those
        # rows were unscoped on BOTH branches. Those are exactly the 9 tables
        # that cannot have a composite tenant FK either (no tenant column to put
        # in one), so this call was their only guard and it was not applied.
        if resolve_parent_fk_uids(db, model_cls, data,
                                  business_id=business_id,
                                  log_prefix="[SYNC_WORKER]"):
            return _Applied("deferred")

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
        _hook_failure = _hook
    return _Applied("applied", _conflicts, _hook_failure)


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
    # Rows in backoff are EXCLUDED from the window, not just skipped inside it.
    # The window is `ORDER BY id LIMIT 100`; a permanently-deferred row sitting
    # at the head consumes a slot on every cycle forever, so filtering after the
    # limit would still let stuck rows crowd out fresh ones and eventually starve
    # the business entirely. See SyncQueue.attempts.
    queue_items = (
        db.query(SyncQueue)
        .filter(SyncQueue.business_id == business_id,
                SyncQueue.synced_at.is_(None),
                or_(SyncQueue.next_attempt_at.is_(None),
                    SyncQueue.next_attempt_at <= utc_now()))
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

                # Stamp the echo window BEFORE reading the body. The cloud
                # broadcasts `sync.trigger` + `sync.pull_ping` for this very push
                # to every SSE subscriber of this business — and one of those
                # subscribers is THIS device's own Instant Pull listener, which
                # has no way to tell our push from a remote one. Without this
                # stamp it answers our own echo with another sync run, which
                # pushes, which broadcasts, forever. See
                # `cloud_listener._ECHO_WINDOW_SEC`.
                try:
                    from services import cloud_listener
                    cloud_listener.note_local_push(business_id)
                except Exception:
                    pass   # accelerator bookkeeping; never fail a push for it

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
                        # Held rows keep synced_at NULL (M-20) but now back off,
                        # so a parent that is never coming costs one push per
                        # backoff interval instead of one per cycle.
                        it.attempts = (it.attempts or 0) + 1
                        it.next_attempt_at = now + _push_backoff(it.attempts)
                        continue
                    it.synced_at = now
                    it.error = None
                    it.attempts = 0
                    it.next_attempt_at = None
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

    # The cloud has already refused this business's credentials and the token was
    # dropped. Only an owner login can mint another (`store_cloud_token` clears
    # this flag), so re-asking every cycle cannot succeed — it just writes an
    # ERROR every couple of minutes until the real signal is indistinguishable
    # from the noise, and spends a request per business per cycle doing it.
    if _PULL_AUTH_BLOCKED.get(business_id):
        logger.debug(
            "[SYNC_WORKER] pull skipped for business_id=%s — awaiting a cloud "
            "token; sign in on this device to resume.", business_id)
        return

    # 3. Pull updates from cloud  (only when explicitly requested, do_pull=True)
    try:
        # (R-2) Use the CLOUD-clock cursor captured from the previous pull's
        # `pulled_at`. Comparing a cloud-issued timestamp against cloud rows'
        # `updated_at` removes the local-vs-cloud clock skew that previously
        # caused freshly-updated cloud rows to be silently skipped. On first run
        # after a restart we fall back to the last successful SyncLog timestamp.
        last_sync_str = _get_pull_cursor(db, business_id)
        if not last_sync_str:
            last_success = (
                db.query(SyncLog)
                .filter(SyncLog.business_id == business_id, SyncLog.status == "success")
                .order_by(SyncLog.synced_at.desc())
                .offset(1 if queue_items else 0)
                .first()
            )
            last_sync_str = last_success.synced_at.isoformat() if last_success else None

        params = {"limit": _PULL_PAGE_LIMIT}
        if last_sync_str:
            params["last_sync_at"] = last_sync_str

        resp = httpx.get(f"{CLOUD_URL}/api/sync/pull", params=params, headers=headers, timeout=_PULL_TIMEOUT)
        if resp.status_code == 401:
            # Drop the dead token, THEN stop asking. `_invalidate_cloud_token`
            # removes it entirely, and `ensure_fresh_cloud_token` returns None
            # when there is no token — so the old message here ("will refresh
            # next cycle") described a recovery that could not happen, and the
            # pull retried for ever. Only a login mints a new one.
            _invalidate_cloud_token(business_id)
            _PULL_AUTH_BLOCKED[business_id] = True
            raise Exception(
                "HTTP 401: token rejected by cloud — the stored token has been "
                "dropped and pull is PAUSED for this business. It resumes when "
                "the owner signs in on this device (which provisions a fresh "
                "cloud token); it will NOT recover on its own.")
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text}")

        _resp_json = resp.json()
        pulled = _resp_json.get("changes", {})
        # Capture the server's own pull timestamp, but DON'T advance the cursor
        # yet — we advance it only AFTER the batch is applied & committed below
        # (see end of this try). Advancing here risked skipping rows if the apply
        # step failed after the cursor had already moved past them.
        _cloud_cursor = _resp_json.get("pulled_at")

        # ── TRUNCATED PAGE: the cursor must not jump past the tail ────────────
        # `pulled_at` is the server's clock at response time. Using it after a
        # truncated page would move the cursor past every row the page cap cut
        # off, and those rows would never be offered again — the page cap would
        # have turned a slow pull into silent data loss, which is strictly worse
        # than the livelock it fixes.
        #
        # The safe watermark is the MINIMUM, across truncated tables, of the
        # newest `updated_at` actually received. Rows are ordered ascending by
        # `updated_at`, so every table has been read in full up to that instant;
        # taking the minimum means no table is advanced past what it delivered.
        _pull_has_more = bool(_resp_json.get("has_more"))
        if _pull_has_more:
            _watermarks = []
            for _t in (_resp_json.get("truncated_tables") or []):
                _ts = [
                    _parse_dt(r.get("updated_at"))
                    for r in (_resp_json.get("changes", {}).get(_t) or [])
                    if r.get("updated_at")
                ]
                _ts = [t for t in _ts if t]
                if _ts:
                    _watermarks.append(max(_ts))
            if _watermarks:
                _cloud_cursor = min(_watermarks).isoformat()
                _PULL_MORE_PENDING.add(business_id)
                logger.info(
                    "[SYNC_WORKER] biz=%s: pull truncated at %s row(s)/table; "
                    "advancing the cursor only to %s (the tail of what actually "
                    "arrived) and pulling again next tick.",
                    business_id, _PULL_PAGE_LIMIT, _cloud_cursor,
                )
            else:
                # Truncated, but no usable timestamp to advance to. Holding is
                # the only safe option — advancing would skip the remainder.
                _cloud_cursor = None
                _PULL_MORE_PENDING.add(business_id)
                logger.warning(
                    "[SYNC_WORKER] biz=%s: pull truncated but no updated_at was "
                    "usable to compute a safe watermark — HOLDING the cursor.",
                    business_id,
                )
        else:
            _PULL_MORE_PENDING.discard(business_id)
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
                # Rows whose parent was not local yet. Previously a bare
                # `continue` — counted as applied, recorded nowhere, and gone
                # once the cursor moved. Now held in the inbox and counted here
                # so the progress figures stop lying about them.
                _pull_deferred = 0

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
                        # ONE apply path, shared with the inbox drain — see
                        # _apply_pulled_row. The outcome is explicit because the
                        # three cases need three different answers, and
                        # collapsing them is exactly what lost rows:
                        #
                        #   applied  — done.
                        #   skipped  — SEE `_Applied.reason`. Three of the five
                        #              skip reasons are decisions (we compared
                        #              both copies and kept ours); two are
                        #              failures that leave the row on the cloud
                        #              and NOT here. `is_lost` is the difference,
                        #              and it is inbox material — see the class
                        #              docstring for what LCL-OW-0037 cost.
                        #   deferred — the row is RIGHT but its parent is not
                        #              here yet. This used to be a bare
                        #              `continue`, recorded nowhere, so the
                        #              cursor advanced and the cloud never
                        #              offered the row again. M-20 on the read
                        #              side. It now lands in the inbox and is
                        #              retried on its own schedule.
                        try:
                            _res = _apply_pulled_row(
                                db, business_id, table_name, model_cls, record)
                            _conflicts_logged += _res.conflicts
                            if _res.hook_failure is not None:
                                _apply_failures.append(_res.hook_failure)
                            if _res.status == "deferred":
                                _inbox.remember(
                                    db,
                                    business_id=business_id,
                                    entity=table_name,
                                    record=record,
                                    reason="deferred",
                                    error="parent row not present in this database yet",
                                )
                                _pull_deferred += 1
                            elif _res.is_lost:
                                # The row was offered, declined, and is still on
                                # the cloud. The cursor is about to move past it,
                                # so this is the LAST time we will be shown it.
                                _inbox.remember(
                                    db,
                                    business_id=business_id,
                                    entity=table_name,
                                    record=record,
                                    reason=_res.reason,
                                    error=(
                                        "row has no uid — cannot be matched safely"
                                        if _res.reason == "no-uid" else
                                        "cloud updated_at is >5 min ahead of this "
                                        "machine's clock"
                                    ),
                                )
                                _pull_deferred += 1
                        except Exception as row_err:
                            # M-12: a rejected row is a MISSING row, not a log
                            # line. It is now DURABLE in the inbox and retried
                            # per row, so the cursor no longer has to choose
                            # between stalling all 29 tables and losing this one.
                            _pull_row_failures.append({
                                "entity": table_name,
                                "row_id": record.get("id"),
                                "error": str(getattr(row_err, "orig", row_err)
                                             ).strip().splitlines()[0],
                            })
                            _inbox.remember(
                                db,
                                business_id=business_id,
                                entity=table_name,
                                record=record,
                                reason="rejected",
                                error=str(getattr(row_err, "orig", row_err)
                                          ).strip().splitlines()[0][:500],
                            )
                            _apply_hooks.log_apply_failure(
                                db,
                                business_id=business_id,
                                entity=table_name,
                                entity_id=record.get("id"),
                                payload=dict(record),
                                error=row_err,
                                log_prefix="[SYNC_WORKER]",
                            )

                    if records:
                            # Successes only. Adding len(records) here regardless
                            # is what let the progress bar reach 100% on a batch
                            # that had dropped rows (M-12). Deferred rows are
                            # excluded for the same reason — they have NOT landed.
                            _pull_done += max(
                                0, len(records)
                                - sum(1 for f in _pull_row_failures
                                      if f["entity"] == table_name))

                if _pull_row_failures:
                    logger.error(
                        "[SYNC_WORKER] %s row(s) were REJECTED for biz=%s. They "
                        "are HELD IN THE INBOX with their full payload and are "
                        "retried per row — the cursor no longer has to stall all "
                        "%s tables to protect them: %s",
                        len(_pull_row_failures), business_id, len(_MODEL_MAP),
                        [f"{f['entity']}#{f['row_id']}: {f['error']}"
                         for f in _pull_row_failures],
                    )

                if _pull_deferred:
                    logger.info(
                        "[SYNC_WORKER] %s pulled row(s) for biz=%s are waiting on "
                        "a parent that is not local yet — held in the inbox and "
                        "retried with backoff. Before the inbox existed these "
                        "were dropped silently and counted as applied.",
                        _pull_deferred, business_id,
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
        #
        # ── WHY A REJECTED ROW NO LONGER HOLDS THE CURSOR ─────────────────────
        # M-12 made the cursor the difference between "retried" and "lost", and
        # holding it was the only tool available: the rejected row existed
        # nowhere but in the cloud, so re-pulling the window was the sole way to
        # see it again. That forced a choice between stalling all %s tables and
        # abandoning the row — which is what the old `_PULL_MAX_FAILED_STREAK`
        # branch did, with a CRITICAL log saying the rows "need a human".
        #
        # The row is now DURABLE in `sync_inbox` with its full payload, retried
        # per row with backoff, and visible in Ops. Nothing is lost by moving on,
        # so the cursor advances and later rows are not held hostage. This is
        # exactly how push has always behaved: a stuck outbox row waits its turn
        # while the rest of the queue drains.
        #
        # A PARTIAL pull is different and still holds — see below. Those rows
        # were never received at all, so there is nothing in the inbox to retry.
        if _cloud_cursor:
            _failed_now = len(_pull_row_failures)
            if _failed_now:
                logger.warning(
                    "[SYNC_WORKER] biz=%s: %s row(s) could not be applied this "
                    "cycle. Advancing the cursor anyway — they are held in the "
                    "inbox with their payloads and retry independently, so later "
                    "rows are not blocked behind them.",
                    business_id, _failed_now)
                _PULL_FAILED_STREAK[business_id] = 0
                _set_pull_cursor(db, business_id, _cloud_cursor)
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
                _set_pull_cursor(db, business_id, _cloud_cursor)

        # ── Drain rows held from earlier cycles ───────────────────────────────
        # AFTER this cycle's rows have landed, because the parent a held child is
        # waiting for is very often in the batch we just applied. Draining first
        # would defer every one of them again and double the wait.
        def _drain_apply(_db, _entity, _record):
            _model = _MODEL_MAP.get(_entity)
            if _model is None:
                # The table left the sync map since this row was held. Say which
                # one — a held row that can never apply needs a name, not an
                # AttributeError deep inside the apply path.
                raise RuntimeError(
                    f"entity {_entity!r} is no longer in the sync model map")
            _out = _apply_pulled_row(_db, business_id, _entity, _model, _record)
            # A skip that means "still not here" must report its REASON, not the
            # bare status: `drain` reads this against `_HELD_OUTCOMES` to decide
            # whether the row was delivered or declined, and "skipped" alone
            # would be counted as delivered.
            return _out.reason if _out.is_lost else _out.status

        try:
            _inbox.drain(db, business_id, _drain_apply)
        except Exception as _inbox_err:
            # The inbox is a recovery mechanism. It failing must not take down
            # the pull that is otherwise working.
            logger.warning(
                "[SYNC_WORKER] biz=%s: inbox drain failed (non-fatal, retried "
                "next cycle): %s", business_id, _inbox_err,
            )

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
