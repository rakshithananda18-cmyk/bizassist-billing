"""
services/feedback_service.py
============================
The answer-quality feedback loop. Thumbs up/down is logged to `Feedback`; a
thumbs-down that names what the user actually wanted creates a `QueryOverride`
so the SAME query routes correctly on re-run (the instant-correction shortcut).

Corrections are user-supplied and exact-query scoped — deliberately NOT blind
auto-learning from raw traffic, which drifts. Similar-but-different phrasings
are improved offline by tuning seeds from the collected feedback.
"""
import logging

from database.db import SessionLocal
from database.models import AIFeedback, AIQueryOverride

logger = logging.getLogger("bizassist.feedback")

# The intents a user may correct an answer TO → (route, handler_key).
_DIRECT_HANDLERS = [
    "invoice_count", "total_revenue", "overdue_list", "overdue_amount",
    "pending_list", "top_debtors", "top_customers", "inventory_count",
    "low_stock", "expiring_soon", "client_summary", "business_summary",
]
CORRECTION_ROUTES = {k: ("DIRECT", k) for k in _DIRECT_HANDLERS}
CORRECTION_ROUTES.update({
    "ai_complex":     ("AI_COMPLEX", None),     # deep analysis / plan
    "ai_simple":      ("AI_SIMPLE", None),      # writing / general
    "conversational": ("CONVERSATIONAL", None),
})


def normalize_query(q: str) -> str:
    """Lowercase + whitespace-collapse — the key an override is matched on."""
    return " ".join((q or "").lower().split())


def record_feedback(business_id: int, *, session_id, query, route, handler_key,
                    verdict: str, correction: str = None) -> dict:
    """
    Log a vote. If `verdict` is 'down' and `correction` is a known intent, upsert
    a QueryOverride and invalidate the user's cache so re-running recomputes.
    Returns {"ok": bool, "override": bool, "error": str?}.
    """
    verdict = (verdict or "").lower()
    if verdict not in ("up", "down"):
        return {"ok": False, "override": False, "error": "verdict must be 'up' or 'down'"}

    correction = (correction or "").strip() or None
    if correction and correction not in CORRECTION_ROUTES:
        return {"ok": False, "override": False, "error": f"unknown correction '{correction}'"}

    db = SessionLocal()
    try:
        db.add(AIFeedback(
            business_id=business_id, session_id=session_id, query=query,
            route=route, handler_key=handler_key, verdict=verdict, correction=correction,
        ))

        made_override = False
        if verdict == "down" and correction:
            norm = normalize_query(query)
            new_route, new_handler = CORRECTION_ROUTES[correction]
            existing = db.query(AIQueryOverride).filter(
                AIQueryOverride.business_id == business_id,
                AIQueryOverride.query_norm == norm,
            ).first()
            if existing:
                existing.route, existing.handler_key = new_route, new_handler
            else:
                db.add(AIQueryOverride(
                    business_id=business_id, query_norm=norm,
                    route=new_route, handler_key=new_handler,
                ))
            made_override = True

        db.commit()

        if made_override:
            # Bust this tenant's cache so the corrected query doesn't serve the
            # old (wrong) cached answer on re-run.
            try:
                from services.context_cache import invalidate_user_cache
                invalidate_user_cache(business_id)
            except Exception as e:
                logger.debug(f"[FEEDBACK] cache invalidate skipped: {e}")
            logger.info(f"[FEEDBACK] override set user={business_id} → {correction} q='{query[:60]}'")

        return {"ok": True, "override": made_override}
    except Exception as e:
        db.rollback()
        logger.error(f"[FEEDBACK] {e}", exc_info=True)
        return {"ok": False, "override": False, "error": "failed to record feedback"}
    finally:
        db.close()


def get_override(business_id: int, query: str):
    """Return (route, handler_key) if this user has corrected this exact query, else None."""
    norm = normalize_query(query)
    if not norm:
        return None
    db = SessionLocal()
    try:
        ov = db.query(AIQueryOverride).filter(
            AIQueryOverride.business_id == business_id,
            AIQueryOverride.query_norm == norm,
        ).first()
        return (ov.route, ov.handler_key) if ov else None
    except Exception as e:
        logger.debug(f"[FEEDBACK] override lookup failed: {e}")
        return None
    finally:
        db.close()
