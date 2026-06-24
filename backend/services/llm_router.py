"""
services/llm_router.py — the next-generation router (NEW FILE, parallel system).
================================================================================
ONE structured 8B call replaces the stacked heuristics (regex tiers, writing
guard, digit rules, entity-first, _detect_topic, embedding router). It returns
four things the old stack could never produce together:

    intent    — which registry handler answers it      (enum = HANDLERS keys)
    mode      — what the user wants BACK:
                  answer   raw data (table/metric)        → DIRECT handler
                  advise   suggestions grounded on data   → handler + advice pass
                  act      DO something (remind/escalate) → gated action PREVIEW
                  analyze  multi-source diagnosis/plan    → agent loop (70B)
                  chat     greeting / small talk          → conversational
    entities  — customer / invoice_id / limit / days_range / month (HINTS only;
                the DB fuzzy-match stays the source of truth)
    confidence

This is the Intercom-Fin / Klarna pattern: the LLM parses the request and picks
the tool in one shot. Cost: ~350 input + ~80 output tokens on the 8B model
(≈ $0.00002/query on Groq). One prevented misroute into the 70B loop (~6,500
tokens) pays for ~300 router calls.

ROLLOUT (no existing file's behaviour changes):
    LLM_ROUTER=off      (default) this module is never called
    LLM_ROUTER=shadow   ai_router calls shadow_compare() AFTER the legacy
                        decision, in a background thread (zero added latency).
                        It logs '[ROUTER][llm-shadow] AGREE|DISAGREE …' lines.
                        Report card: python analyze_llm_shadow.py
    (cutover later)     route() is ready to BE the router once shadow proves it;
                        the legacy regex stack then becomes the fallback.
"""
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("bizassist.llm_router")

MODEL = os.getenv("GROQ_MODEL_ROUTER",
                  os.getenv("GROQ_MODEL_SIMPLE", "llama-3.1-8b-instant"))

# ── The vocabulary (mirrors the live registries; update together) ───────────
# Intents = direct_query_handler.HANDLERS keys (kept as a literal list so this
# module imports nothing heavy and unit tests run without the app).
INTENTS = {
    "invoice_count":        "how many invoices exist",
    "total_revenue":        "total revenue / sales / collection-rate breakdown",
    "revenue_month_detail": "revenue in one specific month (needs `month`)",
    "overdue_list":         "list overdue invoices",
    "overdue_amount":       "total amount overdue",
    "overdue_range_detail": "overdue invoices in an aging range (needs `days_range`)",
    "pending_list":         "list pending (not yet due) invoices",
    "top_debtors":          "customers ranked by amount they owe",
    "top_customers":        "customers ranked by revenue",
    "inventory_count":      "how many products are tracked",
    "low_stock":            "products low on stock / needing reorder",
    "expiring_soon":        "products expiring soon",
    "client_summary":       "one customer's account summary (needs `customer`)",
    "customer_invoices":    "all invoices of one customer (needs `customer`)",
    "invoice_detail":       "one specific invoice (needs `invoice_id`)",
    "product_performance":  "which products sell best/worst",
    "profit_summary":       "profit / margins overview",
    "sales_growth":         "revenue growth / trend over time",
    "dso_summary":          "days-sales-outstanding / collection speed",
    "dormant_customers":    "customers who stopped buying",
    "customer_margins":     "profitability per customer",
    "business_summary":     "whole-business overview snapshot",
}

# Gated actions (services/actions.py ACTIONS registry).
ACTIONS = (
    "send_payment_reminders",
    "mark_invoice_paid",
    "email_reminder_digest",
    "escalate_overdue",
    "draft_reorder_po",
)

MODES = ("answer", "advise", "act", "analyze", "chat")

_ENTITY_KEYS = ("customer", "invoice_id", "limit", "days_range", "month")


# ── Decision object ──────────────────────────────────────────────────────────

