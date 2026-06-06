"""
intents.py — Tier 0 of the agentic engine.

Resolves a known "intent" (a common, predictable question behind a chip / alert
card / dashboard button) straight from the database with ZERO AI tokens, and
attaches Tier-1 next-step suggestions.

Reuses the existing deterministic handlers in direct_query_handler.py — no logic
is duplicated. Add a new button by adding one line to INTENT_MAP.

Returns the unified response envelope:
    { answer: {type,title,markdown}, source, suggestions[], meta }
or None if the intent is unknown (caller may fall back to the AI path).
"""
import logging
from services.direct_query_handler import handle as _direct
from services.recommendations import recommend

logger = logging.getLogger("bizassist.intents")

# intent_key (frontend) -> direct_query_handler key (backend)
INTENT_MAP = {
    "invoice_count":    "invoice_count",
    "total_revenue":    "total_revenue",
    "revenue_summary":  "total_revenue",
    "overdue_list":     "overdue_list",
    "overdue_amount":   "overdue_amount",
    "pending_list":     "pending_list",
    "top_customers":    "top_customers",
    "top_debtors":      "overdue_list",
    "inventory_count":  "inventory_count",
    "low_stock":        "low_stock",
    "expiring_soon":    "expiring_soon",
    "business_summary": "business_summary",
}

TITLES = {
    "invoice_count":    "Invoice Summary",
    "total_revenue":    "Revenue",
    "revenue_summary":  "Revenue Summary",
    "overdue_list":     "Overdue Invoices",
    "overdue_amount":   "Overdue Amount",
    "pending_list":     "Pending Invoices",
    "top_customers":    "Top Customers",
    "top_debtors":      "Top Debtors",
    "inventory_count":  "Inventory",
    "low_stock":        "Low Stock",
    "expiring_soon":    "Expiring Soon",
    "business_summary": "Business Snapshot",
}


def is_intent(intent_key: str) -> bool:
    return intent_key in INTENT_MAP


def resolve_intent(intent_key: str, user_id: int, params: dict = None) -> dict | None:
    handler_key = INTENT_MAP.get(intent_key)
    if not handler_key:
        return None

    query = (params or {}).get("query", "")
    try:
        markdown = _direct(handler_key, query, user_id)
    except Exception as e:
        logger.error(f"resolve_intent('{intent_key}') failed: {e}", exc_info=True)
        return None

    if markdown is None:
        return None

    return {
        "answer": {
            "type": "text",
            "title": TITLES.get(intent_key, intent_key.replace("_", " ").title()),
            "markdown": markdown,
        },
        "source": "db",
        "suggestions": recommend(intent_key, user_id),
        "meta": {"tokens": 0},
    }
