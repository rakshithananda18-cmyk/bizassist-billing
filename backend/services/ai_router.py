"""
services/ai_router.py
=====================
Core business logic for the /ask endpoint.

Handles the full 4-tier routing pipeline:
  CONVERSATIONAL → short reply, no data
  DIRECT         → DB handler, 0 tokens
  CACHE          → cached AI response
  AI_SIMPLE      → Groq tool-calling, small model
  AI_COMPLEX     → LangGraph multi-agent, large model

Called by routes/ask.py -- keeps the FastAPI route thin.

ARCHITECTURE (Phase 0 unification)
----------------------------------
There is ONE pipeline: `process_query()`, a generator that yields semantic
events. The two public entry points are thin adapters over it:

  handle()         → drains the generator, returns a single JSON envelope (/ask)
  handle_stream()  → forwards the events as SSE strings           (/ask/stream)

`process_query(..., stream=False)` produces instant/non-streamed answers;
`stream=True` streams tokens. Everything else — session resolution, history,
classification, rate limiting, cache, DIRECT, intent-first, token accounting,
logging, response assembly — is written exactly once. No more drift between the
two paths.
"""
import json
import logging
import os
import re
import hashlib
import uuid
from datetime import date
from typing import Optional

from groq import Groq
from sqlalchemy import func

from services.query_router import classify, _WRITING_ACTIONS
from services.direct_query_handler import (
    handle as direct_handle, _extract_customer_name, _customer_candidates, CUSTOMER_NOT_FOUND,
)
from services.recommendations import recommend, get_business_snapshot, detect_anomalies
from services.feedback_service import get_override
from services.context_cache import get_focused_context, get_cached_query_response, set_cached_query_response
from services.tools import execute_tool, schemas as tool_schemas
from services.embeddings import search_chat_memories, save_chat_memory
from services.agent_graph import run_agent_graph, run_agent_graph_stream
from services.rate_limiter import check_rate_limit
from services.errors import AskError, ask_error
from services.dates import parse_date
from services.intent_router import classify as _semantic_classify
from database.db import SessionLocal
from database.models import Invoice, ChatMessage

logger = logging.getLogger("bizassist.ai_router")

MODEL_SIMPLE  = os.getenv("GROQ_MODEL_SIMPLE",  "llama-3.1-8b-instant")
MODEL_COMPLEX = os.getenv("GROQ_MODEL_COMPLEX", "llama-3.3-70b-versatile")

# Max characters of a single tool result fed back to the model. A "draft a
# reminder" tool can return the entire overdue table (hundreds of rows); without
# a cap the follow-up call blows past the model's per-minute token limit (Groq
# free tier = 6000 TPM). ~4000 chars ≈ ~1000 tokens — plenty for a useful answer.
_MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "4000"))

# Topics that have a deterministic DB-backed intent handler. An AI_SIMPLE query
# whose detected topic is in this set is "promoted" to a 0-token DB answer.
_INTENT_DIRECT = {
    "overdue_list", "overdue_amount", "pending_list", "total_revenue",
    "revenue_summary", "top_debtors", "top_customers", "low_stock",
    "expiring_soon", "inventory_count", "invoice_count",
}


def _build_chart_data(user_query: str, user_id: int) -> Optional[dict]:
    """
    Detects chart/graph intent and returns a Chart.js-compatible data payload.
    Returns None if no chart is needed.
    """
    import re as _re
    from collections import defaultdict
    q = user_query.lower()
    is_chart = bool(_re.search(r"chart|graph|visuali[sz]e|plot|bar chart|pie chart|line chart|show.*graph|trend", q))
    if not is_chart:
        return None

    db2 = SessionLocal()
    try:
        # Monthly revenue trend (line chart) — checked FIRST before generic "revenue" match
        if any(k in q for k in ["monthly", "month", "trend", "month wise", "per month", "over time"]):
            rows = (
                db2.query(Invoice.invoice_date, func.sum(Invoice.amount).label("total"))
                .filter(Invoice.business_id == user_id, Invoice.invoice_date.isnot(None))
                .group_by(Invoice.invoice_date)
                .all()
            )
            if rows:
                # Aggregate by YYYY-MM
                monthly = defaultdict(float)
                for r in rows:
                    parsed = parse_date(r.invoice_date)
                    if parsed is not None:
                        monthly[parsed.strftime("%Y-%m")] += float(r.total or 0)
                if monthly:
                    sorted_keys = sorted(monthly.keys())
                    from datetime import datetime as _dt
                    labels = [_dt.strptime(k, "%Y-%m").strftime("%b %Y") for k in sorted_keys]
                    data   = [round(monthly[k], 2) for k in sorted_keys]
                    return {
                        "type":  "line",
                        "title": "Monthly Revenue Trend",
                        "labels": labels,
                        "datasets": [{
                            "label":           "Revenue (₹)",
                            "data":            data,
                            "borderColor":     "#6366f1",
                            "backgroundColor": "rgba(99,102,241,0.15)",
                            "tension":         0.4,
                            "fill":            True,
                            "pointRadius":     4,
                            "pointBackgroundColor": "#6366f1"
                        }]
                    }

        # Revenue by status (pie/doughnut) — for revenue/invoice/payment queries
        if any(k in q for k in ["revenue", "invoice", "payment", "overdue", "pending", "status"]):
            rows = (
                db2.query(Invoice.status, func.sum(Invoice.amount).label("total"))
                .filter(Invoice.business_id == user_id)
                .group_by(Invoice.status)
                .all()
            )
            if rows:
                color_map = {"Paid": "#22c55e", "Pending": "#f59e0b", "Overdue": "#ef4444", "Disputed": "#8b5cf6"}
                labels = [r.status for r in rows]
                data   = [round(float(r.total or 0), 2) for r in rows]
                return {
                    "type": "doughnut",
                    "title": "Revenue by Status",
                    "labels": labels,
                    "datasets": [{
                        "label": "Amount",
                        "data": data,
                        "backgroundColor": [color_map.get(l, "#94a3b8") for l in labels]
                    }]
                }

        # Top customers by revenue (bar) — for customer/client/top queries
        if any(k in q for k in ["customer", "client", "top", "debtor"]):
            rows = (
                db2.query(Invoice.customer, func.sum(Invoice.amount).label("total"))
                .filter(Invoice.business_id == user_id)
                .group_by(Invoice.customer)
                .order_by(func.sum(Invoice.amount).desc())
                .limit(7).all()
            )
            if rows:
                return {
                    "type": "bar",
                    "title": "Top Customers by Revenue",
                    "labels": [r.customer for r in rows],
                    "datasets": [{
                        "label": "Revenue (₹)",
                        "data": [round(float(r.total or 0), 2) for r in rows],
                        "backgroundColor": "#6366f1",
                        "borderRadius": 6
                    }]
                }

        # Default: revenue breakdown bar chart
        rows = (
            db2.query(Invoice.status, func.sum(Invoice.amount).label("total"))
            .filter(Invoice.business_id == user_id)
            .group_by(Invoice.status)
            .all()
        )
        if rows:
            color_map = {"Paid": "#22c55e", "Pending": "#f59e0b", "Overdue": "#ef4444", "Disputed": "#8b5cf6"}
            labels = [r.status for r in rows]
            data   = [round(float(r.total or 0), 2) for r in rows]
            return {
                "type": "bar",
                "title": "Invoice Status Breakdown",
                "labels": labels,
                "datasets": [{
                    "label": "Amount (₹)",
                    "data": data,
                    "backgroundColor": [color_map.get(l, "#94a3b8") for l in labels],
                    "borderRadius": 6
                }]
            }
        return None
    except Exception as e:
        logger.warning(f"[CHART] Failed to build chart data: {e}")
        return None
    finally:
        db2.close()


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


