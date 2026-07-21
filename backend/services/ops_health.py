"""
services/ops_health.py — one per-tenant operational-health snapshot.
====================================================================
Shared by the owner route (`GET /reports/ops-health`, scoped to the caller) and
the admin route (`GET /admin/business/{id}/ops-health`, any business). Aggregates
the observability signals that were previously scattered or invisible:

  • sync backlog  — unsynced outbox rows, how many errored, oldest age
  • conflicts     — unreviewed financial sync conflicts (surfaced for review)
  • integrity     — tamper-evident hash chain + journal foots (drift)
  • ai_usage      — today's queries/tokens vs limit (cost signal)

Every section fails SOFT: a problem gathering one signal never breaks the whole
view. `ok` is False if anything needs attention.
"""
import logging

from sqlalchemy import func

logger = logging.getLogger("bizassist.ops_health")


def compute_ops_health(db, business_id: int) -> dict:
    from database.models import SyncQueue, ConflictLog
    bid = business_id

    # ── Sync backlog ─────────────────────────────────────────────────────────
    sync = {"pending": 0, "failed": 0, "oldest_pending_at": None}
    try:
        pend = (db.query(SyncQueue)
                .filter(SyncQueue.business_id == bid, SyncQueue.synced_at.is_(None))
                .order_by(SyncQueue.created_at.asc()).all())
        sync["pending"] = len(pend)
        sync["failed"] = sum(1 for r in pend if r.error)
        sync["oldest_pending_at"] = pend[0].created_at.isoformat() if pend else None
    except Exception as e:
        logger.warning("[OPS] sync backlog gather failed bid=%s: %s", bid, e)

    # ── Unreviewed sync conflicts ────────────────────────────────────────────
    conflicts = {"unreviewed": 0}
    try:
        conflicts["unreviewed"] = (
            db.query(func.count(ConflictLog.id))
            .filter(ConflictLog.business_id == bid,
                    ConflictLog.resolution == "review_needed",
                    ConflictLog.resolved_at.is_(None))
            .scalar()
        ) or 0
    except Exception as e:
        logger.warning("[OPS] conflict gather failed bid=%s: %s", bid, e)

    # ── Books integrity ──────────────────────────────────────────────────────
    integrity_report = {"ok": None}
    try:
        from core.accounting.integrity import run_integrity_check
        r = run_integrity_check(db, bid)
        integrity_report = {
            "ok": r["ok"],
            "hash_chain_ok": r["hash_chain"].get("ok"),
            "journal_drift": r["journal_balance"].get("drift"),
        }
    except Exception as e:
        logger.warning("[OPS] integrity gather failed bid=%s: %s", bid, e)

    # ── AI usage today ───────────────────────────────────────────────────────
    ai = {}
    try:
        from services.rate_limiter import get_usage_summary
        u = get_usage_summary(bid)
        ai = {
            "queries_today": u.get("queries_today"),
            "tokens_today": u.get("tokens_today"),
            "tokens_limit": u.get("tokens_limit"),
        }
    except Exception as e:
        logger.warning("[OPS] AI usage gather failed bid=%s: %s", bid, e)

    overall_ok = (sync["failed"] == 0
                  and conflicts["unreviewed"] == 0
                  and integrity_report.get("ok") is not False)

    return {
        "ok": overall_ok,
        "business_id": bid,
        "sync": sync,
        "conflicts": conflicts,
        "integrity": integrity_report,
        "ai_usage": ai,
    }