@dataclass
class RouteDecision:
    mode:       str
    intent:     Optional[str] = None
    action:     Optional[str] = None
    entities:   dict = field(default_factory=dict)
    confidence: float = 0.0

    @property
    def tier(self) -> str:
        """Map (mode, intent) onto the pipeline's tier vocabulary."""
        if self.mode == "chat":
            return "CONVERSATIONAL"
        if self.mode == "analyze":
            return "AI_COMPLEX"
        if self.mode == "act":
            return "ACTION"            # gated preview→confirm, NEVER auto-executed
        if self.mode == "advise":
            return "AI_ADVISE"         # handler data + grounded advice pass
        return "DIRECT" if self.intent else "AI_SIMPLE"

    @property
    def handler_key(self) -> Optional[str]:
        """The DB handler that supplies data (also grounds 'advise' answers)."""
        return self.intent


# ── Prompt ───────────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    intent_lines = "\n".join(f"  {k}: {v}" for k, v in INTENTS.items())
    actions = ", ".join(ACTIONS)
    return (
        "You are the query router for BizAssist, a business assistant. "
        "Classify the user's message. Respond with ONLY this JSON:\n"
        '{"mode": "answer|advise|act|analyze|chat", "intent": "<intent or null>", '
        '"action": "<action or null>", "entities": {"customer": null, "invoice_id": null, '
        '"limit": null, "days_range": null, "month": null}, "confidence": 0.0}\n\n'
        "MODES — what the user wants BACK:\n"
        "  answer  → they want the data itself (show/list/how many/what is)\n"
        "  advise  → they want suggestions/recommendations/how-to ABOUT their data "
        "(suggest, recommend, how do I, what should I, offers, ideas, tips)\n"
        "  act     → they want the SYSTEM TO DO something (send, escalate, remind, "
        "mark paid, email, create PO). Choose `action` from: " + actions + "\n"
        "  analyze → multi-step diagnosis or planning (diagnose, root cause, "
        "growth plan, deep analysis, compare periods, strategy)\n"
        "  chat    → greetings, thanks, small talk\n\n"
        "INTENTS (the data domain; set for answer AND advise; null if none fits):\n"
        + intent_lines + "\n\n"
        "ENTITIES — extract ONLY what is literally in the message (hints; the "
        "database resolves them): customer = business/shop name mentioned; "
        "invoice_id = codes like INV-0042; limit = 'top 5' → 5; days_range = "
        "'90+ days' → '90+', '31-60 days' → '31-60'; month = 'Mar 26' → '2026-03'.\n\n"
        "RULES:\n"
        "- 'Suggest/recommend/how to … <topic>' is advise with that topic's intent, "
        "NOT answer. 'Draft a plan' is analyze. 'Draft a reminder message' is act.\n"
        "- An invoice code (INV-xxxx) means intent invoice_detail, even if a "
        "customer is also named.\n"
        "- NEVER invent entities. Unsure about mode → answer. Unsure about "
        "intent → null. confidence is YOUR certainty, 0.0-1.0.\n"
        "- Output raw JSON only — no markdown, no explanation."
    )


_SYSTEM = _build_system_prompt()


# ── Core classify ────────────────────────────────────────────────────────────

def _validated(raw: dict) -> Optional[RouteDecision]:
    """Coerce model output into a safe RouteDecision (enum-checked)."""
    if not isinstance(raw, dict):
        return None
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in MODES:
        return None
    intent = raw.get("intent")
    intent = intent if intent in INTENTS else None
    action = raw.get("action")
    action = action if action in ACTIONS else None
    if mode == "act" and action is None:
        # An act with no recognised action is unsafe to act on → treat as advise
        # so the user gets guidance instead of a hallucinated "Done."
        mode = "advise"
    ents_in = raw.get("entities") or {}
    entities = {}
    if isinstance(ents_in, dict):
        for k in _ENTITY_KEYS:
            v = ents_in.get(k)
            if v not in (None, "", "null"):
                entities[k] = v
    try:
        conf = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0
    return RouteDecision(mode=mode, intent=intent, action=action,
                         entities=entities, confidence=conf)


