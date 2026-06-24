"""
services/smart_insights.py  —  Business Advisor
===============================================
Turns the throwaway per-answer "insight" bulb into one dedicated, trustworthy
advisor. Two layers, on purpose:

  1. build_snapshot(user_id)  — a 100% DETERMINISTIC picture from the DB across
     collections, customers/concentration, product velocity, profit, and risk.
     Pure SQL, zero tokens, can't hallucinate.

  2. generate_insights(user_id) — feeds that snapshot to the 70B model with a
     grounded growth-advisor prompt. The model only REASONS over the real
     numbers and must cite them; it never invents figures. Falls back to a
     deterministic headline if the model is unavailable.

Design for trust: the heavy reasoning is pull-only (called from the on-demand
chip), every recommendation cites a real number, and a thin-data business is
told so rather than fed invented advice.
"""
import os
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, Inventory
from services.dates import parse_date

logger = logging.getLogger("bizassist.smart_insights")

MODEL_COMPLEX = os.getenv("GROQ_MODEL_COMPLEX", "llama-3.3-70b-versatile")


def _sf(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except Exception:
        return 0.0


# ── Layer 1: deterministic snapshot ─────────────────────────────────────────

def build_snapshot(user_id: int) -> dict:
    """A real, SQL-only picture of the business. Never guesses."""
    db = SessionLocal()
    snap: dict = {"has_data": False}
    try:
        invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()
        if not invoices:
            return snap
        snap["has_data"] = True
        now = datetime.now()

        total = sum(_sf(i.amount) for i in invoices)
        paid  = sum(_sf(i.amount) for i in invoices if i.status == "Paid")
        over  = [i for i in invoices if i.status == "Overdue"]
        pend  = [i for i in invoices if i.status == "Pending"]
        over_amt = sum(_sf(i.amount) for i in over)

        snap["collections"] = {
            "total_revenue":   round(total),
            "collected":       round(paid),
            "collection_rate": round((paid / total) * 100) if total else 0,
            "overdue_amount":  round(over_amt),
            "overdue_count":   len(over),
            "pending_amount":  round(sum(_sf(i.amount) for i in pend)),
            "pending_count":   len(pend),
        }

        # Aging of overdue (bad-debt risk lives in the long buckets).
        buckets = {"0_30": 0.0, "31_90": 0.0, "91_180": 0.0, "180_plus": 0.0}
        for i in over:
            due = parse_date(i.due_date)
            days = (now - due).days if due else 0
            amt = _sf(i.amount)
            if days <= 30:    buckets["0_30"] += amt
            elif days <= 90:  buckets["31_90"] += amt
            elif days <= 180: buckets["91_180"] += amt
            else:             buckets["180_plus"] += amt
        snap["overdue_aging"] = {k: round(v) for k, v in buckets.items()}

        # Top debtors.
        debt: dict = {}
        for i in over:
            debt[i.customer] = debt.get(i.customer, 0.0) + _sf(i.amount)
        snap["top_debtors"] = [
            {"customer": c, "overdue": round(a)}
            for c, a in sorted(debt.items(), key=lambda x: -x[1])[:5]
        ]

        # Customers + concentration risk.
        cust: dict = {}
        for i in invoices:
            cust[i.customer] = cust.get(i.customer, 0.0) + _sf(i.amount)
        ranked = sorted(cust.items(), key=lambda x: -x[1])
        snap["customers"] = {
            "count": len(cust),
            "top": [{"customer": c, "revenue": round(a)} for c, a in ranked[:5]],
            "top_concentration_pct": round((ranked[0][1] / total) * 100) if total and ranked else 0,
        }

        # Product velocity — fast movers by billed value; dead stock = in stock
        # but never invoiced.
        prod: dict = {}
        for i in invoices:
            p = getattr(i, "product", None)
            if p:
                prod[p] = prod.get(p, 0.0) + _sf(i.amount)
        snap["products"] = {
            "fast_movers": [{"product": p, "billed": round(a)}
                            for p, a in sorted(prod.items(), key=lambda x: -x[1])[:5]],
        }

        # Inventory risk.
        items = db.query(Inventory).filter(Inventory.business_id == user_id).all()
        sold = set(prod.keys())
        dead, low, expiring = [], 0, []
        for it in items:
            stock = int(it.stock) if str(it.stock or "").strip().isdigit() else None
            if stock is not None and stock <= 10:
                low += 1
            exp = parse_date(it.expiry_date)
            if exp is not None and 0 <= (exp - now).days <= 30:
                expiring.append({"product": it.product_name, "days": (exp - now).days,
                                 "stock": stock})
            if it.product_name and it.product_name not in sold and (stock or 0) > 0:
                dead.append({"product": it.product_name, "stock": stock})
        snap["products"]["dead_stock"] = dead[:5]
        snap["risk"] = {
            "low_stock_items":   low,
            "expiring_30d":      sorted(expiring, key=lambda x: x["days"])[:5],
            "bad_debt_180plus":  snap["overdue_aging"]["180_plus"],
        }
        return snap
    except Exception as e:
        logger.error("[ADVISOR] build_snapshot failed: %s", e, exc_info=True)
        return snap
    finally:
        db.close()


# ── Panel split: deterministic positives / improvements (free, always-on) ───

def build_panel_insights(user_id: int) -> dict:
    """
    A model-free 'what's working / could be better' split for the always-visible
    right pane. Pure snapshot math — instant, free, and impossible to hallucinate.
    Returns {has_data, positives: [...], improvements: [...]}.
    """
    snap = build_snapshot(user_id)
    if not snap.get("has_data"):
        return {"has_data": False, "positives": [], "improvements": []}

    c = snap["collections"]
    cust = snap["customers"]
    prods = snap["products"]
    risk = snap["risk"]
    pos, imp = [], []

    def _inr(n):
        return f"₹{int(n):,}"

    # ── Strengths ──
    if c["collection_rate"] >= 60:
        pos.append({"title": "Healthy collections",
                    "detail": f"{c['collection_rate']}% of {_inr(c['total_revenue'])} billed is collected.",
                    "dimension": "collections"})
    if prods.get("fast_movers"):
        f = prods["fast_movers"][0]
        pos.append({"title": "Top-selling product",
                    "detail": f"{f['product']} leads at {_inr(f['billed'])} billed.",
                    "dimension": "products"})
    if cust.get("top") and cust["top_concentration_pct"] < 50:
        t = cust["top"][0]
        pos.append({"title": "Strong customer base",
                    "detail": f"{t['customer']} is your top account ({_inr(t['revenue'])}), with healthy spread across {cust['count']} customers.",
                    "dimension": "customers"})
    if c["pending_count"] == 0 and c["overdue_count"] == 0:
        pos.append({"title": "Nothing outstanding",
                    "detail": "No pending or overdue invoices — fully collected.",
                    "dimension": "collections"})

    # ── Improvements ──
    if c["overdue_amount"] > 0:
        imp.append({"title": "Overdue cash to collect",
                    "detail": f"{_inr(c['overdue_amount'])} overdue across {c['overdue_count']} invoices.",
                    "action": "Chase top debtors first.", "dimension": "collections"})
    if risk["bad_debt_180plus"] > 0:
        imp.append({"title": "Ageing bad-debt risk",
                    "detail": f"{_inr(risk['bad_debt_180plus'])} is 180+ days overdue.",
                    "action": "Escalate or set a payment plan.", "dimension": "risk"})
    if cust.get("top") and cust["top_concentration_pct"] >= 50:
        imp.append({"title": "Customer concentration risk",
                    "detail": f"{cust['top_concentration_pct']}% of revenue rides on {cust['top'][0]['customer']}.",
                    "action": "Grow other accounts to diversify.", "dimension": "risk"})
    if prods.get("dead_stock"):
        imp.append({"title": "Dead stock tying up cash",
                    "detail": f"{len(prods['dead_stock'])} product(s) in stock but never sold (e.g. {prods['dead_stock'][0]['product']}).",
                    "action": "Discount or bundle to clear.", "dimension": "products"})
    if risk["expiring_30d"]:
        e = risk["expiring_30d"][0]
        imp.append({"title": "Stock expiring soon",
                    "detail": f"{len(risk['expiring_30d'])} item(s) expire within 30 days (e.g. {e['product']} in {e['days']}d).",
                    "action": "Promote before it spoils.", "dimension": "products"})
    if risk["low_stock_items"] > 0:
        imp.append({"title": "Low stock",
                    "detail": f"{risk['low_stock_items']} product(s) at/under 10 units.",
                    "action": "Reorder fast movers first.", "dimension": "products"})

    return {"has_data": True, "positives": pos, "improvements": imp}


# ── Query-contextual insight (deterministic, scoped to one answer) ──────────

def _inr(n) -> str:
    return f"₹{int(round(_sf(n))):,}"


def contextual_insight(user_id: int, handler_key: str, snap: dict = None) -> dict:
    """
    ONE small, GROUNDED insight scoped to the topic the user just asked about —
    the trustworthy successor to the old per-answer bulb. Pure snapshot math (no
    LLM, can't hallucinate). Returns {"text": str, "dimension": str} or None.

    Returns None when there's nothing useful/relevant to add, or for
    customer-specific answers (client_summary / customer_invoices /
    invoice_detail) — the business-wide snapshot would mismatch a single
    customer's view, so we stay silent rather than risk a confusing aside.
    """
    if handler_key in ("client_summary", "customer_invoices", "invoice_detail",
                        "business_summary"):
        return None

    snap = snap or build_snapshot(user_id)
    if not snap.get("has_data"):
        return None

    c     = snap.get("collections", {})
    cust  = snap.get("customers", {})
    prods = snap.get("products", {})
    risk  = snap.get("risk", {})
    debtors = snap.get("top_debtors", [])
    aging   = snap.get("overdue_aging", {})

    def _ins(text, dim):
        return {"text": text, "dimension": dim}

    # ── Collections / receivables ────────────────────────────────────────
    if handler_key in ("overdue_list", "overdue_amount", "top_debtors"):
        if debtors:
            top = debtors[0]
            bad = aging.get("180_plus", 0)
            tail = f" {_inr(bad)} of it is 180+ days overdue — escalate that first." if bad > 0 else ""
            return _ins(
                f"{top['customer']} is your biggest debtor at {_inr(top['overdue'])} "
                f"of {_inr(c.get('overdue_amount', 0))} total overdue.{tail}",
                "collections")
        return None

    if handler_key == "pending_list":
        if c.get("pending_amount", 0) > 0:
            return _ins(
                f"{_inr(c['pending_amount'])} is pending across {c.get('pending_count', 0)} "
                f"invoice(s) — send these before they tip into overdue.",
                "collections")
        return None

    if handler_key in ("total_revenue", "invoice_count"):
        if c.get("overdue_amount", 0) > 0:
            return _ins(
                f"You've collected {c.get('collection_rate', 0)}% of {_inr(c.get('total_revenue', 0))} billed; "
                f"{_inr(c['overdue_amount'])} is still overdue to chase.",
                "collections")
        return None

    if handler_key == "dso_summary":
        if c.get("overdue_amount", 0) > 0 and debtors:
            return _ins(
                f"Most of the drag is {debtors[0]['customer']} ({_inr(debtors[0]['overdue'])} overdue) — "
                f"collecting from the top debtors moves this number fastest.",
                "collections")
        return None

    # ── Customers ────────────────────────────────────────────────────────
    if handler_key in ("top_customers", "customer_margins"):
        if cust.get("top"):
            conc = cust.get("top_concentration_pct", 0)
            risk_tail = " — that's heavy concentration; grow other accounts to de-risk." if conc >= 40 else "."
            return _ins(
                f"{cust['top'][0]['customer']} alone is {conc}% of revenue{risk_tail}",
                "customers")
        return None

    if handler_key == "dormant_customers":
        if cust.get("top"):
            return _ins(
                f"Win-backs are worth it: your top account {cust['top'][0]['customer']} "
                f"is {_inr(cust['top'][0]['revenue'])} of lifetime value — a lapsed one of that size hurts.",
                "customers")
        return None

    # ── Products / inventory ─────────────────────────────────────────────
    if handler_key in ("product_performance", "profit_summary"):
        dead = prods.get("dead_stock", [])
        if dead:
            return _ins(
                f"{len(dead)} product(s) sit in stock but have never sold (e.g. {dead[0]['product']}) — "
                f"discount or bundle to free up cash.",
                "products")
        if prods.get("fast_movers"):
            f = prods["fast_movers"][0]
            return _ins(f"{f['product']} is your top line at {_inr(f['billed'])} billed — keep it stocked.",
                        "products")
        return None

    if handler_key == "low_stock":
        if prods.get("fast_movers"):
            return _ins(
                f"Prioritise reordering fast movers like {prods['fast_movers'][0]['product']} "
                f"({_inr(prods['fast_movers'][0]['billed'])} billed) over slow stock.",
                "products")
        return None

    if handler_key == "expiring_soon":
        exp = risk.get("expiring_30d", [])
        if exp:
            return _ins(
                f"{exp[0]['product']} expires in {exp[0]['days']}d — promote or discount it now to avoid a write-off.",
                "products")
        return None

    if handler_key == "inventory_count":
        dead = prods.get("dead_stock", [])
        if dead:
            return _ins(
                f"{len(dead)} of these have never sold (e.g. {dead[0]['product']}) — that's cash tied up in dead stock.",
                "products")
        return None

    if handler_key == "sales_growth":
        if cust.get("top"):
            return _ins(
                f"Your top account {cust['top'][0]['customer']} ({_inr(cust['top'][0]['revenue'])}) drives much of this — "
                f"a second account that size would meaningfully lift growth.",
                "customers")
        return None

    return None


# ── Layer 2: grounded advisor (70B) ─────────────────────────────────────────

_ADVISOR_SYSTEM = (
    "You are a sharp business growth advisor for a distributor, wholesaler, or small business. "
    "You are given the owner's REAL business data as JSON. Give a BALANCED read:\n"
    "- 2-3 STRENGTHS (polarity 'positive') — what's working well, worth reinforcing "
    "(e.g. a strong collection rate, a top-selling product, a loyal high-value customer).\n"
    "- 3-4 IMPROVEMENTS (polarity 'improve') — what could be better, to grow revenue, "
    "collect cash faster, sell stock faster, lift profit, or cut risk.\n\n"
    "HARD RULES (trust depends on these):\n"
    "- Use ONLY numbers present in the JSON. NEVER invent figures, customers, or products.\n"
    "- Every item must cite the exact ₹ figure or count from the data that motivates it.\n"
    "- Be specific: name the customer / product / bucket and the concrete move.\n"
    "- For a STRENGTH, the 'action' is how to LEVERAGE it; for an IMPROVEMENT, how to FIX it.\n"
    "- Order improvements by impact (biggest cash / risk first).\n"
    "- If data is too thin for a point, skip it — do not pad. Use ₹, never $.\n\n"
    "Return STRICT JSON: {\"insights\": [{\"title\": str, \"insight\": str, \"action\": str, "
    "\"impact\": str, \"dimension\": one of [collections, customers, products, profit, risk], "
    "\"polarity\": one of [positive, improve]}]}"
)


def _deterministic_headline(snap: dict) -> list:
    """A safe, model-free fallback so the feature never shows nothing/garbage."""
    if not snap.get("has_data"):
        return []
    c = snap["collections"]
    out = []
    # Strength: a healthy collection rate, or the top product.
    if c["collection_rate"] >= 60:
        out.append({
            "title": "Healthy collections",
            "insight": f"You've collected {c['collection_rate']}% of ₹{c['total_revenue']:,} billed.",
            "action": "Keep the follow-up cadence that's working.",
            "impact": "Stable cash flow.",
            "dimension": "collections", "polarity": "positive",
        })
    fast = (snap.get("products") or {}).get("fast_movers") or []
    if fast:
        out.append({
            "title": "Top-selling product",
            "insight": f"{fast[0]['product']} is your top mover at ₹{fast[0]['billed']:,} billed.",
            "action": "Keep it well stocked and lead with it.",
            "impact": "Protects your biggest revenue line.",
            "dimension": "products", "polarity": "positive",
        })
    # Improvement: overdue cash.
    if c["overdue_amount"] > 0:
        out.append({
            "title": "Collect your overdue cash",
            "insight": f"₹{c['overdue_amount']:,} is overdue across {c['overdue_count']} invoices "
                       f"(collection rate {c['collection_rate']}%).",
            "action": "Start with the top debtors and send reminders this week.",
            "impact": "Directly improves cash flow.",
            "dimension": "collections", "polarity": "improve",
        })
    return out


def generate_insights(user_id: int, client=None) -> dict:
    """
    Returns {"insights": [...], "snapshot": {...}, "source": "ai"|"deterministic"}.
    Grounded: the model only reasons over build_snapshot's real numbers.
    """
    snap = build_snapshot(user_id)
    if not snap.get("has_data"):
        return {"insights": [], "snapshot": snap, "source": "empty",
                "message": "Upload some invoices and inventory to get tailored growth insights."}

    if client is None:
        try:
            from groq import Groq
            client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        except Exception as e:
            logger.warning("[ADVISOR] no Groq client: %s", e)
            return {"insights": _deterministic_headline(snap), "snapshot": snap, "source": "deterministic"}

    try:
        resp = client.chat.completions.create(
            model=MODEL_COMPLEX,
            temperature=0.3,
            max_tokens=900,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _ADVISOR_SYSTEM},
                {"role": "user", "content": "BUSINESS DATA (JSON):\n" + json.dumps(snap, ensure_ascii=False)},
            ],
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        insights = data.get("insights") or []
        if not insights:
            insights = _deterministic_headline(snap)
            return {"insights": insights, "snapshot": snap, "source": "deterministic"}
        return {"insights": insights, "snapshot": snap, "source": "ai"}
    except Exception as e:
        logger.error("[ADVISOR] generate_insights failed: %s", e, exc_info=True)
        return {"insights": _deterministic_headline(snap), "snapshot": snap, "source": "deterministic"}
