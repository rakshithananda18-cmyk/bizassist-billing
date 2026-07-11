"""
services/memory_service.py
==========================
Phase 4 — Proactive Memory Distillation.

Extracts durable business facts from live data + chat history using a
lightweight Groq LLM call, then upserts them into the BusinessFact table.
These facts are injected into every downstream LLM prompt under [Durable
Memories] so the AI advisor has long-term, personalised business knowledge.

Public API
----------
  distill_memory(business_id)  -> None        (background job)
  get_business_facts(business_id) -> str       (prompt injection)
"""

import json
import logging
import re
from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from database.db import SessionLocal
from database.models import BusinessFact, ChatMessage, Invoice, Inventory
from sqlalchemy import func
from services.groq_client import make_groq_client

logger = logging.getLogger("bizassist.memory")

# ── Groq client (reuses existing API key via env; timeout via groq_client) ───
import os
_groq = make_groq_client(os.environ.get("GROQ_API_KEY", ""))
_MODEL = os.environ.get("GROQ_MODEL_SIMPLE", "meta-llama/llama-4-scout-17b-16e-instruct")


# ── Prompt ───────────────────────────────────────────────────────────────────
_SYSTEM = """You are a business analyst AI. Your job is to extract STABLE, RECURRING business
facts from the snapshot and chat history provided. These facts will be stored as long-term
memory and used to personalise future advice.

Rules:
- Extract DURABLE PATTERNS, not point-in-time snapshots. The exact figures below
  change constantly; a fact stating today's exact rupee total or today's exact
  percentage is STALE within days and is NOT useful long-term memory.
- PREFER relative, behavioural, structural insights that stay true over time, e.g.
  "Daily Needs Store is consistently one of the largest overdue accounts",
  "collection rate tends to sit around the low-50s%", "Milk Powder 500g is a
  recurring low-stock risk", "revenue is concentrated in a handful of customers".
- AVOID facts that are just a current number, e.g. "total revenue is Rs.37,71,970"
  or "overdue is Rs.1,72,914" — the AI already reads live numbers from the database
  on every answer, so storing a frozen number adds no value and can mislead later.
- Only extract STABLE patterns, NOT one-time events.
- Each fact must be a single, clear, actionable English sentence.
- Use the category codes: payment_delay | sales_pattern | concentration_risk | cash_flow | inventory_risk | other
- Generate a short snake_case fact_key (max 6 words, no spaces).
- Set confidence honestly: a clear, repeatedly-evidenced pattern is high (0.8-1.0);
  a tentative or single-signal inference is low (0.4-0.6).
- The database snapshot is the absolute ground truth for the patterns you infer. If the chat history contains numbers, rates, or claims that contradict the database snapshot, prioritize the snapshot and discard the chat history's contradictory numbers.
- Do not conflate "collection rate" (the percentage of total revenue collected) with "overdue rate" (the percentage of revenue that is overdue).
- Output ONLY a valid JSON object with a "facts" key containing the list of facts. No explanation. No markdown.

Example output:
{
  "facts": [
    {"fact_key": "late_payer_star_bazaar", "category": "payment_delay", "fact_text": "Star Bazaar consistently pays 30–45 days late despite a 30-day net term.", "confidence": 0.9},
    {"fact_key": "q4_revenue_spike", "category": "sales_pattern", "fact_text": "Revenue spikes significantly in Q4 (Oct–Dec), likely due to festive season demand.", "confidence": 0.8}
  ]
}
"""