# ─────────────────────────────────────────────────────────────────────────────
# SHARED HELPERS  (used by the single pipeline)
# ─────────────────────────────────────────────────────────────────────────────

def _safe_int(v) -> int:
    """Coerce a token count to int. Mock/None usage objects collapse to 0."""
    return int(v) if isinstance(v, (int, float)) else 0


def _cache_salt(user_id: int, route: str, user_query: str, topic: str,
                handler_key: str = None, *, is_writing: bool = False, day: str = None) -> str:
    """
    Build the query-cache key. The DISCRIMINATOR must match the *resolved intent*
    so two different intents never share a cache entry — otherwise a coarse
    `_detect_topic` collapses distinct questions onto one key (e.g. "how many
    invoices" and "total revenue" both detect topic 'total_revenue', which made
    "total revenue" return the cached invoice answer).

      - AI_COMPLEX / writing task → exact query (each is unique; a "draft a
        reminder" must not be served a cached data list)
      - DIRECT                    → the precise `handler_key`
      - else (AI_SIMPLE / intent) → the detected topic, so semantic variants of
        the same intent ("show overdue" == "who owes me") still share a hit

    The current DATE is folded in (C6) so day-sensitive answers refresh daily.
    """
    day = day or date.today().isoformat()
    disc = _cache_disc(route, user_query, topic, handler_key, is_writing)
    return hashlib.md5(f"{user_id}:{day}:{disc}".encode("utf-8")).hexdigest()


def _cache_disc(route: str, user_query: str, topic: str, handler_key, is_writing: bool) -> str:
    """The cache discriminator (the part that decides which answers share an entry)."""
    if route == "AI_COMPLEX" or is_writing:
        return f"q:{(user_query or '').strip().lower()}"
    if route == "DIRECT" and handler_key:
        # These are parameterised by the customer/ID named IN the query, so keying
        # on the handler alone would make every customer (or invoice) share one
        # entry. Key on the query so each distinct lookup runs its own handler.
        if handler_key in ("client_summary", "customer_invoices", "invoice_detail"):
            return f"q:{(user_query or '').strip().lower()}"
        return handler_key
    # AI_SIMPLE on the catch-all topic: `business_summary` is also `_detect_topic`'s
    # safe default, so unrelated fallback queries ("do yo know Rahul traders", "what
    # about my pricing") would all collide on it and serve each other's cached
    # answer. Too coarse to share — key on the query.
    if route == "AI_SIMPLE" and topic == "business_summary":
        return f"q:{(user_query or '').strip().lower()}"
    return topic


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
    named = _extract_customer_name(q, user_id)
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
        s_tier, s_intent, s_conf = _semantic_classify(user_query)
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


def _log_token_usage(business_id, model, tier, usage, acc) -> None:
    """
    Record one Groq call's token usage to TokenUsage AND add it to the running
    per-request accumulator `acc`. This is the single source of token truth —
    every Groq call (conversational, polish, tool round, final round) flows
    through here, so budgets and the admin usage page reflect real spend.
    """
    ti = _safe_int(getattr(usage, "prompt_tokens", 0))
    to = _safe_int(getattr(usage, "completion_tokens", 0))
    acc["in"]  += ti
    acc["out"] += to
    if not (ti or to):
        return
    db = SessionLocal()
    try:
        from database.models import TokenUsage
        db.add(TokenUsage(
            business_id   = business_id,
            model         = model,
            model_tier    = tier,
            input_tokens  = ti,
            output_tokens = to,
            total_tokens  = ti + to,
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"[TOKENS] Failed to log usage ({tier}): {e}")
    finally:
        db.close()


_SESSION_PLACEHOLDER = "New chat"

# A leading greeting/filler shouldn't become the conversation title — otherwise
# every chat a user opens with "hi" is titled "hi" and they're indistinguishable.
_GREETING_RE = re.compile(
    r"^(hi+|hey+|hello+|hiya|yo|hola|sup|namaste|"
    r"thanks?|thank\s*you|thankyou|thx|ty|"
    r"ok(ay)?|cool|nice|great|good\s+(morning|afternoon|evening|day)|greetings)"
    r"[\s!.,?]*$",
    re.I,
)


def _is_titleable(text: str) -> bool:
    """True if this message is substantive enough to title a conversation."""
    t = (text or "").strip()
    return bool(t) and _GREETING_RE.match(t) is None


def _title_from(text: str) -> str:
    t = (text or "").strip()
    return t[:40] + ("..." if len(t) > 40 else "")


class _UsageEstimate:
    """
    Fallback usage for a streamed response that exposed no usage object
    (~4 chars/token heuristic). Streamed traffic is the app's main path, so it
    must never log 0 tokens (R1) — an estimate keeps budgets honest.
    """
    def __init__(self, messages, completion_text: str):
        def _clen(m):
            c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            return len(str(c or ""))
        self.prompt_tokens     = sum(_clen(m) for m in (messages or [])) // 4
        self.completion_tokens = (max(1, len(completion_text) // 4)
                                  if completion_text else 0)


def _stream_deltas(client, messages, model, business_id, tier, acc, **kw):
    """
    Stream a chat completion, yielding text deltas. Requests real usage via
    stream_options={"include_usage": True} (Groq is OpenAI-compatible); the
    usage arrives on a final choices-less chunk, which is captured and logged
    through _log_token_usage. Falls back gracefully:
      - SDK too old for stream_options → retry without it
      - no usage chunk seen           → character-count estimate
    """
    base = dict(messages=messages, model=model, stream=True, **kw)
    try:
        s = client.chat.completions.create(**base,
                                           stream_options={"include_usage": True})
    except TypeError:
        s = client.chat.completions.create(**base)

    usage, text = None, ""
    for chunk in s:
        u = getattr(chunk, "usage", None)
        if u is not None:
            usage = u                      # usage-only final chunk
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue
        delta = choices[0].delta.content
        if delta:
            text += delta
            yield delta
    _log_token_usage(business_id, model, tier,
                     usage or _UsageEstimate(messages, text), acc)


def _resolve_session(active_user_id: int, session_id: str, user_query: str) -> str:
    """
    Resolve the session title for this session_id. The title is the first
    SUBSTANTIVE user message — greetings ("hi", "thanks") are skipped so a chat
    opened with "hi" isn't permanently titled "hi". When the first real question
    arrives in a session that only had greetings, earlier rows are retro-fitted
    to the new title so the sidebar updates.
    """
    db = SessionLocal()
    session_title = _SESSION_PLACEHOLDER
    try:
        first = db.query(ChatMessage).filter(
            ChatMessage.business_id == active_user_id,
            ChatMessage.session_id  == session_id,
        ).order_by(ChatMessage.id.asc()).first()

        existing_title = first.session_title if first else None
        # Keep an existing real title (incl. one the user manually renamed to).
        if existing_title and existing_title not in (_SESSION_PLACEHOLDER, "Untitled Conversation") \
                and _is_titleable(existing_title):
            return existing_title

        if _is_titleable(user_query):
            session_title = _title_from(user_query)
            # Upgrade any earlier greeting-only rows in this session.
            if first is not None:
                db.query(ChatMessage).filter(
                    ChatMessage.business_id == active_user_id,
                    ChatMessage.session_id  == session_id,
                ).update({ChatMessage.session_title: session_title})
                db.commit()
        else:
            session_title = existing_title or _SESSION_PLACEHOLDER
    except Exception as e:
        db.rollback()
        logger.error(f"Error resolving session title: {e}", exc_info=True)
    finally:
        db.close()
    return session_title


def _fetch_history(active_user_id: int, session_id: str) -> list:
    """Last 6 turns for this session, long responses truncated to keep context lean."""
    db = SessionLocal()
    history = []
    try:
        rows = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.business_id == active_user_id,
                ChatMessage.session_id  == session_id,
            )
            .order_by(ChatMessage.id.desc())
            .limit(6)
            .all()
        )
        for m in reversed(rows):
            content = m.content
            if len(content) > 400:
                content = content[:400] + "... [truncated]"
            history.append({"role": m.role, "content": content})
    except Exception as e:
        logger.error(f"Error fetching chat history: {e}", exc_info=True)
    finally:
        db.close()
    return history


