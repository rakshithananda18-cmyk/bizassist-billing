"""
query_router.py
===============
Layer 1 of the hybrid engine.

Classifies every incoming question into one of:

  DIRECT   — DB can answer fully, no LLM needed
             e.g. "how many invoices", "total revenue"
             Returns answer immediately. Zero Groq tokens used.

  AI       — Needs LLM reasoning on top of DB data
             e.g. "which customer should I follow up with first?"
             Context is fetched from cache, then sent to Groq.

This keeps token usage minimal and response time fast
for the most common business queries.
"""

import re
from typing import Optional, Tuple


# ── Patterns that map directly to a DB query function ──────────────
# Each entry: (compiled regex, handler_key)
# Handler keys are resolved in direct_query_handler.py

DIRECT_PATTERNS = [

    # Invoice counts
    (re.compile(r"how many invoices|invoice count|total invoices", re.I),
     "invoice_count"),

    # Revenue
    (re.compile(r"total revenue|how much revenue|revenue total|total sales", re.I),
     "total_revenue"),

    # Overdue
    (re.compile(r"overdue (invoices?|amount|total|list)|who (is |are )overdue|list overdue", re.I),
     "overdue_list"),

    (re.compile(r"overdue amount|how much (is )?overdue|total overdue", re.I),
     "overdue_amount"),

    # Pending
    (re.compile(r"pending (invoices?|payments?|list)|how many (are )?pending", re.I),
     "pending_list"),

    # Top customers
    (re.compile(r"top (customers?|clients?)|who owes (me )?the most|highest (paying|revenue) customer", re.I),
     "top_customers"),

    # Inventory / stock
    (re.compile(r"how many (products?|items?|medicines?)|inventory count|stock count", re.I),
     "inventory_count"),

    (re.compile(r"low stock|out of stock|stock (below|under|less than)|reorder", re.I),
     "low_stock"),

    # Expiry
    (re.compile(r"expir(ing|ed|y)|medicines? expir", re.I),
     "expiring_soon"),

    # Payments
    (re.compile(r"pending payment|unpaid|not paid", re.I),
     "pending_list"),

    # Summary / dashboard
    (re.compile(r"(business |quick )?summary|dashboard|overview|snapshot", re.I),
     "business_summary"),
]


def classify(user_query: str) -> Tuple[str, Optional[str]]:
    """
    Returns:
        ("DIRECT", handler_key)  — answer from DB, skip LLM
        ("AI",     None)         — needs LLM
    """
    q = user_query.strip()

    for pattern, handler_key in DIRECT_PATTERNS:
        if pattern.search(q):
            return ("DIRECT", handler_key)

    return ("AI", None)