"""
services/ai_router_decision.py
==============================
Route-decision layer split out of ai_router.py (MASTER_REVIEW §2.5).

Everything that decides WHERE a query goes — topic detection, intent-direct
promotion, LLM-router trust guards (B1/B2/B6), entity-first scoping, and
shadow routing — with no knowledge of execution or caching.

Patchability contract: `_extract_customer_name` and `_semantic_classify` are
resolved at call time through the `services.ai_router` façade so existing
monkeypatch targets (services.ai_router._extract_customer_name, etc.) keep
working exactly as before the split.
"""
import os
import re
import logging

from services.query_router import _WRITING_ACTIONS

logger = logging.getLogger("bizassist.ai_router")


def _facade_dep(name):
    """Late-bind a dependency through the ai_router façade (test-patchable)."""
    import services.ai_router as _facade
    return getattr(_facade, name)

# Topics that have a deterministic DB-backed intent handler. An AI_SIMPLE query
# whose detected topic is in this set is "promoted" to a 0-token DB answer.
_INTENT_DIRECT = {
    "overdue_list", "overdue_amount", "pending_list", "total_revenue",
    "revenue_summary", "top_debtors", "top_customers", "low_stock",
    "expiring_soon", "inventory_count", "invoice_count",
}


# ── Topic detector — maps any query/tool-call to a recommend() key ────
def _detect_topic(user_query: str, tool_calls_made: list = None) -> str:
    """
    Priority: tool calls made during this turn > keyword match on query.
    Covers all 13 intent topics used in recommendations.RECS.

    Embedding/semantic queries (query_semantic_index) fall through to
    keyword matching so they still get contextual chips.
    """
    # Tool-call → topic (checked first — most precise signal)
    TOOL_TOPIC = {
        "summarize_invoices":    "total_revenue",
        "rank_top_customers":    "top_customers",
        "view_business_metrics": "business_summary",
    }
    if tool_calls_made:
        for tc in tool_calls_made:
            name = tc.function.name if hasattr(tc, "function") else str(tc)
            if name in TOOL_TOPIC:
                return TOOL_TOPIC[name]
            if name == "list_invoices":
                args_str = (tc.function.arguments if hasattr(tc, "function") else "{}") or "{}"
                import json as _j
                try:
                    args = _j.loads(args_str)
                except Exception:
                    args = {}
                status = (args.get("status") or "").lower()
                if status == "overdue":   return "overdue_list"
                if status == "pending":   return "pending_list"
                return "total_revenue"
            if name == "check_inventory_stock":
                args_str = (tc.function.arguments if hasattr(tc, "function") else "{}") or "{}"
                import json as _j
                try:
                    args = _j.loads(args_str)
                except Exception:
                    args = {}
                if args.get("filter_expiry_days") is not None: return "expiring_soon"
                return "low_stock"
            if name == "list_payment_records":   return "overdue_amount"
            if name == "search_exact_keywords":  pass   # fall through to keyword
            if name == "query_semantic_index":   pass   # fall through to keyword

    # Keyword fallback — covers all domains end-to-end
    q = user_query.lower()

    # Overdue / debt (semantic variants: "who owes", "not paid", "outstanding")
    if any(k in q for k in ["overdue", "debt", "owes", "owe me", "outstanding", "bad debt",
                              "not paid", "hasn't paid", "havent paid", "due and unpaid",
                              "debtor", "receivable", "collect"]):
        return "overdue_list"

    # Pending invoices
    if any(k in q for k in ["pending", "unpaid invoice", "upcoming payment", "not yet paid",
                              "awaiting payment", "soon due"]):
        return "pending_list"

    # Top debtors (separate from generic overdue — ranked by amount)
    if any(k in q for k in ["top debtor", "biggest debtor", "who owes most", "highest overdue",
                              "worst payer", "most overdue"]):
        return "top_debtors"

    # Revenue / sales / income
    if any(k in q for k in ["revenue", "sales", "income", "earning", "turnover",
                              "monthly", "trend", "month wise", "per month", "over time",
                              "collection rate", "cash flow", "cashflow", "profit"]):
        return "total_revenue"

    # Top customers
    if any(k in q for k in ["top customer", "best customer", "biggest buyer", "most revenue",
                              "highest paying", "vip client", "top client", "loyal"]):
        return "top_customers"

    # General customer / client queries
    if any(k in q for k in ["customer", "client", "buyer", "account"]):
        return "top_customers"

    # Expiry
    if any(k in q for k in ["expir", "expire", "expiry", "shelf life", "use by",
                              "best before", "fresh", "spoil", "wastage", "near expiry"]):
        return "expiring_soon"

    # Low stock / reorder
    if any(k in q for k in ["low stock", "running out", "running low", "reorder", "shortage",
                              "out of stock", "stock level", "replenish", "restock", "almost out",
                              "nearly out", "critically low"]):
        return "low_stock"

    # Inventory / products general
    if any(k in q for k in ["inventory", "stock", "product", "item", "goods", "sku", "batch",
                              "warehouse", "shelf"]):
        return "inventory_count"

    # Payments / collections
    if any(k in q for k in ["payment", "paid", "due date", "invoice due", "settlement",
                              "remittance", "cheque", "upi", "transfer", "receipt"]):
        return "overdue_amount"

    # Invoices general
    if any(k in q for k in ["invoice", "bill", "receipt", "order", "transaction"]):
        return "total_revenue"

    # Upload / file analysis
    if any(k in q for k in ["upload", "file", "csv", "xlsx", "pdf", "imported", "analyze the"]):
        return "upload"

    # Business overview / planning
    if any(k in q for k in ["summary", "overview", "health", "snapshot", "dashboard",
                              "performance", "report", "kpi", "metrics", "priorities",
                              "today", "focus", "attention", "analyze", "analysis",
                              "strategy", "plan", "growth", "improve"]):
        return "business_summary"

    return "business_summary"   # safe default



