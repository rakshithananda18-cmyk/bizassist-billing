"""
recommendations.py — Tier 1 of the agentic engine.

Rule-based "next step" suggestions returned with every answer. ZERO AI tokens —
pure rules over the business data. The frontend renders these as chips in the
chip bar; each suggestion is typed:

    deterministic -> calls another /intent (0 tokens)
    ai            -> sends a prompt to the AI assistant
    action        -> runs a gated action (added in Phase 3)

Add a capability by adding an entry to RECS — no other code changes needed.
"""
import logging
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, Inventory
from services.dates import parse_date

logger = logging.getLogger("bizassist.recommendations")


# ── Suggestion factory helpers ──────────────────────────────────────
def det(id, label, intent, icon="chart"):
    return {"id": id, "label": label, "type": "deterministic", "intent": intent, "icon": icon}

def ai(id, label, prompt, icon="chat"):
    return {"id": id, "label": label, "type": "ai", "prompt": prompt, "icon": icon}

def action(id, label, action_key, icon="bell"):
    return {"id": id, "label": label, "type": "action", "action": action_key, "confirm": True, "icon": icon}

def select(id, label, action_key, options, icon="bell"):
    """Radio/checkbox selection chip — expands inline for user to pick targets before executing."""
    return {"id": id, "label": label, "type": "select", "action": action_key, "options": options, "icon": icon}


# ── Light business signals (one cheap query, cached per request) ─────
def signals(user_id: int) -> dict:
    db = SessionLocal()
    try:
        overdue = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").count()
        pending = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Pending").count()
        items = db.query(Inventory).filter(Inventory.business_id == user_id).all()
        low_stock = sum(
            1 for i in items
            if i.stock is not None and str(i.stock).isdigit() and int(i.stock) <= 10
        )
        # Collection rate for cashflow emergency detection
        total_rev = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id).scalar() or 0
        paid_rev  = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Paid").scalar() or 0
        collection_rate = round((paid_rev / total_rev) * 100) if total_rev else 100
        # Top overdue customers for select-chip options
        top_overdue_rows = (
            db.query(Invoice.customer, func.sum(Invoice.amount).label("overdue_total"))
            .filter(Invoice.business_id == user_id, Invoice.status == "Overdue")
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .limit(6).all()
        )
        overdue_options = [
            {"value": r.customer, "label": f"{r.customer} (₹{float(r.overdue_total or 0):,.0f})"}
            for r in top_overdue_rows
        ]
        return {
            "overdue": overdue,
            "pending": pending,
            "low_stock": low_stock,
            "collection_rate": collection_rate,
            "overdue_options": overdue_options,
        }
    except Exception as e:
        logger.error(f"[RECS] signals() failed: {e}", exc_info=True)
        return {"overdue": 0, "pending": 0, "low_stock": 0, "collection_rate": 100, "overdue_options": []}
    finally:
        db.close()


