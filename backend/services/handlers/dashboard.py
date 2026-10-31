"""
dashboard.py  —  Dashboard & Summary Handlers
Domain handler for BizAssist Tier-0 intent engine.

Each function takes (user_id, ...) and returns a formatted markdown string
ready to send to the frontend. Returns None on DB error (caller falls through to AI).

To add a new handler:
  1. Add a function here
  2. Register it in services/direct_query_handler.py HANDLERS dict
  3. Add intent mapping in services/intents.py INTENT_MAP
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, Inventory

logger = logging.getLogger("bizassist.handlers.dashboard")

def _business_summary(user_id: int) -> str:
    db = SessionLocal()
    try:
        from core.billing.balances import business_revenue_summary
        metrics = business_revenue_summary(db, user_id)
        total_rev = metrics["net_revenue"]
        paid_amt = metrics["collected_revenue"]
        overdue_amt = metrics["overdue_revenue"]
        pending_ct = metrics["pending_invoice_count"]
        collection_rate = metrics["collection_rate_pct"]
        inv_count = db.query(Invoice).filter(Invoice.business_id == user_id, func.coalesce(Invoice.invoice_type, "") != "credit_note").count()
        inv_items = db.query(Inventory).filter(Inventory.business_id == user_id).count()

        from core.billing.balances import customer_revenue_rows
        ranked = customer_revenue_rows(db, user_id)
        top = ranked[0] if ranked else None

        return (
            f"**Business Snapshot**\n\n"
            f"**Revenue**\n"
            f"- Total       : ₹{total_rev:,.0f}\n"
            f"- Collected   : ₹{paid_amt:,.0f}  ({collection_rate}% rate)\n"
            f"- Overdue     : ₹{overdue_amt:,.0f}\n\n"
            f"**Invoices**\n"
            f"- Total       : {inv_count}\n"
            f"- Pending     : {pending_ct}\n\n"
            f"**Inventory**\n"
            f"- Products tracked : {inv_items}\n\n"
            f"**Top Customer**\n"
            f"- {top.customer} — ₹{top.total_amount:,.0f}" if top else ""
        )
    finally:
        db.close()