def _log_chat(business_id, user_query, response, session_id, session_title,
              source="ai", model_tier=None, cached=False, remember=True) -> None:
    """
    Persist a user+assistant turn to ChatMessage. When `remember` is True the
    turn is also embedded into the Chroma memory (skip for conversational chit-
    chat and cache replays, which add no durable business signal).
    """
    db = SessionLocal()
    try:
        db.add(ChatMessage(
            business_id=business_id, role="user", content=user_query,
            session_id=session_id, session_title=session_title,
        ))
        db.add(ChatMessage(
            business_id=business_id, role="assistant", content=response,
            session_id=session_id, session_title=session_title,
            source=source, model_tier=model_tier, cached=cached,
        ))
        db.commit()
        if remember:
            save_chat_memory(
                business_id=business_id, session_id=session_id,
                session_title=session_title,
                user_query=user_query, assistant_response=response,
            )
    except Exception as e:
        db.rollback()
        logger.error(f"[CHAT] {e}", exc_info=True)
    finally:
        db.close()


# Handlers whose output is a precise factual record — skip the AI insight layer
# (no analysis to add, and high confabulation risk on single records / tables).
_NO_POLISH = {"invoice_detail", "customer_invoices"}


def _polish(raw_markdown: str, topic: str, client: Groq,
            business_id=None, acc=None) -> str:
    """
    Adds a 2-sentence AI insight layer to raw DB/handler output.
    Cost: ~250 tokens FIRST call per topic (now logged via _log_token_usage).
    Falls back to raw_markdown on any Groq error — never blocks the response.
    """
    try:
        resp = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a business analyst. Read the BUSINESS DATA below and write at most 2 short sentences:\n"
                        "1. The single biggest risk or insight, citing the exact number from the data.\n"
                        "2. One concrete next step.\n"
                        "\n"
                        "HARD RULES — follow exactly:\n"
                        "- Use ONLY facts that appear in the data. NEVER invent or guess customer names, "
                        "customer IDs, invoice numbers, product names/IDs, or amounts.\n"
                        "- If the data names a specific customer or item, refer to it by that exact name. "
                        "If the data has only totals and names NO specific customer/item, give a GENERAL "
                        "next step — do NOT make up a name, an ID, or a figure.\n"
                        "- If the data says everything is fine (e.g. sufficient stock), say so plainly; do not invent a problem.\n"
                        "- NEVER infer timing: a 'Paid' status does NOT tell you WHEN it was paid. Never say "
                        "'paid N days early/late' or any payment date — that data is not here.\n"
                        "- NEVER do arithmetic between unlike things (e.g. an amount vs a date) and never "
                        "compute a difference or ratio unless BOTH numbers literally appear in the data.\n"
                        "- If the data says 'top N of M (₹X total)', then ₹X is the total of ALL M — never "
                        "describe it as the total of just the N shown.\n"
                        "- Do not contradict the data's own status labels (if it says Paid, it is Paid).\n"
                        "- Use the same currency symbol as the data (₹). Never use $.\n"
                        "- Exact numbers only (no rounding). No headers, no bullet points, no filler."
                    )
                },
                {"role": "user", "content": "BUSINESS DATA:\n" + raw_markdown[:900]}
            ],
            model=MODEL_SIMPLE,
            temperature=0.0,
            max_tokens=110,
        )
        if business_id is not None and acc is not None:
            _log_token_usage(business_id, MODEL_SIMPLE, "POLISH", getattr(resp, "usage", None), acc)
        insight = (resp.choices[0].message.content or "").strip()
        if insight:
            return f"{raw_markdown}\n\n---\n💡 {insight}"
        return raw_markdown
    except Exception as e:
        logger.warning(f"[POLISH] Groq polish failed — returning raw. Reason: {e}")
        return raw_markdown