def _build_context(business_id: int, db) -> str:
    """Build a compact business context string for the LLM."""
    lines = [f"[Business ID: {business_id}]", ""]

    # Revenue snapshot
    total_rev   = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == business_id).scalar() or 0
    paid_rev    = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == business_id, Invoice.status == "Paid").scalar() or 0
    overdue_amt = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == business_id, Invoice.status == "Overdue").scalar() or 0
    overdue_ct  = db.query(Invoice).filter(Invoice.business_id == business_id, Invoice.status == "Overdue").count()
    collection  = round((paid_rev / total_rev) * 100) if total_rev else 100

    lines += [
        f"Total Revenue: Rs.{total_rev:,.0f}",
        f"Collection Rate: {collection}%",
        f"Overdue: Rs.{overdue_amt:,.0f} across {overdue_ct} invoices",
        "",
    ]

    # Top overdue customers
    top_overdue = (
        db.query(Invoice.customer, func.sum(Invoice.amount).label("amount_sum"))
        .filter(Invoice.business_id == business_id, Invoice.status == "Overdue")
        .group_by(Invoice.customer)
        .order_by(func.sum(Invoice.amount).desc())
        .limit(5)
        .all()
    )
    if top_overdue:
        lines.append("Top overdue customers:")
        for row in top_overdue:
            lines.append(f"  - {row.customer}: Rs.{float(row.amount_sum or 0):,.0f}")
        lines.append("")

    # Inventory risk
    items = db.query(Inventory).filter(Inventory.business_id == business_id).all()
    low_stock = [i.product_name for i in items if i.stock is not None and str(i.stock).isdigit() and int(i.stock) <= 5]
    if low_stock:
        lines.append(f"Critical low stock: {', '.join(low_stock[:5])}")
        lines.append("")

    # Recent chat history (last 15 messages for context)
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.business_id == business_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(15)
        .all()
    )
    if msgs:
        lines.append("Recent conversation excerpts:")
        for m in reversed(msgs):
            role = "User" if m.role == "user" else "AI"
            snippet = (m.content or "")[:200].replace("\n", " ")
            lines.append(f"  [{role}] {snippet}")
        lines.append("")

    return "\n".join(lines)


def distill_memory(business_id: int) -> None:
    """
    Extract durable business facts for a business via LLM and upsert into
    the BusinessFact table. Called weekly by the scheduler, or on-demand via
    the /alerts/test/memory_distillation endpoint.
    """
    logger.info(f"[MEMORY] Starting distillation for business_id={business_id}")
    db = SessionLocal()
    try:
        context = _build_context(business_id, db)

        response = _groq.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": f"Extract business facts from:\n\n{context}"},
            ],
            temperature=0.2,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or "{}"

        # Strip any markdown fences the model may add
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"[MEMORY] LLM returned invalid JSON: {raw[:200]}")
            return

        if not isinstance(parsed, dict) or "facts" not in parsed:
            logger.warning(f"[MEMORY] LLM did not return a dictionary with 'facts' key. Raw: {raw[:200]}")
            return

        facts = parsed["facts"]
        if not isinstance(facts, list):
            logger.warning("[MEMORY] 'facts' property is not a list.")
            return

        # Replace semantics: a distillation run is a fresh, full snapshot of the
        # CURRENT durable patterns. Clear this business's existing facts first so
        # repeated runs can't accumulate near-duplicates (the 8B invents slightly
        # different fact_keys each run), then insert the new set.
        cleared = (
            db.query(BusinessFact)
            .filter(BusinessFact.business_id == business_id)
            .delete(synchronize_session=False)
        )
        logger.debug(f"[MEMORY] cleared {cleared} prior fact(s) for business_id={business_id} before refresh")

        seen = set()
        added = 0
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            fact_key  = str(fact.get("fact_key",  "")).strip()[:120]
            category  = str(fact.get("category",  "other")).strip()[:60]
            fact_text = str(fact.get("fact_text", "")).strip()
            try:
                confidence = float(fact.get("confidence", 1.0))
            except (TypeError, ValueError):
                confidence = 1.0

            if not fact_key or not fact_text:
                continue

            # In-run dedupe: skip the same sentence repeated within one response.
            norm = fact_text.lower().rstrip(".").strip()
            if norm in seen:
                logger.debug(f"[MEMORY] skip in-run duplicate: '{fact_text}'")
                continue
            seen.add(norm)

            db.add(BusinessFact(
                business_id = business_id,
                fact_key    = fact_key,
                category    = category,
                fact_text   = fact_text,
                confidence  = confidence,
            ))
            added += 1

        db.commit()
        logger.info(f"[MEMORY] Distilled {added} fact(s) for business_id={business_id} (cleared {cleared} prior)")

    except Exception as e:
        logger.error(f"[MEMORY] distill_memory failed for business_id={business_id}: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()


def get_business_facts(business_id: int, min_confidence: float = 0.6) -> str:
    """
    Return a formatted bullet-list of distilled business facts for injection
    into LLM system prompts. Returns empty string if no facts exist yet.
    """
    db = SessionLocal()
    try:
        facts = (
            db.query(BusinessFact)
            .filter(
                BusinessFact.business_id == business_id,
                BusinessFact.confidence  >= min_confidence,
            )
            .order_by(BusinessFact.category, BusinessFact.fact_key)
            .all()
        )
        if not facts:
            return ""

        lines = ["[Durable Business Memories]"]
        for f in facts:
            lines.append(f"  • [{f.category}] {f.fact_text}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[MEMORY] get_business_facts failed: {e}")
        return ""
    finally:
        db.close()