# Global-aggregate handlers — if the query NAMES a single known customer, the
# answer should be scoped to that customer's summary, not the all-customers view
# ("how much does Nilgiris Fresh owe me" → Nilgiris's overdue, not the global list).
_AGGREGATE_HANDLERS = {
    "overdue_list", "overdue_amount", "total_revenue", "top_debtors",
    "pending_list", "top_customers", "invoice_count",
}

# ── LLM-router decision-consumption guards (B1/B2/B6) ───────────────────────
# Below this confidence the LLM guessed → keep the legacy decision (B1).
_LLM_CONF_FLOOR = float(os.getenv("LLM_ROUTER_CONF_FLOOR", "0.6"))

# Handlers that are already about ONE customer / invoice — a named-customer
# entity does NOT need rerouting for these (B2).
_CUSTOMER_SCOPED = {"client_summary", "customer_invoices", "invoice_detail"}

# Exact dashboard templates legacy resolves deterministically — skip the LLM
# router's 1-2s call when one of these already matched (B6).
_LLM_FASTPATH_HANDLERS = {"overdue_range_detail", "revenue_month_detail"}


def _resolve_llm_decision(decision, legacy_route: str, legacy_handler):
    """
    Decide whether/how to honor an LLM RouteDecision (pure → unit-testable).

    Implements the two trust guards from the live-trace review:
      B1 — below the confidence floor, the model guessed → fall back to the
           legacy decision (which already handles bare-name lookups, etc.).
      B2 — a named customer with a non-customer-scoped answer (or a 'chat')
           means the user wants THAT customer's view, not a global table →
           reroute to client_summary; never drop to chat when a customer is named.

    Returns (route, handler_key, entities, accepted).
    """
    conf = getattr(decision, "confidence", 0.0)
    if conf < _LLM_CONF_FLOOR:
        return legacy_route, legacy_handler, {}, False
    tier, handler = decision.tier, decision.handler_key
    ents = getattr(decision, "entities", {}) or {}
    cust = ents.get("customer")
    if cust and getattr(decision, "mode", None) in ("answer", "chat") \
            and handler not in _CUSTOMER_SCOPED:
        tier, handler = "DIRECT", "client_summary"
    return tier, handler, ents, True

