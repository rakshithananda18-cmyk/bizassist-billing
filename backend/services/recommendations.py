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

logger = logging.getLogger("bizassist.recommendations")


# ── Suggestion factory helpers ──────────────────────────────────────
def det(id, label, intent, icon="chart"):
    return {"id": id, "label": label, "type": "deterministic", "intent": intent, "icon": icon}

def ai(id, label, prompt, icon="chat"):
    return {"id": id, "label": label, "type": "ai", "prompt": prompt, "icon": icon}

def action(id, label, action_key, icon="bell"):
    return {"id": id, "label": label, "type": "action", "action": action_key, "confirm": True, "icon": icon}


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
        return {"overdue": overdue, "pending": pending, "low_stock": low_stock}
    except Exception as e:
        logger.error(f"signals() failed: {e}", exc_info=True)
        return {"overdue": 0, "pending": 0, "low_stock": 0}
    finally:
        db.close()


# ── Per-intent recommendation rules ─────────────────────────────────
# Each value: fn(signals) -> list[suggestion]
RECS = {
    "overdue_list": lambda s: [
        action("send_reminders", "Send reminders", "send_payment_reminders", "bell"),
        ai("recovery", "Recovery plan", "Draft a polite, prioritized plan to recover my overdue invoices."),
        det("top_debtors", "Top debtors", "top_customers", "trophy"),
    ],
    "overdue_amount": lambda s: [
        det("overdue_list", "See overdue list", "overdue_list", "alert"),
        action("send_reminders", "Send reminders", "send_payment_reminders", "bell"),
        ai("recovery", "Recovery plan", "Draft a polite, prioritized plan to recover my overdue invoices."),
    ],
    "pending_list": lambda s: [
        ai("followup", "Follow-up tips", "Suggest how to convert my pending invoices into payments faster."),
    ],
    "total_revenue": lambda s: [
        det("pending", "Pending invoices", "pending_list", "clock"),
        det("top_customers", "Top customers", "top_customers", "trophy"),
        ai("growth", "Growth ideas", "Give me 3 concrete ways to grow revenue based on my data."),
    ],
    "revenue_summary": lambda s: [
        det("pending", "Pending invoices", "pending_list", "clock"),
        det("top_customers", "Top customers", "top_customers", "trophy"),
        ai("growth", "Growth ideas", "Give me 3 concrete ways to grow revenue based on my data."),
    ],
    "top_debtors": lambda s: [
        action("send_reminders", "Send reminders", "send_payment_reminders", "bell"),
        det("overdue", "Overdue list", "overdue_list", "alert"),
        ai("recovery", "Recovery plan", "Draft a polite, prioritized plan to recover my overdue invoices."),
    ],
    "top_customers": lambda s: [
        ai("retain", "Retention ideas", "Suggest loyalty/retention offers for my top customers."),
    ],
    "low_stock": lambda s: [
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
    if s["overdue"] > 0 and intent_key not in ("overdue_list", "overdue_amount", "client_summary"):
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