_AI_SIMPLE_SYSTEM_PROMPT = (
    "You are BIZASSIST, a sharp business advisor for Indian distributors and small businesses.\n"
    "\n"
    "CRITICAL — NEVER FABRICATE DATA:\n"
    "You may ONLY state an invoice ID, amount, date, status, customer name, or any figure\n"
    "that appears in a TOOL RESULT from THIS conversation. If you don't have the rows, CALL\n"
    "THE TOOL to fetch them. If a tool cannot supply them, say plainly 'I don't have those\n"
    "details' — do NOT invent, estimate, guess, or pattern-fill them (e.g. inventing\n"
    "INV-0001, INV-0002… with made-up amounts). The conversation summary holds TOTALS, not\n"
    "line items — never reconstruct individual invoices from it. Fabricating financial data\n"
    "is the single worst thing you can do.\n"
    "\n"
    "RULES:\n"
    "1. Call a tool first for any business-data question. The summary in context has totals,\n"
    "   not the underlying rows — fetch the real rows before listing anything.\n"
    "2. Write like a trusted advisor. Use a table ONLY when the user asks for one, and fill\n"
    "   it STRICTLY from tool results; otherwise short paragraphs or a brief list.\n"
    "3. Always name specifics drawn from the data: customer names, invoice IDs, rupee\n"
    "   amounts, dates, days overdue. Vague answers are useless.\n"
    "4. End with ONE concrete action the owner can take right now — not a generic tip.\n"
    "5. Never write code. Never pad with filler sentences.\n"
    "6. You CANNOT perform actions — you cannot send emails/reminders, escalate, mark\n"
    "   invoices paid, or place orders. NEVER claim you did ('Done.', 'Sent.',\n"
    "   'I've escalated…'). If the user asks you to DO one of these, draft the content\n"
    "   if helpful and tell them to use the action button to actually send/run it.\n"
    "\n"
    "TONE: Direct, clear, human. Think 'smart accountant on the phone', not 'dashboard report'.\n"
    "\n"
    "Tool args must be valid JSON.\n"
)

_CONVERSATIONAL_SYSTEM_PROMPT = (
    "You are BIZASSIST, a business assistant. The user sent a short conversational "
    "message. Reply briefly and naturally in 1-2 sentences. Do NOT volunteer business "
    "data, reports, or unsolicited recommendations."
)

_ADVISE_SYSTEM_PROMPT = (
    "You are BIZASSIST, a sharp business advisor for Indian distributors. The user "
    "asked for SUGGESTIONS, and their REAL data is provided below. Give practical, "
    "specific advice grounded in that data.\n\n"
    "RULES:\n"
    "- Use ONLY the numbers, customers, and products in the data. NEVER invent any.\n"
    "- NEVER use hypothetical examples, illustrative names, or made-up amounts — "
    "no \"if Customer X has ₹50,000…\", no \"for example, a customer who…\". Every "
    "name and figure you write MUST appear verbatim in the data below. If the data "
    "doesn't support a point, leave it out.\n"
    "- Name names: tie each suggestion to a specific customer/product/amount.\n"
    "- 3-5 concrete suggestions, most impactful first. Short paragraphs or a brief "
    "numbered list.\n"
    "- Use ₹ with comma formatting (₹2,48,669). Never $.\n"
    "- End with ONE thing to do today.\n"
)


def _build_ai_simple_messages(user_query: str, history: list, active_user_id: int) -> list:
    """Assemble the message list for an AI_SIMPLE tool-calling turn."""
    messages = [{"role": "system", "content": _AI_SIMPLE_SYSTEM_PROMPT}]
    past_memories = search_chat_memories(active_user_id, user_query, limit=3)
    if past_memories:
        messages.append({"role": "system", "content": f"[Relevant past context]\n{past_memories}"})
    if os.getenv("SNAPSHOT_CONTEXT", "true").lower() != "false":
        snap = get_business_snapshot(active_user_id)
        if snap:
            messages.append({"role": "system", "content": snap})
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_query})
    return messages


