"""
query_router.py
===============
Layer 1 of the hybrid engine.

Classifies every incoming question into one of three tiers:

  DIRECT      — DB can answer fully, no LLM needed.
                e.g. "how many invoices", "total revenue"
                0 tokens, ~5ms.

  AI_SIMPLE   — Needs LLM but query is narrow/factual.
                e.g. "which customer owes the most?", "am I low on stock?"
                Uses small fast model (llama-3.1-8b-instant).

  AI_COMPLEX  — Multi-step reasoning, strategy, analysis, planning.
                e.g. "analyse my Q1 business and give a growth plan"
                Uses larger model (llama-3.3-70b-versatile).

Token cost ladder: DIRECT (0) < AI_SIMPLE (low) < AI_COMPLEX (high).
Always push queries as far left as possible.
"""

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger("bizassist.query_router")


# ── Patterns → direct DB handler ────────────────────────────────────
DIRECT_PATTERNS = [

    (re.compile(r"overdue payments in range (\d+-\d+ days|90\+ days)", re.I),
     "overdue_range_detail"),

    (re.compile(r"revenue in\s+([a-zA-Z]+)\s+(\d{2,4})", re.I),
     "revenue_month_detail"),

    (re.compile(r"how many invoices|invoice count|total invoices", re.I),
     "invoice_count"),

    (re.compile(r"total revenue|how much revenue|revenue total|total sales", re.I),
     "total_revenue"),

    (re.compile(r"overdue (invoices?|amount|total|list)|who (is |are )overdue|list overdue", re.I),
     "overdue_list"),

    (re.compile(r"overdue amount|how much (is )?overdue|total overdue", re.I),
     "overdue_amount"),

    (re.compile(r"pending (invoices?|payments?|list)|how many (are )?pending", re.I),
     "pending_list"),

    (re.compile(r"top\s*(?:\d+\s+)?(?:customers?|clients?)|who owes (me )?the most|highest (paying|revenue) customer", re.I),
     "top_customers"),

    (re.compile(r"how many (products?|items?|medicines?)|inventory count|stock count", re.I),
     "inventory_count"),

    (re.compile(r"low stock|out of stock|stock (below|under|less than)|reorder", re.I),
     "low_stock"),

    (re.compile(r"expir(ing|ed|y)|medicines? expir", re.I),
     "expiring_soon"),

    (re.compile(r"pending payment|unpaid|not paid", re.I),
     "pending_list"),

    (re.compile(r"(business |quick )?summary|dashboard|overview|snapshot", re.I),
     "business_summary"),
]


# ── Keywords that force AI_COMPLEX (strategic / multi-step) ─────────
COMPLEX_PATTERNS = [
    r"\banaly[sz][a-zA-Z]*\b",             # analyze, analysis, analyse, analyzing, etc.
    r"\bforecast\b", r"\bpredict\b",
    r"\bq[1-4]\b", r"\bquarter\b",         # Q1, Q2, quarterly
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
    r"\bwhat should i\b", r"\bhow (can|do|should) (i|we)\b",
    r"\baction plan\b", r"\broad ?map\b",
    r"\binsight\b", r"\binsights\b",
    # Data expansion — needs fresh DB fetch, not history
    r"\bexpand\b", r"\belaborate\b",
    r"\bmore detail\b", r"\bin detail\b",
    r"\blist all\b", r"\bshow all\b", r"\bgive me all\b",
    r"\bbreak(down| it down)\b",
]

# ── Keywords that keep it AI_SIMPLE (factual but needs LLM) ─────────
# Everything that isn't DIRECT and isn't COMPLEX defaults to AI_SIMPLE.
# No explicit list needed — it's the fallback.


# ── Follow-up indicators ─────────────────────────────────────────────
# If a query matches these AND the session has prior history,
# it's a follow-up to a previous answer — route to AI_SIMPLE
# instead of re-running the expensive agent graph.
FOLLOWUP_PATTERNS = [
    # Conversational clarification — safe to use history, no new data needed
    re.compile(r"\b(clarify|what do you mean|explain that|tell me more about that)\b", re.I),
    re.compile(r"\b(from that|based on that|about that|regarding that|from the above|from your (answer|response))\b", re.I),
    re.compile(r"\b(the above|the previous|that analysis|that report|that plan|that growth plan|that recommendation)\b", re.I),
    re.compile(r"^(what|which|how|why)\s+(do you mean|does that mean|should i do with that)", re.I),
    re.compile(r"^(and|but|so)\s+", re.I),

    # NOTE: "expand", "elaborate", "more detail", "list all" are intentionally excluded.
    # These require fresh DB data — let them route to AI_COMPLEX to avoid hallucination.
]


def is_followup(query: str, has_history: bool) -> bool:
    """Returns True if the query looks like a follow-up to a previous response."""
    if not has_history:
        return False
    for pattern in FOLLOWUP_PATTERNS:
        if pattern.search(query.strip()):
            return True
    return False


def classify(user_query: str, has_history: bool = False) -> Tuple[str, Optional[str]]:
    """
    Returns one of:
        ("DIRECT",     handler_key)  — DB only, 0 tokens
        ("AI_SIMPLE",  None)         — small model, low cost
        ("AI_COMPLEX", None)         — large model, use sparingly
    """
    q = user_query.strip()

    # ── Step 0: Follow-up detection — runs before everything else ────
    # If the query is a follow-up to a previous response, downgrade to
    # AI_SIMPLE so it uses chat history instead of re-running agents.
    if is_followup(q, has_history):
        logger.info(f"[Router] AI_SIMPLE (follow-up detected): '{q}'")
        return ("AI_SIMPLE", None)

    # ── Step 1: Check for COMPLEX keywords first ─────────────────────
    for pattern in COMPLEX_PATTERNS:
        if re.search(pattern, q, re.I):
            logger.info(f"[Router] AI_COMPLEX — matched pattern '{pattern}' in: '{q}'")
            return ("AI_COMPLEX", None)

    # ── Step 2: Dashboard quick-action templates (contain digits) ────
    for pattern, handler_key in DIRECT_PATTERNS:
        if handler_key in ("overdue_range_detail", "revenue_month_detail") and pattern.search(q):
            logger.info(f"[Router] DIRECT ({handler_key}) — template match")
            return ("DIRECT", handler_key)

    # ── Step 3: Custom digit queries → AI_SIMPLE (dynamic values) ───
    if any(char.isdigit() for char in q):
        is_default = (
            ("30" in q and re.search(r"expir", q, re.I)) or
            ("5"  in q and re.search(r"top",   q, re.I)) or
            ("10" in q and re.search(r"low|stock|reorder", q, re.I))
        )
        if not is_default:
            logger.info(f"[Router] AI_SIMPLE — custom digit query: '{q}'")
            return ("AI_SIMPLE", None)

    # ── Step 4: Standard DIRECT patterns ────────────────────────────
    for pattern, handler_key in DIRECT_PATTERNS:
        if pattern.search(q):
            logger.info(f"[Router] DIRECT ({handler_key})")
            return ("DIRECT", handler_key)

    # ── Step 5: Default → AI_SIMPLE ─────────────────────────────────
    logger.info(f"[Router] AI_SIMPLE — default fallback: '{q}'")
    return ("AI_SIMPLE", None)
