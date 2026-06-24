"""
routes/smart_insights.py
========================
On-demand Business Advisor. Triggered from the chip bar; pull-only so the heavy
70B reasoning never runs unprompted.

  GET /smart-insights  -> {insights: [...], source, message?}
"""
import logging
from fastapi import APIRouter, Depends

from services.auth import get_active_user, restrict_cashier
from services.smart_insights import generate_insights, build_panel_insights

logger = logging.getLogger("bizassist.routes.smart_insights")
router = APIRouter()


@router.get("/smart-insights")
def smart_insights(current_user: dict = Depends(restrict_cashier)):
    """On-demand, 70B-reasoned advisory (the chat chip)."""
    uid = current_user["id"]
    logger.info(f"[ADVISOR] Generating smart insights for user {uid}...")
    result = generate_insights(uid)
    logger.info(f"[ADVISOR] {len(result.get('insights', []))} insight(s) (source={result.get('source')}) for user {uid}.")
    return result


@router.get("/smart-insights/summary")
def smart_insights_summary(current_user: dict = Depends(restrict_cashier)):
    """Deterministic 'what's working / could be better' split for the right pane —
    free, instant, model-free (no hallucination, safe to auto-load)."""
    return build_panel_insights(current_user["id"])