# ── Per-intent recommendation rules ─────────────────────────────────
# Each value: fn(signals) -> list[suggestion]
RECS = {
    "overdue_list": lambda s: [
        select("send_reminders", "Send reminders", "send_payment_reminders", s.get("overdue_options", []), "bell") if s.get("overdue_options") else action("send_reminders", "Send reminders", "send_payment_reminders", "bell"),
        action("digest", "Email me the digest", "email_reminder_digest", "bell"),
        action("escalate", "Escalate 90+ days", "escalate_overdue", "alert"),
        ai("recovery", "Recovery plan", "Draft a polite, prioritized plan to recover my overdue invoices."),
        det("top_debtors", "Top debtors", "top_debtors", "trophy"),
    ],
    "overdue_amount": lambda s: [
        det("overdue_list", "See overdue list", "overdue_list", "alert"),
        action("send_reminders", "Send reminders", "send_payment_reminders", "bell"),
        action("digest", "Email me the digest", "email_reminder_digest", "bell"),
        ai("recovery", "Recovery plan", "Draft a polite, prioritized plan to recover my overdue invoices."),
    ],
    "pending_list": lambda s: [
        ai("followup", "Follow-up tips", "Suggest how to convert my pending invoices into payments faster."),
    ],
    "total_revenue": lambda s: [
        det("top_debtors", "Top debtors", "top_debtors", "trophy"),
        det("pending", "Pending invoices", "pending_list", "clock"),
        ai("growth", "Growth ideas", "Give me 3 concrete ways to grow revenue based on my data."),
    ] + ([ai("cashflow_alert", f"⚠ Fix cash flow ({s['collection_rate']}%)", f"My collection rate is {s['collection_rate']}% — diagnose why and give me a step-by-step plan to fix it.", "alert")] if s.get("collection_rate", 100) < 70 else []),
    "revenue_summary": lambda s: [
        det("pending", "Pending invoices", "pending_list", "clock"),
        det("top_customers", "Top customers", "top_customers", "trophy"),
        ai("growth", "Growth ideas", "Give me 3 concrete ways to grow revenue based on my data."),
    ],
    "top_debtors": lambda s: [
        select("send_reminders", "Send reminders", "send_payment_reminders", s.get("overdue_options", []), "bell") if s.get("overdue_options") else action("send_reminders", "Send reminders", "send_payment_reminders", "bell"),
        action("escalate", "Escalate 90+ days", "escalate_overdue", "alert"),
        det("overdue", "Overdue list", "overdue_list", "alert"),
        ai("recovery", "Recovery plan", "Draft a polite, prioritized plan to recover my overdue invoices."),
    ],
    "top_customers": lambda s: [
        ai("retain", "Retention ideas", "Suggest loyalty/retention offers for my top customers."),
    ],
    "low_stock": lambda s: [
        action("reorder_po", "Draft reorder", "draft_reorder_po", "package"),
        det("inventory_count", "Full inventory", "inventory_count", "package"),
        ai("reorder", "Reorder advice", "Recommend reorder quantities and timing for my low-stock products."),
    ],
    "expiring_soon": lambda s: [
        ai("clearance", "Clearance ideas", "Suggest discounts or bundles to clear products expiring soon and reduce waste."),
    ],
    "inventory_count": lambda s: [
        det("low_stock", "Low stock", "low_stock", "package"),
        det("expiring_soon", "Expiring soon", "expiring_soon", "clock"),
    ],
    "business_summary": lambda s: [
        ai("priorities", "Today's priorities", "What are the top 3 things I should act on today, with reasons?"),
    ],
    # Context after a data upload (called with intent_key="upload")
    "upload": lambda s: [
        ai("summary", "Summarize data", "Analyze the uploaded data and give me a concise summary."),
        ai("anomaly", "Check anomalies", "Check the uploaded data for anomalies, duplicates, or risks."),
    ],
}

# Client-specific recommendations (need the customer name from params)
def _client_recs(params: dict) -> list:
    cust = (params or {}).get("customer", "this customer")
    return [
        ai("client_followup", "Follow-up message",
           f"Draft a polite, professional follow-up to {cust} about their outstanding invoices."),
        ai("client_terms", "Payment terms",
           f"Suggest payment terms or incentives to improve {cust}'s payment behaviour."),
        det("top_customers", "Top customers", "top_customers", "trophy"),
    ]


# Global signal-driven suggestions appended when relevant (and not redundant)
def _global(intent_key: str, s: dict) -> list:
    extra = []
    # Cashflow emergency alert — surfaced on ANY answer when collection rate < 70%
    if s.get("collection_rate", 100) < 70 and intent_key not in ("total_revenue", "revenue_summary", "business_summary"):
        rate = s.get("collection_rate", 0)
        extra.append(ai(
            "cashflow_emergency",
            f"⚠ Cash flow: {rate}%",
            f"My collection rate is only {rate}%. Diagnose the root cause and give me a prioritized action plan to improve cash flow this week.",
            "alert"
        ))
    if s["overdue"] > 0 and intent_key not in ("overdue_list", "overdue_amount", "top_debtors", "client_summary"):
        extra.append(det("overdue", "Overdue invoices", "overdue_list", "alert"))
    if s["low_stock"] > 0 and intent_key not in ("low_stock", "inventory_count", "client_summary"):
        extra.append(det("low_stock_g", "Low stock", "low_stock", "package"))
    return extra


def recommend(intent_key: str, user_id: int, params: dict = None) -> list:
    """Return up to 4 next-step suggestions for the given intent."""
    s = signals(user_id)
    if intent_key == "client_summary":
        base = _client_recs(params)
    else:
        fn = RECS.get(intent_key)
        base = fn(s) if fn else []
    combined = base + _global(intent_key, s)
    # de-dup by intent/label and cap at 4
    seen, out = set(), []
    for sug in combined:
        key = sug.get("intent") or sug.get("prompt") or sug.get("label")
        if key in seen:
            continue
        seen.add(key)
        out.append(sug)
    return out[:4]