# ─────────────────────────────────────────────────────────────────────────────
# THE ONE PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def process_query(prompt_message: str, session_id_in: Optional[str],
                  current_user: dict, client, *, stream: bool):
    """
    The single routing pipeline shared by /ask and /ask/stream.

    Yields event dicts:
      {"type": "status",  "content": str}            progress text (streamed UIs)
      {"type": "replace", "content": str}            full content for instant answers
      {"type": "token",   "content": str}            streamed delta (stream=True only)
      {"type": "raw_sse", "data": str}               pre-formatted SSE (agent graph)
      {"type": "final",   "envelope": dict}          the complete response envelope
      {"type": "error",   "message": str, "status_code": int, ...}

    `handle()` keeps only the final envelope; `handle_stream()` forwards each
    event as SSE. The envelope ALWAYS carries the full markdown + real token
    totals, so the non-stream path no longer reports tokens:0.
    """
    user_query     = prompt_message.strip()
    active_user_id = current_user["id"]
    acc            = {"in": 0, "out": 0}   # per-request token accumulator (real truth)

    session_id    = session_id_in or str(uuid.uuid4())
    session_title = _resolve_session(active_user_id, session_id, user_query)
    history       = _fetch_history(active_user_id, session_id)

    # ── Layer 1: classify ───────────────────────────────────────────
    route, handler_key = classify(user_query, has_history=len(history) > 0)
    # Entity-first: a short query that names a known customer → client lookup,
    # before a stray keyword ("fresh") can misroute it.
    route, handler_key = _maybe_entity_first(route, handler_key, user_query, active_user_id)

    # User correction override (feedback loop): if this user marked this exact
    # query wrong and told us the right intent, honour it above all routing.
    _override = get_override(active_user_id, user_query)
    if _override:
        route, handler_key = _override
        logger.info(f"[ROUTER] override → {route}/{handler_key} q='{user_query[:60]}'")

    # ── NEXT-GEN ROUTER SWITCH (LLM_ROUTER=on) ──────────────────────
    # When ON, the LLM router's decision REPLACES the legacy one (a user's
    # explicit override still wins). On ANY failure it returns None and the
    # legacy decision above stands — legacy is the permanent safety net.
    # New tiers it can produce: AI_ADVISE (data + grounded advice) and
    # ACTION (gated preview — never auto-executed), handled below.
    from services.router_mode import get_mode as _router_mode, pretty as _router_pretty
    _rmode = _router_mode()            # legacy(off) | shadow | new(on) — resolved ONCE
    _llm_decision = None
    _llm_entities = {}                 # extracted hints we actually honor (B2/B3/B4)
    # B6: legacy already matched an exact dashboard template → it's deterministic,
    # so skip the LLM router's extra 1-2s call (it only agrees with these).
    _llm_skip = (route == "DIRECT" and handler_key in _LLM_FASTPATH_HANDLERS)
    if _override is None and _rmode == "on" and not _llm_skip:
        try:
            from services.llm_router import route as _llm_route
            _r = _llm_route(user_query, client=client, business_id=active_user_id)
            if _r is not None:
                _, _, _decision = _r
                _new_route, _new_handler, _ents, _accepted = _resolve_llm_decision(
                    _decision, route, handler_key)
                if not _accepted:
                    logger.info(f"[ROUTER] llm conf {_decision.confidence:.2f} < floor "
                                f"{_LLM_CONF_FLOOR} → keep legacy {route}/{handler_key} "
                                f"q='{user_query[:60]}'")
                else:
                    _llm_decision = _decision
                    _llm_entities = _ents
                    logger.info(f"[ROUTER] llm → {_new_route}/{_new_handler} "
                                f"(legacy was {route}/{handler_key}) q='{user_query[:60]}'")
                    route, handler_key = _new_route, _new_handler
        except Exception as _le:
            logger.warning(f"[ROUTER] llm route failed, legacy stands: {_le}")

    # ── Rate limit ──────────────────────────────────────────────────
    rl = check_rate_limit(active_user_id, route)
    if not rl["allowed"]:
        logger.warning(f"[RATELIMIT] Blocked user {active_user_id}: {rl['reason']}")
        yield {
            "type": "error", "message": rl["reason"], "status_code": 429,
            "limit": rl.get("limit"), "used": rl.get("used"),
            "retry_after": rl.get("retry_after"),
        }
        return

    # Cache salt: AI_COMPLEX keys on exact query (data-driven); everything else
    # keys on topic so "show overdue" and "who owes me" share one entry.
    _pre_topic   = _detect_topic(user_query)
    _is_writing  = bool(_WRITING_ACTIONS.search(user_query))   # "draft/write a reminder…"
    # AI_ADVISE keys on the exact query (advice for "loyalty offers" must not be
    # served to a different advice question that shares the topic). Compute the
    # effective flag ONCE so the salt and the debug log lines agree (B7 — the REQ
    # line used to print the topic-keyed disc for AI_ADVISE).
    _eff_writing = _is_writing or route == "AI_ADVISE"
    history_salt = _cache_salt(active_user_id, route, user_query, _pre_topic,
                               handler_key, is_writing=_eff_writing)

    # Full routing+cache context for root-cause debugging (LOG_LEVEL=DEBUG). This
    # is the line that makes cache-collision bugs obvious: if `handler` and
    # `cache_disc` disagree for a DIRECT query, two intents are sharing a key.
    # One INFO line per request, ALIGNED with the response: rid + router mode +
    # final route/handler. Grep "[REQ" to trace exactly which router (legacy /
    # shadow / new) produced any answer, even across live mode switches.
    rid = uuid.uuid4().hex[:8]
    logger.info(
        f"[REQ {rid}] router={_router_pretty(_rmode)} user={active_user_id} "
        f"route={route} handler={handler_key} topic={_pre_topic} writing={_is_writing} "
        f"cache_disc='{_cache_disc(route, user_query, _pre_topic, handler_key, _eff_writing)}' "
        f"q='{user_query[:100]}'"
    )

    # Phase 1 shadow routing (no-op unless INTENT_ROUTER=shadow|on) — gathers
    # semantic-vs-regex agreement data on real traffic without changing routing.
    _maybe_shadow_route(user_query, route, handler_key, _pre_topic)

    # Next-gen LLM router shadow (services/llm_router.py — NEW parallel system).
    # No-op unless LLM_ROUTER=shadow. Runs in a background thread (zero added
    # latency) AFTER the legacy decision and changes NOTHING — it only logs
    # '[ROUTER][llm-shadow] …' lines for analyze_llm_shadow.py.
    if _rmode == "shadow":
        try:
            from services.llm_router import shadow_compare as _llm_shadow
            _llm_shadow(user_query, route, handler_key, _pre_topic,
                        business_id=active_user_id)
        except Exception as _le:
            logger.debug(f"[ROUTER][llm-shadow] skipped: {_le}")

    # ── Layer 1.5: CONVERSATIONAL short-circuit ─────────────────────
    if route == "CONVERSATIONAL":
        logger.info(f"[CONVERSATIONAL] '{user_query}'")
        conv_messages = [
            {"role": "system", "content": _CONVERSATIONAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_query},
        ]
        if stream:
            full = ""
            for delta in _stream_deltas(client, conv_messages, MODEL_SIMPLE,
                                        active_user_id, "CONVERSATIONAL", acc,
                                        temperature=0.5, max_tokens=80):
                full += delta
                yield {"type": "token", "content": delta}
        else:
            resp = client.chat.completions.create(
                messages=conv_messages, model=MODEL_SIMPLE,
                temperature=0.5, max_tokens=80,
            )
            full = (resp.choices[0].message.content or "Got it!").strip()
            _log_token_usage(active_user_id, MODEL_SIMPLE, "CONVERSATIONAL", getattr(resp, "usage", None), acc)

        _log_chat(active_user_id, user_query, full, session_id, session_title,
                  source="conversational", remember=False)
        yield {"type": "final", "envelope": {
            "answer":        {"markdown": full, "title": ""},
            "response":      full,
            "source":        "conversational",
            "suggestions":   [],
            "session_id":    session_id,
            "session_title": session_title,
            "meta": {"tokens": acc["in"] + acc["out"], "model": MODEL_SIMPLE,
                     "model_tier": "CONVERSATIONAL", "cached": False},
        }}
        return

    # ── ACTION (LLM router only): gated preview, NEVER auto-executed ─
    # "Escalate 90+ days" must return a confirm chip, not a hallucinated "Done."
    if route == "ACTION":
        _action = getattr(_llm_decision, "action", None)
        _ents   = _llm_entities or (getattr(_llm_decision, "entities", {}) or {})
        markdown = "I can't run that automatically yet — here's what I found instead."
        suggestions = []
        try:
            from services.actions import is_action as _is_action, preview as _a_preview
            if _action and _is_action(_action):
                prev = _a_preview(_action, active_user_id, _ents)
                nice = _action.replace("_", " ")
                summary = (prev or {}).get("summary", "")
                markdown = (f"I can **{nice}** for you. Nothing is sent or changed "
                            f"until you confirm.\n\n{summary}".strip())
                suggestions = [{
                    "id": _action, "label": f"Preview & confirm: {nice}",
                    "type": "action", "action": _action, "confirm": True,
                    "params": _ents, "icon": "bell",
                }]
        except Exception as _ae:
            logger.warning(f"[ACTION] preview failed: {_ae}")
        _log_chat(active_user_id, user_query, markdown, session_id, session_title,
                  source="action", remember=False)
        yield {"type": "replace", "content": markdown}
        yield {"type": "final", "envelope": {
            "answer":        {"markdown": markdown, "title": ""},
            "response":      markdown,
            "source":        "action",
            "suggestions":   suggestions,
            "alerts":        [],
            "chart":         None,
            "session_id":    session_id,
            "session_title": session_title,
            "meta": {"tokens": acc["in"] + acc["out"], "model": MODEL_SIMPLE,
                     "model_tier": "ACTION", "cached": False},
        }}
        return

    # ── Layer 2: universal cache check ──────────────────────────────
    cached = get_cached_query_response(active_user_id, user_query, history_salt)
    if cached:
        logger.info(f"[CACHE] HIT [REQ {rid}] source={cached.get('source','?')} "
                    f"disc='{_cache_disc(route, user_query, _pre_topic, handler_key, _eff_writing)}' query='{user_query[:80]}'")
        markdown = cached.get("answer", {}).get("markdown") or cached.get("response", "")
        _log_chat(active_user_id, user_query, markdown, session_id, session_title,
                  source=cached.get("source", "ai"), model_tier=cached.get("model_tier"),
                  cached=True, remember=False)
        envelope = {
            "answer":        {"markdown": markdown, "title": ""},
            "response":      markdown,
            "source":        cached.get("source", "ai"),
            "suggestions":   cached.get("suggestions", []),
            "alerts":        cached.get("alerts", []),
            "chart":         cached.get("chart"),
            "session_id":    session_id,
            "session_title": session_title,
            "meta": {
                "tokens":     0,
                "cached":     True,
                "model":      cached.get("meta", {}).get("model") or cached.get("model_used"),
                "model_tier": cached.get("meta", {}).get("model_tier") or cached.get("model_tier"),
            },
        }
        yield {"type": "replace", "content": markdown}
        yield {"type": "final", "envelope": envelope}
        return

    # ── AI_ADVISE (LLM router only): real data + grounded advice ────
    # "Suggest loyalty offers for my top customers" → fetch the top-customers
    # data, then ask the 8B for advice grounded ON that data. Fixes the
    # advice-questions-get-raw-tables bug.
    if route == "AI_ADVISE":
        data_md = None
        if handler_key:
            try:
                data_md = direct_handle(handler_key, user_query, active_user_id, params=_llm_entities)
            except Exception as _de:
                logger.debug(f"[ADVISE] data fetch failed: {_de}")
        if data_md and data_md != CUSTOMER_NOT_FOUND:
            # B5: collection/DSO advice ("why is my collection rate low") needs
            # real names to be specific — enrich with the actual top-debtors so
            # the model cites them instead of inventing an example customer.
            if handler_key in ("dso_summary", "overdue_amount", "total_revenue"):
                try:
                    _debtors_md = direct_handle("top_debtors", user_query, active_user_id)
                    if _debtors_md:
                        data_md = f"{data_md}\n\n--- YOUR TOP DEBTORS (real) ---\n{_debtors_md}"
                except Exception:
                    pass
            logger.info(f"[ADVISE] grounding on handler={handler_key} | '{user_query[:60]}'")
            advise_messages = [
                {"role": "system", "content": _ADVISE_SYSTEM_PROMPT},
                {"role": "user", "content":
                    f"QUESTION: {user_query}\n\nTHEIR REAL BUSINESS DATA:\n{data_md[:3500]}"},
            ]
            if stream:
                yield {"type": "status", "content": "Reading your data…"}
                full_text = ""
                for delta in _stream_deltas(client, advise_messages, MODEL_SIMPLE,
                                            active_user_id, "AI_ADVISE", acc,
                                            temperature=0.3, max_tokens=700):
                    full_text += delta
                    yield {"type": "token", "content": delta}
            else:
                _ar = client.chat.completions.create(
                    messages=advise_messages, model=MODEL_SIMPLE,
                    temperature=0.3, max_tokens=700,
                )
                _log_token_usage(active_user_id, MODEL_SIMPLE, "AI_ADVISE",
                                 getattr(_ar, "usage", None), acc)
                full_text = (_ar.choices[0].message.content or "").strip()
            recs      = recommend(handler_key, active_user_id)
            anomalies = detect_anomalies(active_user_id)
            envelope = {
                "answer":        {"markdown": full_text, "title": ""},
                "response":      full_text,
                "source":        "advice",
                "suggestions":   recs,
                "alerts":        anomalies,
                "chart":         None,
                "session_id":    session_id,
                "session_title": session_title,
                "meta": {"tokens": acc["in"] + acc["out"], "model": MODEL_SIMPLE,
                         "model_tier": "AI_ADVISE", "cached": False},
            }
            set_cached_query_response(active_user_id, user_query, envelope, history_salt)
            _log_chat(active_user_id, user_query, full_text, session_id, session_title,
                      source="advice", model_tier="AI_ADVISE")
            yield {"type": "final", "envelope": envelope}
            return
        # No grounding data → plain AI_SIMPLE (tool-calling) handles it below.
        route, handler_key = "AI_SIMPLE", None

    # ── Layer 2.5: DIRECT DB answer → polish → cache ────────────────
    if route == "DIRECT":
        answer = direct_handle(handler_key, user_query, active_user_id, params=_llm_entities)
        if answer:
            logger.info(f"[DIRECT] handler={handler_key} | '{user_query}'")
            # Honest "customer not found" — return verbatim. Don't polish (the LLM
            # would re-invent a client card). Offer near-miss customers as "did you
            # mean" chips so the user can pick the one they meant.
            if answer == CUSTOMER_NOT_FOUND:
                cands = _customer_candidates(user_query, active_user_id)
                if cands:
                    chips = [{
                        "id":     f"didyoumean_{c}",
                        "label":  c,
                        "type":   "ai",
                        "prompt": f"tell me about {c}",
                        "icon":   "users",
                    } for c in cands]
                    answer = "I couldn't find an exact match. Did you mean one of these?"
                    logger.info(f"[DIRECT] client_summary not found → {len(cands)} suggestion(s) q='{user_query}'")
                else:
                    chips = []
                envelope = {
                    "answer":        {"markdown": answer, "title": ""},
                    "response":      answer,
                    "source":        "db",
                    "suggestions":   chips,
                    "alerts":        [],
                    "chart":         None,
                    "session_id":    session_id,
                    "session_title": session_title,
                    "meta": {"tokens": 0, "model": MODEL_SIMPLE,
                             "model_tier": "DIRECT", "cached": False},
                }
                _log_chat(active_user_id, user_query, answer, session_id, session_title,
                          source="db", remember=False)
                yield {"type": "replace", "content": answer}
                yield {"type": "final", "envelope": envelope}
                return
            # No per-answer "insight" bulb — it confabulated on factual data and
            # added little value. Real advice now lives in the dedicated Smart
            # Insights advisor (services/smart_insights.py, the chip-bar feature).
            # DIRECT answers return their clean DB data; deterministic alert chips
            # (cash-flow / expiry) still come from detect_anomalies below.
            polished   = answer
            recs       = recommend(handler_key, active_user_id)
            # On a single-invoice view, offer the "Mark as paid" action (gated:
            # preview → confirm → execute; it no-ops if already Paid).
            if handler_key == "invoice_detail":
                recs = [{"id": "mark_paid", "label": "Mark as paid", "type": "action",
                         "action": "mark_invoice_paid", "confirm": True,
                         "params": {"query": user_query}, "icon": "check"}] + (recs or [])
            anomalies  = detect_anomalies(active_user_id)
            # ONE grounded, query-scoped insight (deterministic snapshot math,
            # no LLM) — the trustworthy successor to the removed bulb. None when
            # there's nothing relevant to add.
            ctx_insight = None
            try:
                from services.smart_insights import contextual_insight
                ctx_insight = contextual_insight(active_user_id, handler_key)
            except Exception as _ci_e:
                logger.debug(f"[DIRECT] contextual_insight skipped: {_ci_e}")
            envelope = {
                "answer":        {"markdown": polished, "title": ""},
                "response":      polished,
                "source":        "db",
                "suggestions":   recs,
                "alerts":        anomalies,
                "chart":         None,
                "insight":       ctx_insight,
                "session_id":    session_id,
                "session_title": session_title,
                "meta": {"tokens": acc["in"] + acc["out"], "model": MODEL_SIMPLE,
                         "model_tier": "DIRECT", "cached": False},
            }
            set_cached_query_response(active_user_id, user_query, envelope, history_salt)
            _log_chat(active_user_id, user_query, polished, session_id, session_title, source="db")
            yield {"type": "replace", "content": polished}
            yield {"type": "final", "envelope": envelope}
            return
        # handler returned None (DB error) → fall through to AI

    # ── Layer 2.7: intent-first promotion (AI_SIMPLE + known topic) ─
    if route == "AI_SIMPLE" and not _is_writing and _pre_topic in _INTENT_DIRECT:
        try:
            from services.intents import resolve_intent
            _ir = resolve_intent(_pre_topic, active_user_id)
            if _ir and _ir.get("answer", {}).get("markdown"):
                logger.info(f"[INTENT] Promoted AI_SIMPLE → DIRECT via topic={_pre_topic}")
                raw_md    = _ir["answer"]["markdown"]
                polished  = raw_md   # no insight bulb — see Smart Insights advisor
                anomalies = detect_anomalies(active_user_id)
                chart     = _build_chart_data(user_query, active_user_id)
                recs      = _ir.get("suggestions", recommend(_pre_topic, active_user_id))
                envelope = {
                    "answer":        {"markdown": polished, "title": ""},
                    "response":      polished,
                    "source":        "intent",
                    "suggestions":   recs,
                    "alerts":        anomalies,
                    "chart":         chart,
                    "session_id":    session_id,
                    "session_title": session_title,
                    "meta": {"tokens": acc["in"] + acc["out"], "model": MODEL_SIMPLE,
                             "model_tier": "INTENT", "cached": False},
                }
                set_cached_query_response(active_user_id, user_query, envelope, history_salt)
                _log_chat(active_user_id, user_query, polished, session_id, session_title, source="db")
                yield {"type": "replace", "content": polished}
                yield {"type": "final", "envelope": envelope}
                return
        except Exception as _ie:
            logger.debug(f"[INTENT] Fallback to AI: {_ie}")

    # ── Layer 3a: AI_COMPLEX → LangGraph multi-agent ────────────────
    tool_calls_made = None
    if route == "AI_COMPLEX":
        _agent_mode = os.getenv("AGENT_MODE", "pipeline").lower()
        logger.info(f"[AI_COMPLEX] {'agent-loop' if _agent_mode == 'loop' else 'LangGraph agents'} "
                    f"| '{user_query}'")
        if stream:
            full_text = ""
            for event_str in run_agent_graph_stream(user_query, active_user_id, history):
                try:
                    evt = json.loads(event_str[6:])  # strip "data: "
                    if evt.get("type") == "ag_done":
                        full_text = evt.get("full_text", "")
                        _toks = evt.get("tokens") or {}
                        acc["in"]  += _safe_int(_toks.get("input"))
                        acc["out"] += _safe_int(_toks.get("output"))
                        continue  # don't forward ag_done to the client
                except Exception:
                    pass
                yield {"type": "raw_sse", "data": event_str}
        else:
            _ag = run_agent_graph(
                user_query=user_query, business_id=active_user_id, history=history,
            )
            # run_agent_graph returns {text, tokens_in, tokens_out}; tolerate a bare
            # string too (older callers / test mocks).
            if isinstance(_ag, dict):
                full_text  = _ag.get("text", "")
                acc["in"]  += _safe_int(_ag.get("tokens_in"))
                acc["out"] += _safe_int(_ag.get("tokens_out"))
            else:
                full_text = _ag or ""
        selected_model = MODEL_COMPLEX

    # ── Layer 3b: AI_SIMPLE → tool-calling agent ────────────────────
    else:
        selected_model = MODEL_SIMPLE
        logger.info(f"[AI_SIMPLE] model={selected_model} | '{user_query}'")
        if stream:
            yield {"type": "status", "content": "Fetching your business data…"}

        messages   = _build_ai_simple_messages(user_query, history, active_user_id)
        completion = client.chat.completions.create(
            messages=messages, model=selected_model,
            temperature=0.1, max_tokens=800,
            tools=tool_schemas, tool_choice="auto",
        )
        _log_token_usage(active_user_id, selected_model, "AI_SIMPLE", completion.usage, acc)
        resp_msg        = completion.choices[0].message
        tool_calls      = resp_msg.tool_calls
        tool_calls_made = tool_calls

        if tool_calls:
            messages.append(resp_msg)
            for tc in tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments or "{}")
                tr      = execute_tool(fn_name, fn_args, active_user_id)
                if isinstance(tr, str) and len(tr) > _MAX_TOOL_CHARS:
                    logger.info(f"[AI_SIMPLE] tool '{fn_name}' result {len(tr)} chars → "
                                f"truncated to {_MAX_TOOL_CHARS} (token budget)")
                    tr = tr[:_MAX_TOOL_CHARS] + "\n…[truncated to fit the model's token budget]"
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "name": fn_name, "content": tr})
            if stream:
                full_text = ""
                for delta in _stream_deltas(client, messages, selected_model,
                                            active_user_id, "AI_SIMPLE", acc,
                                            temperature=0.1, max_tokens=800):
                    full_text += delta
                    yield {"type": "token", "content": delta}
            else:
                second = client.chat.completions.create(
                    messages=messages, model=selected_model,
                    temperature=0.1, max_tokens=800,
                )
                _log_token_usage(active_user_id, selected_model, "AI_SIMPLE", second.usage, acc)
                full_text = second.choices[0].message.content or ""
        else:
            if stream:
                full_text = ""
                for delta in _stream_deltas(client, messages, selected_model,
                                            active_user_id, "AI_SIMPLE", acc,
                                            temperature=0.1, max_tokens=800):
                    full_text += delta
                    yield {"type": "token", "content": delta}
            else:
                full_text = resp_msg.content or ""

    # ── Shared: assemble + cache + log the AI envelope ──────────────
    chart       = _build_chart_data(user_query, active_user_id)
    topic       = _detect_topic(user_query, tool_calls_made if route != "AI_COMPLEX" else None)
    suggestions = recommend(topic, active_user_id)
    anomalies   = detect_anomalies(active_user_id)

    envelope = {
        "answer":        {"markdown": full_text, "title": ""},
        "response":      full_text,
        "source":        "ai",
        "suggestions":   suggestions,
        "alerts":        anomalies,
        "chart":         chart,
        "session_id":    session_id,
        "session_title": session_title,
        "meta": {"tokens": acc["in"] + acc["out"], "model": selected_model,
                 "model_tier": route, "cached": False},
    }
    set_cached_query_response(active_user_id, user_query, envelope, history_salt)
    _log_chat(active_user_id, user_query, full_text, session_id, session_title,
              source="ai", model_tier=route)
    yield {"type": "final", "envelope": envelope}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC ENTRY POINTS  (thin adapters over process_query)