def classify(query: str, client=None, business_id: int = None) -> Optional[RouteDecision]:
    """
    One structured 8B call → RouteDecision. Returns None on ANY failure so the
    caller always has the legacy router as fallback. Never raises.
    """
    q = (query or "").strip()
    if not q:
        return None
    try:
        if client is None:
            from groq import Groq
            client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=0.0,
            max_tokens=160,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": q[:500]},
            ],
        )
        if business_id is not None:
            _log_usage(business_id, getattr(resp, "usage", None))
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        logger.debug(f"[ROUTER][llm] raw response: {raw[:300]}")
        decision = _validated(json.loads(raw))
        if decision:
            logger.info(
                f"[ROUTER][llm] mode={decision.mode} intent={decision.intent} "
                f"action={decision.action} entities={decision.entities} "
                f"conf={decision.confidence:.2f} | q='{q[:80]}'"
            )
        return decision
    except Exception as e:
        logger.warning(f"[ROUTER][llm] classify failed (fallback to legacy): {e}")
        return None


def route(query: str, client=None, business_id: int = None):
    """
    Cutover-ready entry point: returns (tier, handler_key, decision) or None.
    Not wired into the pipeline yet — shadow first.
    """
    d = classify(query, client=client, business_id=business_id)
    if d is None:
        return None
    return (d.tier, d.handler_key, d)


# ── Shadow comparison (the only thing ai_router calls today) ─────────────────

def _verdict(d: RouteDecision, legacy_route: str, legacy_handler, legacy_topic) -> str:
    """
    AGREE when both systems would have behaved the same. The interesting cases
    are labelled so analyze_llm_shadow.py can bucket them:
      MODE-UPGRADE   llm found advise/act where legacy could only say answer/AI —
                     the loyalty-offers and 'Escalate → Done.' bug classes.
      DISAGREE       genuinely different routing — needs a human look.
    """
    if d.mode in ("advise", "act"):
        return "MODE-UPGRADE"          # legacy has no vocabulary for these
    if legacy_route == "DIRECT":
        return "AGREE" if d.tier == "DIRECT" and d.intent == legacy_handler else "DISAGREE"
    if legacy_route == d.tier:
        return "AGREE"
    return "DISAGREE"


def shadow_compare(query: str, legacy_route: str, legacy_handler, legacy_topic,
                   business_id: int = None, client=None, sync: bool = False):
    """
    Run the LLM router NEXT TO the legacy decision and log the comparison.
    Routing is untouched. Runs in a daemon thread (zero request latency) unless
    sync=True (tests). Lines are consumed by analyze_llm_shadow.py.
    """
    def _run():
        d = classify(query, client=client, business_id=business_id)
        if d is None:
            logger.info(
                f"[ROUTER][llm-shadow] ERROR | legacy=({legacy_route}, {legacy_handler}, "
                f"topic={legacy_topic}) llm=(unavailable) | q='{(query or '')[:120]}'"
            )
            return
        verdict = _verdict(d, legacy_route, legacy_handler, legacy_topic)
        logger.info(
            f"[ROUTER][llm-shadow] {verdict} | legacy=({legacy_route}, {legacy_handler}, "
            f"topic={legacy_topic}) llm=(mode={d.mode}, intent={d.intent}, "
            f"action={d.action}, entities={json.dumps(d.entities, ensure_ascii=False)}, "
            f"conf={d.confidence:.2f}) | q='{(query or '')[:120]}'"
        )

    if sync:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()


# ── Token accounting (lazy DB import keeps this module light) ────────────────

def _log_usage(business_id: int, usage) -> None:
    ti = getattr(usage, "prompt_tokens", 0) or 0
    to = getattr(usage, "completion_tokens", 0) or 0
    if not (ti or to):
        return
    try:
        from database.db import SessionLocal
        from database.models import TokenUsage
        db = SessionLocal()
        try:
            db.add(TokenUsage(
                business_id=business_id, model=MODEL, model_tier="LLM_ROUTER",
                input_tokens=ti, output_tokens=to, total_tokens=ti + to,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"[ROUTER][llm] usage log skipped: {e}")