# ── Business snapshot (compact one-liner for AI context injection) ────
def get_business_snapshot(user_id: int) -> str:
    """
    Compact business health string for AI system prompt injection.
    Grounds every AI response in real current data. ~80 tokens.
    """
    from database.models import Payment
    from datetime import datetime, timedelta
    db = SessionLocal()
    try:
        total_rev   = _sf(db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id).scalar())
        paid_rev    = _sf(db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Paid").scalar())
        overdue_amt = _sf(db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").scalar())
        overdue_ct  = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").count()
        pending_ct  = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Pending").count()
        collection  = round((paid_rev / total_rev) * 100) if total_rev else 100
        items       = db.query(Inventory).filter(Inventory.business_id == user_id).all()
        low_stock   = sum(1 for i in items if i.stock is not None and str(i.stock).isdigit() and int(i.stock) <= 10)
        expiring_7d = 0
        for item in items:
            exp = parse_date(item.expiry_date)
            if exp is not None and exp <= datetime.now() + timedelta(days=7):
                expiring_7d += 1
        parts = [
            f"Revenue: Rs.{total_rev:,.0f}",
            f"Collected: {collection}%",
            f"Overdue: Rs.{overdue_amt:,.0f} ({overdue_ct} invoices)",
            f"Pending: {pending_ct} invoices",
        ]
        if low_stock:   parts.append(f"Low stock: {low_stock} items")
        if expiring_7d: parts.append(f"Expiring in 7d: {expiring_7d} items")
        snapshot = "[Live Business Data] " + " | ".join(parts)

        # Inject durable memory facts (Phase 4)
        try:
            from services.memory_service import get_business_facts
            facts = get_business_facts(user_id)
            if facts:
                snapshot = snapshot + "\n" + facts
        except Exception as mem_err:
            logger.debug(f"[RECS] memory injection skipped: {mem_err}")

        return snapshot
    except Exception as e:
        logger.error("[RECS] get_business_snapshot failed: %s", e)
        return ""
    finally:
        db.close()


# ── Anomaly detector (0 tokens, pure DB) ─────────────────────────────
def _sf(v):
    """Safe float conversion for SQLAlchemy scalar results."""
    try: return float(v) if v is not None else 0.0
    except: return 0.0

def detect_anomalies(user_id: int) -> list:
    """
    Detects business anomalies — zero AI tokens.
    Returns list of alert dicts: {type, severity, label, message, icon}
    """
    from datetime import datetime, timedelta
    db = SessionLocal()
    alerts = []
    try:
        total_rev = _sf(db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id).scalar())
        paid_rev  = _sf(db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Paid").scalar())
        if total_rev > 0:
            rate = round((paid_rev / total_rev) * 100)
            if rate < 60:
                alerts.append({"type": "cashflow", "severity": "critical",
                    "label": f"Cash flow risk: {rate}% collected",
                    "message": f"Only {rate}% of revenue collected. Immediate follow-up needed.",
                    "icon": "alert"})

        overdue_total = _sf(db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").scalar())
        if overdue_total > 0:
            top = (db.query(Invoice.customer, func.sum(Invoice.amount).label("t"))
                   .filter(Invoice.business_id == user_id, Invoice.status == "Overdue")
                   .group_by(Invoice.customer).order_by(func.sum(Invoice.amount).desc()).first())
            if top and top.t and (_sf(top.t) / overdue_total) > 0.6:
                pct = round((_sf(top.t) / overdue_total) * 100)
                alerts.append({"type": "concentration", "severity": "warning",
                    "label": f"{top.customer}: {pct}% of overdue",
                    "message": f"{top.customer} accounts for {pct}% of all overdue. High concentration risk.",
                    "icon": "alert"})

        items = db.query(Inventory).filter(Inventory.business_id == user_id).all()
        critical_expiry = []
        for item in items:
            exp = parse_date(item.expiry_date)
            if exp is None:
                continue
            days = (exp - datetime.now()).days
            if 0 <= days <= 7:
                critical_expiry.append((item.product_name, days))
        if critical_expiry:
            names = ", ".join(f"{n}({d}d)" for n, d in critical_expiry[:3])
            alerts.append({"type": "expiry", "severity": "warning",
                "label": f"{len(critical_expiry)} item(s) expiring this week",
                "message": f"Critical expiry: {names}{'...' if len(critical_expiry) > 3 else ''}",
                "icon": "clock"})

        zero_stock = [i.product_name for i in items if str(i.stock or "").strip() in ("0", "")]
        if zero_stock:
            alerts.append({"type": "stock_out", "severity": "critical",
                "label": f"{len(zero_stock)} item(s) out of stock",
                "message": f"Out of stock: {', '.join(zero_stock[:3])}{'...' if len(zero_stock) > 3 else ''}",
                "icon": "package"})
    except Exception as e:
        logger.error("[RECS] detect_anomalies failed: %s", e)
    finally:
        db.close()
    return alerts