# ─────────────────────────────────────────────────────────────────────────────

_ERROR_CODES = {429: "rate_limited", 500: "internal_error"}


def _raise_pipeline_error(ev: dict):
    """Turn a pipeline 'error' event into a real HTTP error (H1)."""
    sc = ev.get("status_code", 500)
    raise ask_error(
        sc,
        _ERROR_CODES.get(sc, "error"),
        ev.get("message", "Request failed."),
        limit=ev.get("limit"),
        used=ev.get("used"),
        retry_after=ev.get("retry_after"),
    )


def handle(prompt_message: str, session_id_in: Optional[str], current_user: dict, client: Groq):
    """
    Non-streaming /ask endpoint. Drains the shared pipeline and returns one JSON
    envelope on success. On failure it raises AskError, which the app's exception
    handler renders with a real HTTP status code (no more 200-OK error bodies).
    Token totals in meta.tokens are real (no more tokens:0).
    """
    try:
        final_env = None
        error_ev  = None
        for ev in process_query(prompt_message, session_id_in, current_user, client, stream=False):
            t = ev["type"]
            if t == "error":
                error_ev = ev
                break
            if t == "final":
                final_env = ev["envelope"]
            # status / replace / token / raw_sse are irrelevant to the JSON path
    except Exception as e:
        error_str = str(e)
        logger.error(f"[ASK] Error handling request: {error_str}", exc_info=True)
        if "429" in error_str or "rate_limit" in error_str.lower() or "quota" in error_str.lower():
            raise ask_error(429, "quota_exceeded",
                            "API quota exceeded. Please wait a moment and try again.")
        raise ask_error(500, "internal_error",
                        "An internal error occurred while processing your request.")

    if error_ev is not None:
        _raise_pipeline_error(error_ev)
    if final_env is None:
        raise ask_error(500, "internal_error", "No response produced.")
    # Traceability: stamp WHICH router produced this answer into meta, and log a
    # [DONE] line that pairs with the request's [REQ] line (match on q=…).
    try:
        from services.router_mode import get_mode as _gm, pretty as _pp
        final_env.setdefault("meta", {})["router"] = _pp(_gm())
    except Exception:
        pass
    _m = final_env.get("meta", {})
    logger.info(
        f"[DONE] router={_m.get('router')} source={final_env.get('source')} "
        f"tier={_m.get('model_tier')} tokens={_m.get('tokens')} cached={_m.get('cached')} "
        f"q='{prompt_message.strip()[:80]}'"
    )
    return final_env


