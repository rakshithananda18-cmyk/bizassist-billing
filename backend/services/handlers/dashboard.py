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
        total_rev  = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id).scalar() or 0
        inv_count  = db.query(Invoice).filter(Invoice.business_id == user_id).count()
        paid_amt   = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Paid").scalar()    or 0
        overdue_amt= db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").scalar() or 0
        pending_ct = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Pending").count()
        inv_items  = db.query(Inventory).filter(Inventory.business_id == user_id).count()

        top = (
            db.query(Invoice.customer, func.sum(Invoice.amount).label("total_amount"))
            .filter(Invoice.business_id == user_id)
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .first()
        )

        collection_rate = round((paid_amt / total_rev) * 100) if total_rev else 0

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
