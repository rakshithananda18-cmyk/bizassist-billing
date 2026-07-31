"""
core/sync/inbox.py — the PULL-side outbox.
==========================================

Push has `sync_queue`: a row that cannot be delivered stays queued, is visible in
Ops, retries on its own, and blocks nothing else. Pull had no equivalent, and the
two consequences are the reason this module exists.

────────────────────────────────────────────────────────────────────────────────
1. DEFERRED PULL ROWS WERE SILENTLY LOST
────────────────────────────────────────────────────────────────────────────────
`resolve_parent_fk_uids` returns True when a child row's parent is not in this
database yet. Its contract, quoted from its own docstring:

    Returns ``True`` if the row must be **deferred** … it re-applies on a later
    sync once the parent lands.

The pull-apply loop honoured the first half and not the second:

    if resolve_parent_fk_uids(db, model_cls, data, log_prefix="[SYNC_WORKER]"):
        continue                      # ← recorded nowhere

Because nothing was recorded, `_pull_row_failures` stayed empty, so the cursor
advanced. The cloud then never re-offered the row — its `updated_at` had not
changed, and the cursor was already past it. The row was gone, and the progress
bar counted it as applied.

This is **M-20 on the read side**. The push path fixed the identical bug and its
comment still describes it exactly:

    the row is DEFERRED, the client MUST be told … The outbox row was gone, so
    the "later sync" could never happen.

────────────────────────────────────────────────────────────────────────────────
2. A REJECTED ROW FROZE EVERY LATER ROW
────────────────────────────────────────────────────────────────────────────────
The only recovery available was to HOLD the global pull cursor — which blocks all
29 tables — bounded by `_PULL_MAX_FAILED_STREAK`, after which the row was
abandoned with:

    logger.critical("… THESE ROWS REMAIN MISSING … They need a human.")

So the design was forced to choose between stalling everything and losing one
row. Push is never forced to choose: a stuck outbox row waits while the rest
drains.

────────────────────────────────────────────────────────────────────────────────
WHAT THIS MODULE CHANGES
────────────────────────────────────────────────────────────────────────────────
A row that cannot apply is written HERE — durably, with its full payload — and
the cursor advances. Retry is per row with backoff, ordering is preserved by
applying parents before children on every drain, and Ops gets the same depth and
retry controls the outbox has.

SAFETY
------
* Nothing is deleted. A drained row is stamped `applied_at`; a row that keeps
  failing stays visible. Silent disappearance is the defect being fixed, so this
  module must never introduce its own.
* `uid` is the match key. `remote_id` is stored for operator legibility only and
  is NEVER written to a local FK — that is M-9, money on the wrong invoice.
* One live entry per (business, entity, uid): a re-offered row UPDATES its entry
  rather than stacking a second copy.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from database.models import SyncInbox
from services.dates import utc_now

logger = logging.getLogger("bizassist.sync_inbox")

# Per-row backoff. A child waiting on a parent that is still in flight should
# retry quickly; one waiting on a parent that is never coming should not burn a
# query every cycle forever. Index is `attempts`, clamped to the last entry.
_BACKOFF_SECONDS = [0, 15, 60, 300, 900, 3600, 21600]

# Above this, the row stops being retried automatically and waits for a human via
# the Ops console. It is NOT deleted and NOT hidden — see `stats()`.
MAX_AUTO_ATTEMPTS = len(_BACKOFF_SECONDS)

# Parents before children on every drain, mirroring the pull-apply ordering. A
# drain that applied children first would defer them all over again.
_CHILD_LAST = (
    "invoice_line_items", "purchase_order_line_items",
    "purchase_invoice_line_items", "invoice_payments",
    "stock_transfer_line_items", "product_barcodes",
    "stock_ledger", "b2b_ledgers", "shift_cash_movements",
    "b2b_order_line_items",
)


def _next_attempt_at(attempts: int):
    idx = min(attempts, len(_BACKOFF_SECONDS) - 1)
    return utc_now() + timedelta(seconds=_BACKOFF_SECONDS[idx])


# Outcomes from `apply_row` that mean the row is STILL NOT HERE, mapped to the
# operator-facing reason. Anything not in this map counts as applied.
#
# `deferred` was the only member until 2026-08-01. The other two arrived with
# `_Applied.reason`: a held row that comes back `skipped` because it has no uid
# would otherwise be stamped `applied_at` and disappear — the inbox marking a
# row as delivered when it was declined, which is the exact failure the inbox
# exists to prevent, reintroduced one layer in.
_HELD_OUTCOMES = {
    "deferred":   "parent row not present in this database yet",
    "no-uid":     "row has no uid — cannot be matched safely",
    "clock-skew": "cloud updated_at is >5 min ahead of this machine's clock",
}


# ─────────────────────────────────────────────────────────────────────────────
# WRITE
# ─────────────────────────────────────────────────────────────────────────────

def remember(
    db: Session,
    *,
    business_id: int,
    entity: str,
    record: Dict[str, Any],
    reason: str,
    error: Optional[str] = None,
) -> Optional[SyncInbox]:
    """Persist one un-appliable pulled row so it can be retried later.

    `reason` is 'deferred' (parent not local yet — expected, usually transient)
    or 'rejected' (the apply raised — usually not transient).

    Returns the row, or None if it could not be recorded. A failure here is
    logged at ERROR and never raised: this is called from inside the pull-apply
    loop, and taking the whole pull down to report one row would be a worse
    trade than the bug it is reporting.
    """
    uid = record.get("uid")
    remote_id = record.get("id")

    if not uid and remote_id is None:
        # Nothing to match on later — re-applying it would be guesswork about
        # which row it was. Say so loudly rather than store an unusable entry.
        logger.error(
            "[SYNC_INBOX] biz=%s %s: cannot record an un-appliable row with "
            "neither uid nor id — it is LOST. reason=%s error=%s",
            business_id, entity, reason, error,
        )
        return None

    try:
        existing = None
        if uid:
            existing = (
                db.query(SyncInbox)
                .filter(
                    SyncInbox.business_id == business_id,
                    SyncInbox.entity == entity,
                    SyncInbox.uid == uid,
                    SyncInbox.applied_at.is_(None),
                )
                .first()
            )

        if existing is not None:
            # Re-offered before it drained. Refresh the payload (the cloud copy
            # may have moved on) but keep `attempts` so backoff is not reset by
            # an unrelated pull — otherwise a row the cloud sends every cycle
            # would retry every cycle regardless of how often it has failed.
            existing.payload = json.dumps(record, default=str)
            existing.reason = reason
            existing.error = error
            if existing.next_attempt_at is None:
                existing.next_attempt_at = _next_attempt_at(existing.attempts)
            return existing

        row = SyncInbox(
            business_id=business_id,
            entity=entity,
            uid=uid,
            remote_id=remote_id if isinstance(remote_id, int) else None,
            payload=json.dumps(record, default=str),
            reason=reason,
            error=error,
            attempts=0,
            next_attempt_at=_next_attempt_at(0),
        )
        db.add(row)
        logger.info(
            "[SYNC_INBOX] biz=%s recorded %s uid=%r as %s — it will be retried "
            "and is visible in Ops (previously this row was dropped silently)",
            business_id, entity, uid, reason,
        )
        return row
    except Exception as e:
        logger.error(
            "[SYNC_INBOX] biz=%s FAILED to record un-appliable %s uid=%r: %s",
            business_id, entity, uid, e, exc_info=True,
        )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────────

def due_rows(db: Session, business_id: int, limit: int = 200) -> List[SyncInbox]:
    """Un-applied rows whose backoff has elapsed, parents before children."""
    now = utc_now()
    rows = (
        db.query(SyncInbox)
        .filter(
            SyncInbox.business_id == business_id,
            SyncInbox.applied_at.is_(None),
            SyncInbox.attempts < MAX_AUTO_ATTEMPTS,
            (SyncInbox.next_attempt_at.is_(None)) | (SyncInbox.next_attempt_at <= now),
        )
        .order_by(SyncInbox.created_at.asc(), SyncInbox.id.asc())
        .limit(limit)
        .all()
    )
    return sorted(rows, key=lambda r: 1 if r.entity in _CHILD_LAST else 0)


def stats(db: Session, business_id: int) -> Dict[str, Any]:
    """Inbox depth for the Ops console — the pull-side mirror of queue depth.

    `stuck` counts rows past MAX_AUTO_ATTEMPTS. They are not retried
    automatically and not deleted; they are exactly the population the outbox's
    "Retry Item" button exists for, and the reason this number is surfaced at all
    is that its predecessor was a CRITICAL log line nobody was reading.
    """
    pending = (
        db.query(SyncInbox)
        .filter(SyncInbox.business_id == business_id,
                SyncInbox.applied_at.is_(None))
        .all()
    )
    by_entity: Dict[str, int] = {}
    stuck = 0
    for r in pending:
        by_entity[r.entity] = by_entity.get(r.entity, 0) + 1
        if r.attempts >= MAX_AUTO_ATTEMPTS:
            stuck += 1
    # Reasons grew past {deferred, rejected} on 2026-08-01 (no-uid, clock-skew).
    # `by_reason` is the open-ended one so a reason added later still shows up
    # instead of silently landing in neither named bucket; the two named counts
    # stay for the existing Ops panel contract.
    by_reason: Dict[str, int] = {}
    for r in pending:
        by_reason[r.reason or "unknown"] = by_reason.get(r.reason or "unknown", 0) + 1
    return {
        "pending_count": len(pending),
        "entity_counts": by_entity,
        "stuck_count": stuck,
        "reason_counts": by_reason,
        "deferred_count": sum(1 for r in pending if r.reason == "deferred"),
        "rejected_count": sum(1 for r in pending if r.reason == "rejected"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# DRAIN
# ─────────────────────────────────────────────────────────────────────────────

def drain(db: Session, business_id: int, apply_row, limit: int = 200) -> Dict[str, int]:
    """Retry every due row. `apply_row(db, entity, record) -> None` applies one
    row and raises on failure — the same callable the pull-apply loop uses, so
    the two paths cannot drift.

    Each row applies inside its own SAVEPOINT: one poison row must not roll back
    the rows that drained successfully alongside it. That is the same isolation
    the push path uses per row, and its absence is what turns a single bad row
    into a whole failed batch.
    """
    rows = due_rows(db, business_id, limit=limit)
    result = {"attempted": len(rows), "applied": 0, "deferred": 0, "failed": 0}
    if not rows:
        return result

    for row in rows:
        try:
            record = json.loads(row.payload)
        except Exception as e:
            row.attempts += 1
            row.last_attempt_at = utc_now()
            row.next_attempt_at = _next_attempt_at(row.attempts)
            row.error = f"unreadable payload: {e}"
            result["failed"] += 1
            logger.error("[SYNC_INBOX] biz=%s %s#%s payload is not readable: %s",
                         business_id, row.entity, row.id, e)
            continue

        row.attempts += 1
        row.last_attempt_at = utc_now()
        try:
            with db.begin_nested():
                outcome = apply_row(db, row.entity, record)
            if outcome in _HELD_OUTCOMES:
                # Still not here. Expected while a backlog drains (a parent in
                # flight, a clock being corrected); back off rather than spinning
                # on it every cycle. Record WHICH reason — "deferred" for a
                # uid-less row would be a wrong answer in the one place an
                # operator goes to look.
                row.reason = outcome
                row.error = _HELD_OUTCOMES[outcome]
                row.next_attempt_at = _next_attempt_at(row.attempts)
                result["deferred"] += 1
            else:
                row.applied_at = utc_now()
                row.error = None
                result["applied"] += 1
                logger.info(
                    "[SYNC_INBOX] biz=%s applied held %s uid=%r after %s attempt(s)",
                    business_id, row.entity, row.uid, row.attempts,
                )
        except Exception as e:
            row.reason = "rejected"
            row.error = str(getattr(e, "orig", e)).strip().splitlines()[0][:500]
            row.next_attempt_at = _next_attempt_at(row.attempts)
            result["failed"] += 1
            logger.warning(
                "[SYNC_INBOX] biz=%s %s uid=%r still not appliable (attempt %s/%s): %s",
                business_id, row.entity, row.uid, row.attempts,
                MAX_AUTO_ATTEMPTS, row.error,
            )

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("[SYNC_INBOX] biz=%s drain commit failed: %s", business_id, e)

    if result["applied"] or result["failed"] or result["deferred"]:
        logger.info(
            "[SYNC_INBOX] biz=%s drain: attempted=%s applied=%s still-deferred=%s failed=%s",
            business_id, result["attempted"], result["applied"],
            result["deferred"], result["failed"],
        )
    return result


def requeue(db: Session, business_id: int, inbox_id: int) -> bool:
    """Ops "Retry" — clear the backoff and the attempt count for one row.

    The outbox equivalent had to also SCHEDULE a run, because clearing `error`
    alone changed nothing the worker selected on. Same lesson applies here: the
    caller must trigger a drain, or this is a button that only looks busy.
    """
    row = (
        db.query(SyncInbox)
        .filter(SyncInbox.id == inbox_id, SyncInbox.business_id == business_id)
        .first()
    )
    if row is None or row.applied_at is not None:
        return False
    row.attempts = 0
    row.next_attempt_at = utc_now()
    row.error = None
    db.commit()
    return True
