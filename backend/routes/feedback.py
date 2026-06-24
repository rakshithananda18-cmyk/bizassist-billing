"""
routes/feedback.py
==================
Answer-quality feedback. Thumbs up/down on an answer; a thumbs-down may name the
intent the user actually wanted, which creates an instant per-query override.

  POST /feedback   {session_id?, query, route?, handler_key?, verdict, correction?}
  GET  /feedback/intents   -> the list of correctable intents (for the UI picker)
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import get_active_user, restrict_cashier
from services.feedback_service import record_feedback, CORRECTION_ROUTES

logger = logging.getLogger("bizassist.routes.feedback")
router = APIRouter()


class FeedbackRequest(BaseModel):
    query:       str
    verdict:     str                      # 'up' | 'down'
    session_id:  Optional[str] = None
    route:       Optional[str] = None
    handler_key: Optional[str] = None
    correction:  Optional[str] = None     # an intent key from /feedback/intents


# Human labels for the correctable intents (drives the down-vote picker).
_INTENT_LABELS = {
    "overdue_list":     "Overdue invoices",
    "overdue_amount":   "Total overdue amount",
    "pending_list":     "Pending invoices",
    "total_revenue":    "Revenue / sales",
    "invoice_count":    "Invoice count",
    "top_customers":    "Top customers",
    "top_debtors":      "Top debtors",
    "inventory_count":  "Inventory count",
    "low_stock":        "Low stock",
    "expiring_soon":    "Expiring soon",
    "client_summary":   "A specific customer",
    "business_summary": "Business overview",
    "ai_complex":       "Deep analysis / plan",
    "ai_simple":        "Write / draft something",
    "conversational":   "Just chatting",
}


@router.get("/feedback/intents")
def feedback_intents(current_user: dict = Depends(restrict_cashier)):
    """The correctable intents, in display order, for the 'what did you want?' picker."""
    return {"intents": [
        {"key": k, "label": _INTENT_LABELS.get(k, k)}
        for k in CORRECTION_ROUTES
    ]}


@router.post("/feedback")
def submit_feedback(body: FeedbackRequest, current_user: dict = Depends(restrict_cashier)):
    if not (body.query or "").strip():
        raise HTTPException(status_code=400, detail="query is required")

    result = record_feedback(
        current_user["id"],
        session_id=body.session_id,
        query=body.query,
        route=body.route,
        handler_key=body.handler_key,
        verdict=body.verdict,
        correction=body.correction,
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result.get("error", "feedback failed"))

    return {
        "ok": True,
        "override": result["override"],
        "message": ("Got it — I'll answer that the right way next time."
                    if result["override"] else "Thanks for the feedback."),
    }