# Genuinely multi-entity phrasings ("compare X and Y") — don't scope to one
# customer. (List/ranking words like "all"/"top" are handled by the name lookup
# simply returning None, so they don't need to be here.)
_MULTI_SIGNAL = re.compile(
    r"\b(compare|comparison|versus|vs|each|both|every|everyone|everybody)\b",
    re.I,
)

# A specific invoice ID → its detail row. Matches bare "INV-0007" (the real data
# format) and prefixed "SUP-INV-0138".
_INVOICE_ID_RE = re.compile(r"\b(?:[A-Za-z]{2,6}-)?INV-\d+\b", re.I)

# The user wants a customer's full invoice ledger, not just the summary.
_INVOICE_LIST_SIGNAL = re.compile(
    r"\b(invoices?|bills?|transactions?|ledger|statement|orders?|table)\b", re.I,
)


def _maybe_entity_first(route: str, handler_key, user_query: str, user_id: int):
    """
    Entity scoping: route by the specific entity a query names, even if a keyword
    tripped a global topic.
      • Specific invoice ID ("SUP-INV-0138 details") → invoice_detail.
      • A named customer + "invoices/table/list" → customer_invoices (full ledger).
      • A named customer otherwise ("how much does Nilgiris Fresh owe me",
        "namdhari fresh") → client_summary.
    Skipped for writing tasks (must draft) and genuine multi-entity comparisons.
    The fuzzy matcher's 0.82 threshold rejects non-name text. Returns (route, handler_key).
    """
    q = user_query or ""
    # Writing tasks must stay on the drafting path ("draft a reminder about X").
    if _WRITING_ACTIONS.search(q):
        return route, handler_key
    # A specific invoice ID → its real DB row (never generated).
    if _INVOICE_ID_RE.search(q):
        logger.info(f"[ROUTER] entity → invoice_detail q='{user_query}'")
        return "DIRECT", "invoice_detail"
    # A plain client_summary with no 'invoices/table' ask is already correct.
    if handler_key == "client_summary" and not _INVOICE_LIST_SIGNAL.search(q):
        return route, handler_key
    eligible = (route == "AI_SIMPLE") or (route == "DIRECT" and handler_key in _AGGREGATE_HANDLERS) \
        or (handler_key == "client_summary")
    if not eligible or _MULTI_SIGNAL.search(q):
        return route, handler_key
    named = _facade_dep("_extract_customer_name")(q, user_id)
    if named:
        if _INVOICE_LIST_SIGNAL.search(q):
            logger.info(f"[ROUTER] entity → customer_invoices (customer='{named}') q='{user_query}'")
            return "DIRECT", "customer_invoices"
        logger.info(f"[ROUTER] entity-first → client_summary (customer='{named}') q='{user_query}'")
        return "DIRECT", "client_summary"
    return route, handler_key


def _maybe_shadow_route(user_query: str, route: str, handler_key, topic: str) -> None:
    """
    Phase 1 Step 2 — shadow routing. When INTENT_ROUTER=shadow (or on), run the
    semantic router alongside the live regex router and log AGREE/DISAGREE. This
    changes nothing about routing; it just gathers real-traffic accuracy data so
    we can trust the semantic router before cutover.
    """
    mode = os.getenv("INTENT_ROUTER", "off").lower()
    if mode not in ("shadow", "on"):
        return
    try:
        s_tier, s_intent, s_conf = _facade_dep("_semantic_classify")(user_query)
    except Exception as e:
        logger.warning(f"[ROUTER][shadow] semantic classify failed: {e}")
        return
    # The regex system's effective "intent" is the detected topic (used for cache
    # + intent-first). Compare on intent when the semantic router named one, else
    # on tier.
    match = (s_intent == topic) if s_intent is not None else (s_tier == route)
    verdict = "AGREE" if match else "DISAGREE"
    logger.info(
        f"[ROUTER][shadow] {verdict} | regex=({route}, handler={handler_key}, topic={topic}) "
        f"semantic=({s_tier}, {s_intent}, {s_conf:.2f}) | q='{user_query}'"
    )


