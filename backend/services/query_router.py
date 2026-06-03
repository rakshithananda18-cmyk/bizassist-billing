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

    # Overdue range click (specific template containing digits)
    (re.compile(r"overdue payments in range (\d+-\d+ days|90\+ days)", re.I),
     "overdue_range_detail"),

    # Revenue month click (specific template containing digits)
    (re.compile(r"revenue in\s+([a-zA-Z]+)\s+(\d{2,4})", re.I),
     "revenue_month_detail"),

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

    # Top customers (allowing optional count parameter like "top 5")
    (re.compile(r"top\s*(?:\d+\s+)?(?:customers?|clients?)|who owes (me )?the most|highest (paying|revenue) customer", re.I),
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

    # 0. Bypass to AI if query contains strategic, planning, or reasoning keywords
    reasoning_keywords = [
        r"\bstrategy\b", r"\bstrategies\b",
        r"\bplan\b", r"\bplanning\b",
        r"\bsystem\b", r"\bmanagement\b",
        r"\bhow\s+(?!many\b|much\b)", r"\bimprove\b", r"\bgrow\b",
        r"\boptimize\b", r"\boptimization\b",
        r"\bminimize\b", r"\bwaste\b",
        r"\bdevelop\b", r"\bdevelopment\b",
        r"\bpromotional\b", r"\bpromotion\b", r"\bpromotions\b",
        r"\bmarketing\b", r"\bcampaign\b", r"\bcampaigns\b",
        r"\badvice\b", r"\brecommendation\b", r"\brecommendations\b",
        r"\bsuggestion\b", r"\bsuggestions\b", r"\bidea\b", r"\bideas\b",
        r"\bimplement\b", r"\bimplementation\b", r"\bdesign\b"
    ]
    for kw_pattern in reasoning_keywords:
        if re.search(kw_pattern, q, re.I):
            return ("AI", None)

    # 1. First, check if it matches the specific dashboard quick actions that contain digits
    for pattern, handler_key in DIRECT_PATTERNS:
        if handler_key in ("overdue_range_detail", "revenue_month_detail") and pattern.search(q):
            return ("DIRECT", handler_key)

    # 2. Next, check for digits to see if this is a custom dynamic query (e.g., "15 days", "top 3")
    if any(char.isdigit() for char in q):
        # Allow default template numbers to pass through to the direct path
        # Example: "expiring in 30 days" matches default expiring_soon (30 days)
        # "top 5 customers" matches default top_customers (5)
        # "low stock" with 10 matches default low_stock (10)
        is_default = False
        if "30" in q and re.search(r"expir", q, re.I):
            is_default = True
        elif "5" in q and re.search(r"top", q, re.I):
            is_default = True
        elif "10" in q and re.search(r"low|stock|reorder", q, re.I):
            is_default = True
            
        if not is_default:
            return ("AI", None)

    # 3. Standard routing for general queries without digits or matching default numbers
    for pattern, handler_key in DIRECT_PATTERNS:
        if pattern.search(q):
            return ("DIRECT", handler_key)

    return ("AI", None)