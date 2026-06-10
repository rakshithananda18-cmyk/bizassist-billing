"""
direct_query_handler.py
=======================
Tier-0 router -- maps handler_key strings to domain handler functions.
"""
import re
import logging
from services.handlers.payments  import _overdue_list, _overdue_amount, _pending_list, _top_debtors
from services.handlers.invoices  import _invoice_count, _total_revenue, _overdue_range_detail, _revenue_month_detail
from services.handlers.inventory import _inventory_count, _low_stock, _expiring_soon
from services.handlers.clients   import _top_customers, _client_summary
from services.handlers.dashboard import _business_summary

logger = logging.getLogger("bizassist.direct_query")

HANDLERS = {
    "invoice_count":        _invoice_count,
    "total_revenue":        _total_revenue,
    "revenue_summary":      _total_revenue,
    "overdue_range_detail": _overdue_range_detail,
    "revenue_month_detail": _revenue_month_detail,
    "overdue_list":         _overdue_list,
    "overdue_amount":       _overdue_amount,
    "pending_list":         _pending_list,
    "top_debtors":          _top_debtors,
    "inventory_count":      _inventory_count,
    "low_stock":            _low_stock,
    "expiring_soon":        _expiring_soon,
    "top_customers":        _top_customers,
    "client_summary":       _client_summary,
    "business_summary":     _business_summary,
}


_ALL_WORDS = {"all", "every", "complete", "full", "entire"}


def _extract_customer_name(query: str, user_id: int):
    """
    Best-effort extraction of a customer name from a free-form query.
    Fetches distinct customer names from the DB and does case-insensitive
    substring matching against the query.  Returns None if no match.
    """
    try:
        from database.db import SessionLocal
        from database.models import Invoice
        db = SessionLocal()
        try:
            names = [r[0] for r in db.query(Invoice.customer)
                     .filter(Invoice.business_id == user_id)
                     .distinct().all()]
        finally:
            db.close()
        q_lower = query.lower()
        matches = [n for n in names if n and n.lower() in q_lower]
        if matches:
            return max(matches, key=len)   # longest match wins
    except Exception as e:
        logger.debug(f"[HANDLER] extract_customer: {e}")
    return None


def _extract_limit(query: str, default: int = 50) -> int:
    """
    Parse an explicit top-N limit from the user query.
    'top 15' / 'show 30' / 'first 10' -> that number.
    'all' / 'every' / 'full list'     -> 0  (meaning no limit).
    Otherwise                             -> default.
    """
    q = query.lower()
    if any(w in q for w in _ALL_WORDS):
        return 0
    m = re.search(r'\b(?:top|show|first|last|only|give\s+me)?\s*(\d+)\b', q)
    if m:
        return int(m.group(1))
    return default


def handle(handler_key: str, user_query: str, user_id: int, params: dict = None):
    """
    Routes handler_key to the correct domain function and returns a
    formatted markdown string, or None if the handler is unknown / errors.
    """
    fn = HANDLERS.get(handler_key)
    if fn is None:
        logger.debug(f"[HANDLER] No handler registered for key: '{handler_key}'")
        return None

    try:
        if handler_key in ("overdue_range_detail", "revenue_month_detail"):
            return fn(user_id, user_query)

        if handler_key == "client_summary":
            customer = (params or {}).get("customer") or _extract_customer_name(user_query, user_id)
            if not customer:
                return None
            return fn(user_id, {"customer": customer})

        if handler_key in ("overdue_list", "pending_list"):
            return fn(user_id, limit=_extract_limit(user_query))

        return fn(user_id)

    except Exception as e:
        logger.error(f"[HANDLER] '{handler_key}' raised an error: {e}", exc_info=True)
        return None
