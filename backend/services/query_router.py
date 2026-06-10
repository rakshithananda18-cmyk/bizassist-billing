"""
query_router.py
===============
Layer 1 of the hybrid engine.

Classifies every incoming question into one of three tiers:

  DIRECT      -- DB can answer fully, no LLM needed.
  AI_SIMPLE   -- Needs LLM but query is narrow/factual.
  AI_COMPLEX  -- Multi-step reasoning, strategy, analysis, planning.
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger("bizassist.query_router")


# ── Patterns -> direct DB handler ────────────────────────────────────
DIRECT_PATTERNS = [

    (re.compile(r"overdue payments in range (\d+-\d+ days|90\+ days)", re.I),
     "overdue_range_detail"),

    (re.compile(r"revenue in\s+([a-zA-Z]+)\s+(\d{2,4})", re.I),
     "revenue_month_detail"),

    (re.compile(r"how many invoices|invoice count|total invoices", re.I),
     "invoice_count"),

    (re.compile(r"total revenue|how much revenue|revenue total|total sales", re.I),
     "total_revenue"),

    # Overdue list -- broad natural language: "overdues", "top 15 overdue", "overdue people"
    (re.compile(
        r"overdue[s]?\s+(invoices?|list|people|customers?|accounts?)"
        r"|(list|give\s+me|show\s+me?)\s+(top\s*\d+\s+)?overdue[s]?"
        r"|show\s+top\s*\d+\s+overdue[s]?"
        r"|overdue (invoices?|total|list)"
        r"|who (is |are )overdue|list overdue"
        r"|(top\s*\d+\s+)?overdue[s]?\s+(people|customers?|invoices?|list)",
        re.I),
     "overdue_list"),

    (re.compile(r"overdue amount|how much (is )?overdue|total overdue", re.I),
     "overdue_amount"),

    (re.compile(r"pending (invoices?|payments?|list)|how many (are )?pending|show (me )?pending", re.I),
     "pending_list"),

    (re.compile(r"top\s*(?:\d+\s+)?debtors?|who owes (me )?the most|biggest debtor|largest debtor|most overdue customer", re.I),
     "top_debtors"),

    (re.compile(r"top\s*(?:\d+\s+)?(?:customers?|clients?)|highest (paying|revenue) customer", re.I),
     "top_customers"),

    (re.compile(r"how many (products?|items?|units?)|inventory count|stock count", re.I),
     "inventory_count"),

    (re.compile(r"low stock|out of stock|stock (below|under|less than)|reorder", re.I),
     "low_stock"),

    (re.compile(r"expir(ing|ed|y)", re.I),
     "expiring_soon"),

    (re.compile(r"pending payment|unpaid|not paid", re.I),
     "pending_list"),

    (re.compile(r"(business |quick )?summary|dashboard|overview|snapshot", re.I),
     "business_summary"),

    # Customer / client lookup
    (re.compile(
        r"\b(tell me about|do you know|info (on|about)|details? (of|for|on)|"
        r"what(\'?s| is) (the status|happening with)|client (profile|info|summary)|"
        r"customer (profile|info|summary)|account (details?|summary|info))\b",
        re.I),
     "client_summary"),
]


# ── "show all overdue/pending" override -- must beat COMPLEX patterns ─
_DIRECT_OVERRIDE = re.compile(
    r"\b(show all|give me all|list all|show me all)\s+(overdue[s]?|pending)\b",
    re.I,
)


# Queries that contain action/writing verbs should NOT go DIRECT even if
# they mention overdue/pending keywords (e.g. "draft a reminder for overdue customers").
_WRITING_ACTIONS = re.compile(
    r"\b(draft|write|compose|prepare|create|generate|make|send|format)\b"
    r".{0,60}\b(message|email|reminder|letter|template|note|text)\b",
    re.I,
)


# ── Keywords that force AI_COMPLEX (strategic / multi-step) ─────────
COMPLEX_PATTERNS = [
    r"\banaly[sz][a-zA-Z]*\b",
    r"\bforecast\b", r"\bpredict\b",
    r"\bq[1-4]\b", r"\bquarter\b",
    r"\byear(ly)?\b", r"\bannual\b",
    r"\bgrowth\s+plan\b",
    r"\bstrateg(y|ies)\b",
    r"\bcompare\b", r"\bcomparison\b",
    r"\breport\b",
    r"\bplan\b", r"\bplanning\b",
    r"\boptimiz(e|ation)\b",
    r"\bimprove\b", r"\bimprovements?\b",
    r"\bprofitabilit(y|ies)\b",
    r"\bgrow\b", r"\bscale\b",
    r"\brecommend\b", r"\badvice\b",
    r"\broot causes?\b", r"\bwhy is\b", r"\bdiagnos[ei]\b",
    r"\bwhat should i\b", r"\bhow (can|do|should) (i|we)\b",
    r"\baction plan\b", r"\broad ?map\b",
    r"\binsight\b", r"\binsights\b",
    r"\bexpand\b", r"\belaborate\b",
    r"\bmore detail\b", r"\bin detail\b",
    r"\blist all\b",
    r"\bbreak(down| it down)\b",
]


# ── Conversational messages ───────────────────────────────────────────
CONVERSATIONAL_PATTERNS = [
    re.compile(r"^(hi+|hello|hey|yo|sup|hiya|howdy)\b", re.I),
    re.compile(r"^(ok|okay|ok cool|alright|got it|got that|okay got it|okay great|okay sure|understood|noted|sure|yep|yup|yeah|yes|nope|no)\s*[.!?]*$", re.I),
    re.compile(r"^(thanks?|thank you|thx|ty|cheers|great|nice|cool|awesome|good|perfect|sounds good|makes sense|that helps|very helpful|got it thanks)\s*[.!?]*$", re.I),
    re.compile(r"^(bye|goodbye|see ya|later|cya)\s*[.!]*$", re.I),
    re.compile(r"^[.!?]{1,3}$", re.I),
]


def is_conversational(query: str) -> bool:
    q = query.strip()
    if len(q) > 40:
        return False
    for pattern in CONVERSATIONAL_PATTERNS:
        if pattern.match(q):
            return True
    return False


# ── Follow-up indicators ─────────────────────────────────────────────
FOLLOWUP_PATTERNS = [
    re.compile(r"\b(clarify|what do you mean|explain that|tell me more about that)\b", re.I),
    re.compile(r"\b(from that|based on that|about that|regarding that|from the above|from your (answer|response))\b", re.I),
    re.compile(r"\b(the above|the previous|that analysis|that report|that plan|that growth plan|that recommendation)\b", re.I),
    re.compile(r"^(what|which|how|why)\s+(do you mean|does that mean|should i do with that)", re.I),
    re.compile(r"^(and|but|so)\s+", re.I),
]


def is_followup(query: str, has_history: bool) -> bool:
    if not has_history:
        return False
    for pattern in FOLLOWUP_PATTERNS:
        if pattern.search(query.strip()):
            return True
    return False


def _direct_override_handler(q: str) -> str:
    """Return the correct handler key for a show-all override query."""
    if re.search(r"\boverdue[s]?\b", q, re.I):
        return "overdue_list"
    if re.search(r"\bpending\b", q, re.I):
        return "pending_list"
    return "overdue_list"


def classify(user_query: str, has_history: bool = False) -> Tuple[str, Optional[str]]:
    """
    Returns one of:
        ("DIRECT",        handler_key)  -- DB only, 0 tokens
        ("AI_SIMPLE",     None)         -- small model, low cost
        ("AI_COMPLEX",    None)         -- large model, use sparingly
        ("CONVERSATIONAL",None)         -- no data needed
    """
    q = user_query.strip()

    # Step 0a: Conversational short-circuit
    if is_conversational(q):
        logger.info(f"[ROUTER] CONVERSATIONAL: '{q}'")
        return ("CONVERSATIONAL", None)

    # Step 0b: "show all overdue/pending" -- must beat COMPLEX patterns
    if _DIRECT_OVERRIDE.search(q):
        handler = _direct_override_handler(q)
        logger.info(f"[ROUTER] DIRECT (show-all override) handler={handler}: '{q}'")
        return ("DIRECT", handler)

    # Step 0c: Follow-up detection
    if is_followup(q, has_history):
        logger.info(f"[ROUTER] AI_SIMPLE (follow-up): '{q}'")
        return ("AI_SIMPLE", None)

    # Step 1: COMPLEX keyword check
    for pattern in COMPLEX_PATTERNS:
        if re.search(pattern, q, re.I):
            logger.info(f"[ROUTER] AI_COMPLEX pattern='{pattern}': '{q}'")
            return ("AI_COMPLEX", None)

    # Step 2: Dashboard quick-action templates (contain digits, handled first)
    for pattern, handler_key in DIRECT_PATTERNS:
        if handler_key in ("overdue_range_detail", "revenue_month_detail") and pattern.search(q):
            logger.info(f"[ROUTER] DIRECT ({handler_key}) template match")
            return ("DIRECT", handler_key)

    # Step 3: Digit queries -- route to AI_SIMPLE unless it's a known list query
    if any(char.isdigit() for char in q):
        is_known_list = (
            ("30" in q and re.search(r"expir", q, re.I)) or
            ("5"  in q and re.search(r"top",   q, re.I)) or
            ("10" in q and re.search(r"low|stock|reorder", q, re.I)) or
            bool(re.search(r"\boverdue[s]?\b", q, re.I)) or   # top-N overdue
            bool(re.search(r"\bpending\b",     q, re.I))       # top-N pending
        )
        if not is_known_list:
            logger.info(f"[ROUTER] AI_SIMPLE (digit query): '{q}'")
            return ("AI_SIMPLE", None)

    # Step 3b: Writing/action tasks -- never route to DIRECT even if keywords match
    if _WRITING_ACTIONS.search(q):
        logger.info(f"[ROUTER] AI_SIMPLE (writing task): '{q}'")
        return ("AI_SIMPLE", None)

    # Step 4: Standard DIRECT patterns
    for pattern, handler_key in DIRECT_PATTERNS:
        if pattern.search(q):
            logger.info(f"[ROUTER] DIRECT ({handler_key}): '{q}'")
            return ("DIRECT", handler_key)

    # Step 5: Default fallback
    logger.info(f"[ROUTER] AI_SIMPLE (fallback): '{q}'")
    return ("AI_SIMPLE", None)
