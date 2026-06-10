"""
clients.py  —  Customer & Client Handlers
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

logger = logging.getLogger("bizassist.handlers.clients")

def _top_customers(user_id: int) -> str:
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Invoice.customer,
                func.sum(Invoice.amount).label("total"),
                func.count(Invoice.id).label("invoices")
            )
            .filter(Invoice.business_id == user_id)
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .limit(5)
            .all()
        )
        if not rows:
            return "No customer data found yet. Upload an invoice file to get started."

        lines = [
            "Here are your **Top 5 Customers** by revenue:\n",
            "| Rank | Customer | Revenue | Invoices |",
            "|:---|:---|:---|:---|"
        ]
        for i, r in enumerate(rows, 1):
            lines.append(f"| {i} | **{r.customer}** | ₹{r.total:,.0f} | {r.invoices} |")
        return "\n".join(lines)
    finally:
        db.close()

def _client_summary(user_id: int, params: dict = None) -> str:
    """Per-customer financial snapshot — all figures straight from the DB."""
    customer = (params or {}).get("customer")
    if not customer:
        return None   # no customer -> let the AI layer handle it
    db = SessionLocal()
    try:
        rows = (
            db.query(Invoice)
            .filter(Invoice.business_id == user_id,
                    func.lower(Invoice.customer) == customer.strip().lower())
            .all()
        )
        if not rows:
            return f"No invoices found for **{customer}**."

        name = rows[0].customer  # canonical casing as stored
        total = sum(r.amount or 0 for r in rows)
        amt = lambda st: sum(r.amount or 0 for r in rows if r.status == st)
        cnt = lambda st: sum(1 for r in rows if r.status == st)
        paid_amt, pend_amt, over_amt = amt("Paid"), amt("Pending"), amt("Overdue")
        coll = round((paid_amt / total) * 100) if total else 0

        lines = [
            f"**{name} — Client Summary**\n",
            f"- Total billed : **₹{total:,.0f}**  ({len(rows)} invoice{'s' if len(rows) != 1 else ''})",
            f"- Collected    : **₹{paid_amt:,.0f}**  ({coll}%)",
            f"- Pending      : **₹{pend_amt:,.0f}**  ({cnt('Pending')})",
            f"- Overdue      : **₹{over_amt:,.0f}**  ({cnt('Overdue')})",
        ]

        overdue_rows = sorted(
            [r for r in rows if r.status == "Overdue"],
            key=lambda x: x.amount or 0, reverse=True,
        )
        if overdue_rows:
            lines.append("\n**Overdue invoices**")
            for r in overdue_rows:
                lines.append(
                    f"- ₹{r.amount:,.0f}"
                    f"{f'  |  Due: {r.due_date}' if r.due_date else ''}"
                )
        return "\n".join(lines)
    finally:
        db.close()
