"""
direct_query_handler.py
=======================
Tier-0 router -- maps handler_key strings to domain handler functions.
"""
import re
import difflib
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

# Returned verbatim (no LLM polish) when a named customer can't be resolved.
CUSTOMER_NOT_FOUND = (
    "I couldn't find a customer matching that name in your records. "
    "Please check the spelling, or ask \"who are my customers?\" to see "
    "the list of names I have."
)

# When a "tell me about ..." query resolves to NO customer, it's either a real
# customer that doesn't exist (-> honest "not found") or a general business ask
# that merely shares the trigger phrase ("tell me about my business") and should
# fall through to the AI. These words mark the latter.
_GENERAL_ABOUT = {
    "business", "company", "firm", "shop", "store", "myself",
    "revenue", "sales", "income", "turnover", "profit", "cash", "flow",
    "overdue", "pending", "unpaid", "outstanding", "invoices", "invoice",
    "payments", "payment", "inventory", "stock", "products", "customers",
    "performance", "overview", "summary", "health", "snapshot", "situation",
    "numbers", "data", "everything", "status", "dashboard", "metrics",
}


def _is_general_about_query(query: str) -> bool:
    """True when a customer-lookup phrasing is actually a general business ask."""
    toks = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
    return bool(toks & _GENERAL_ABOUT)


# Min average token similarity (0..1) to accept a fuzzy customer match. High
# enough to reject unrelated words, low enough to absorb typos/dropped letters.
_CUSTOMER_FUZZY_THRESHOLD = 0.82


def _match_customer_name(query: str, names, threshold: float = _CUSTOMER_FUZZY_THRESHOLD):
    """
    Resolve a customer name from free text against the known names (H8). Pure
    (no DB) so it's unit-testable.

      1. Exact case-insensitive substring — fast and precise for clean queries.
      2. Token-set fuzzy match — tolerant of typos ("nilgris"), casing, dropped
         letters ("nilgiri"), and word order ("fresh nilgiris").

    The DB always owns the candidate names; this only chooses among them — it
    never invents a customer. Returns the matched name, or None.
    """
    q_lower = (query or "").lower()
    clean = [n for n in names if n]
    if not clean or not q_lower.strip():
        return None

    # 1. exact substring (longest wins)
    subs = [n for n in clean if n.lower() in q_lower]
    if subs:
        return max(subs, key=len)

    # 2. token-set fuzzy
    q_tokens = re.findall(r"[a-z0-9]+", q_lower)
    if not q_tokens:
        return None
    best, best_score = None, 0.0
    for n in clean:
        n_tokens = re.findall(r"[a-z0-9]+", n.lower())
        if not n_tokens:
            continue
        # average, over the name's tokens, of each token's best fuzzy ratio
        # against any query token — so every word of the name must be present
        # (in some form) for a high score, which keeps false positives down.
        per_token = [
            max((difflib.SequenceMatcher(None, nt, qt).ratio() for qt in q_tokens), default=0.0)
            for nt in n_tokens
        ]
        score = sum(per_token) / len(per_token)
        if score > best_score:
            best_score, best = score, n
    return best if best_score >= threshold else None


# Lookup-phrase filler stripped before guessing the entity for "did you mean".
_LOOKUP_STOPWORDS = {
    "do", "you", "yo", "know", "tell", "me", "about", "is", "the", "a", "an",
    "of", "on", "for", "info", "information", "details", "detail", "who",
    "what", "give", "show", "more", "please", "any", "there", "i", "my",
}


def _entity_guess(query: str) -> str:
    """The likely customer-name portion of a lookup query (filler removed)."""
    toks = re.findall(r"[a-z0-9]+", (query or "").lower())
    kept = [t for t in toks if t not in _LOOKUP_STOPWORDS]
    return " ".join(kept)


def _match_customer_candidates(query: str, names, low: float = 0.45, max_n: int = 3):
    """
    Ranked NEAR-MISS customer names for a 'did you mean' prompt — used only when
    `_match_customer_name` found no confident (>=0.82) match. Pure (no DB).
    Returns up to `max_n` names whose whole-string similarity to the entity guess
    is >= `low`, best first. Empty when nothing is close enough.
    """
    guess = _entity_guess(query)
    clean = [n for n in names if n]
    if not guess or not clean:
        return []
    scored = []
    for n in clean:
        r = difflib.SequenceMatcher(None, guess, n.lower()).ratio()
        if r >= low:
            scored.append((r, n))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [n for _, n in scored[:max_n]]


def _customer_candidates(query: str, user_id: int):
    """DB-backed near-miss candidates for this user (for 'did you mean' chips)."""
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
        return _match_customer_candidates(query, names)
    except Exception as e:
        logger.debug(f"[HANDLER] customer_candidates: {e}")
        return []


def _extract_customer_name(query: str, user_id: int):
    """Fetch this user's distinct customer names and resolve one from the query."""
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
        return _match_customer_name(query, names)
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
                # No customer resolved. If it's a general business ask that merely
                # used "tell me about ...", let the AI answer. Otherwise the user
                # named a customer we don't have — say so honestly instead of
                # falling through to the LLM, which fabricates an empty client card.
                if _is_general_about_query(user_query):
                    return None
                logger.info(f"[HANDLER] client_summary: no customer match for '{user_query}'")
                return CUSTOMER_NOT_FOUND
            return fn(user_id, {"customer": customer})

        if handler_key in ("overdue_list", "pending_list"):
            return fn(user_id, limit=_extract_limit(user_query))

        return fn(user_id)

    except Exception as e:
        logger.error(f"[HANDLER] '{handler_key}' raised an error: {e}", exc_info=True)
        return None
