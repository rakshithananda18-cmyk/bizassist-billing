"""
invoices.py  —  Invoice & Revenue Handlers
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
from database.models import Invoice, Inventory, Payment
from services.dates import parse_date

logger = logging.getLogger("bizassist.handlers.invoices")

def _invoice_count(user_id: int) -> str:
    db = SessionLocal()
    try:
        total   = db.query(Invoice).filter(Invoice.business_id == user_id).count()
        paid    = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Paid").count()
        pending = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Pending").count()
        overdue = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").count()
        return (
            f"**Invoice Summary**\n\n"
            f"- Total invoices : **{total}**\n"
            f"- Paid           : **{paid}**\n"
            f"- Pending        : **{pending}**\n"
            f"- Overdue        : **{overdue}**"
        )
    finally:
        db.close()

def _total_revenue(user_id: int) -> str:
    db = SessionLocal()
    try:
        total    = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id).scalar() or 0
        paid     = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Paid").scalar()    or 0
        pending  = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Pending").scalar() or 0
        overdue  = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").scalar() or 0
        return (
            f"**Revenue Breakdown**\n\n"
            f"- Total revenue  : **₹{total:,.0f}**\n"
            f"- Collected      : **₹{paid:,.0f}**\n"
            f"- Pending        : **₹{pending:,.0f}**\n"
            f"- Overdue        : **₹{overdue:,.0f}**\n\n"
            f"Collection rate  : **{round((paid/total)*100) if total else 0}%**"
        )
    finally:
        db.close()

def _overdue_range_detail(user_id: int, query: str) -> str:
    db = SessionLocal()
    import re
    try:
        m = re.search(r"range\s+(\d+)-(\d+)\s+days", query, re.I)
        if m:
            min_days = int(m.group(1))
            max_days = int(m.group(2))
        else:
            m_plus = re.search(r"range\s+90\+\s+days", query, re.I)
            if m_plus:
                min_days = 91
                max_days = 99999
            else:
                return "Invalid range details requested."

        rows = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").all()
        today = datetime.today()
        matched = []
        for r in rows:
            if not r.due_date:
                continue
            due = parse_date(r.due_date)
            if due is None:
                continue
            overdue_days = (today - due).days
            if min_days <= overdue_days <= max_days:
                matched.append(r)

        range_label = f"{min_days}-{max_days if max_days < 99999 else ''}{'+' if max_days == 99999 else ''} days"
        if not matched:
            return f"✅ No overdue invoices found in the {range_label} range."

        total = sum(r.amount or 0 for r in matched)
        lines = [
            f"There are **{len(matched)}** overdue invoices in the {range_label} range totaling **₹{total:,.0f}**:\n",
            "| Customer | Invoice ID | Amount | Due Date |",
            "|:---|:---|:---|:---|"
        ]
        for r in matched:
            lines.append(f"| **{r.customer}** | {r.invoice_id or '—'} | ₹{r.amount:,.0f} | {r.due_date or '—'} |")
        return "\n".join(lines)
    finally:
        db.close()

def _revenue_month_detail(user_id: int, query: str) -> str:
    db = SessionLocal()
    import re
    try:
        m = re.search(r"revenue in\s+([a-zA-Z]+)\s+(\d{2,4})", query, re.I)
        if not m:
            return "Invalid monthly revenue query."
        month_str = m.group(1).lower()
        year_str = m.group(2)
        if len(year_str) == 2:
            year_str = "20" + year_str

        month_map = {
            "jan": "01", "january": "01",
            "feb": "02", "february": "02",
            "mar": "03", "march": "03",
            "apr": "04", "april": "04",
            "may": "05",
            "jun": "06", "june": "06",
            "jul": "07", "july": "07",
            "aug": "08", "august": "08",
            "sep": "09", "september": "09",
            "oct": "10", "october": "10",
            "nov": "11", "november": "11",
            "dec": "12", "december": "12"
        }

        month_num = month_map.get(month_str[:3])
        if not month_num:
            return "Invalid month specified."

        rows = db.query(Invoice).filter(Invoice.business_id == user_id).all()
        matched = []
        for r in rows:
            if not r.invoice_date:
                continue
            date_str = str(r.invoice_date)
            is_match = False
            if date_str.startswith(f"{year_str}-{month_num}"):
                is_match = True
            elif f"/{month_num}/{year_str}" in date_str or f"-{month_num}-{year_str}" in date_str:
                is_match = True
            if is_match:
                matched.append(r)

        total = sum(r.amount or 0 for r in matched)
        return f"**Revenue in {m.group(1)} {year_str}**\n\nTotal revenue: **₹{total:,.0f}** across **{len(matched)} invoices**."
    finally:
        db.close()