def handle_stream(prompt_message: str, session_id_in, current_user: dict, client):
    """
    SSE streaming /ask/stream endpoint. Forwards the shared pipeline's events.

    Event types emitted to the client:
      status  — progress text (dimmed, not part of the answer)
      token   — streamed token, append to the current message
      replace — full content for instant answers (DIRECT / CACHE / INTENT)
      done    — final metadata: source, meta, suggestions, alerts, chart, session
      error   — error payload
    """
    def _sse(event_type: str, **kwargs) -> str:
        return "data: " + json.dumps({"type": event_type, **kwargs}, ensure_ascii=False) + "\n\n"

    try:
        for ev in process_query(prompt_message, session_id_in, current_user, client, stream=True):
            t = ev["type"]
            if t == "error":
                yield _sse("error", message=ev.get("message"), status_code=ev.get("status_code", 500))
                return
            elif t == "status":
                yield _sse("status", content=ev["content"])
            elif t == "token":
                yield _sse("token", content=ev["content"])
            elif t == "replace":
                yield _sse("replace", content=ev["content"])
            elif t == "raw_sse":
                yield ev["data"]
            elif t == "final":
                env = ev["envelope"]
                # Traceability: stamp the router mode into meta (flows into the
                # 'done' SSE event) and pair this answer with its [REQ] line.
                try:
                    from services.router_mode import get_mode as _gm, pretty as _pp
                    env.setdefault("meta", {})["router"] = _pp(_gm())
                except Exception:
                    pass
                _m = env.get("meta", {})
                logger.info(
                    f"[DONE] router={_m.get('router')} source={env.get('source')} "
                    f"tier={_m.get('model_tier')} tokens={_m.get('tokens')} cached={_m.get('cached')} "
                    f"q='{prompt_message.strip()[:80]}'"
                )
                yield _sse("done",
                    source=env.get("source"),
                    suggestions=env.get("suggestions", []),
                    alerts=env.get("alerts", []),
                    chart=env.get("chart"),
                    session_id=env.get("session_id"),
                    session_title=env.get("session_title"),
                    meta=env.get("meta", {}),
                )

    except Exception as e:
        msg = str(e)
        logger.error(f"[STREAM] Unhandled error: {msg}", exc_info=True)
        low = msg.lower()
        if "tokens per minute" in low or "request too large" in low or "rate_limit" in low or "429" in low or "413" in low:
            user_msg = ("That request was too large or too frequent for the AI model's "
                        "current limit. Try a more specific question, or wait a minute and retry.")
        elif "invalid api key" in low or "401" in low:
            user_msg = "The AI service rejected the API key. Check GROQ_API_KEY on the server."
        else:
            user_msg = "An error occurred. Please try again."
        yield _sse("error", message=user_msg)
