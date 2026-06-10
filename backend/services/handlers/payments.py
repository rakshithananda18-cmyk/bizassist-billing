"""
payments.py  --  Payment & Overdue Handlers
"""
import logging
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice
from services.handlers.utils import LIST_CAP, large_data_note

logger = logging.getLogger("bizassist.handlers.payments")


def _overdue_list(user_id: int, limit: int = LIST_CAP) -> str:
    db = SessionLocal()
    try:
        total_count  = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").count()
        total_amount = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").scalar() or 0

        q = (
            db.query(Invoice)
            .filter(Invoice.business_id == user_id, Invoice.status == "Overdue")
            .order_by(Invoice.amount.desc())
        )
        rows = q.all() if limit == 0 else q.limit(limit).all()
        if not rows:
            return "No overdue invoices. All payments are on track."

        effective = limit if limit > 0 else total_count
        is_capped = 0 < effective < total_count
        header = (
            f"**Showing top {effective} of {total_count} overdue invoices** (₹{total_amount:,.0f} total outstanding)"
            if is_capped else
            f"**All {total_count} overdue invoices** (₹{total_amount:,.0f} outstanding)"
        )
        lines = [header + ":\n",
                 "| Customer | Invoice ID | Amount | Due Date |",
                 "|:---|:---|:---|:---|"]
        for r in rows:
            lines.append(f"| **{r.customer}** | {r.invoice_id or '-'} | ₹{r.amount:,.0f} | {r.due_date or '-'} |")
        if is_capped:
            lines.append("\n" + large_data_note(effective, total_count, "overdue invoices"))
        return "\n".join(lines)
    finally:
        db.close()


def _overdue_amount(user_id: int) -> str:
    db = SessionLocal()
    try:
        amount = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").scalar() or 0
        count  = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").count()
        return (
            f"**Total Overdue Amount**\n\n"
            f"₹{amount:,.0f} across **{count} invoice{'s' if count != 1 else ''}**."
        )
    finally:
        db.close()


def _pending_list(user_id: int, limit: int = LIST_CAP) -> str:
    db = SessionLocal()
    try:
        total_count  = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Pending").count()
        total_amount = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Pending").scalar() or 0

        q = (
            db.query(Invoice)
            .filter(Invoice.business_id == user_id, Invoice.status == "Pending")
            .order_by(Invoice.amount.desc())
        )
        rows = q.all() if limit == 0 else q.limit(limit).all()
        if not rows:
            return "No pending invoices found."

        effective = limit if limit > 0 else total_count
        is_capped = 0 < effective < total_count
        header = (
            f"**Showing top {effective} of {total_count} pending invoices** (₹{total_amount:,.0f} total)"
            if is_capped else
            f"**All {total_count} pending invoices** (₹{total_amount:,.0f})"
        )
        lines = [header + ":\n",
                 "| Customer | Invoice ID | Amount | Due Date |",
                 "|:---|:---|:---|:---|"]
        for r in rows:
            lines.append(f"| **{r.customer}** | {r.invoice_id or '-'} | ₹{r.amount:,.0f} | {r.due_date or '-'} |")
        if is_capped:
            lines.append("\n" + large_data_note(effective, total_count, "pending invoices"))
        return "\n".join(lines)
    finally:
        db.close()


def _top_debtors(user_id: int) -> str:
    """Rank customers by total outstanding (overdue) amount."""
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Invoice.customer,
                func.sum(Invoice.amount).label("overdue_total"),
                func.count(Invoice.id).label("invoices")
            )
            .filter(Invoice.business_id == user_id, Invoice.status == "Overdue")
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .limit(10)
            .all()
        )
        if not rows:
            return "No overdue customers right now. All accounts are clear."

        total = sum(float(r.overdue_total or 0) for r in rows)
        lines = [
            "**Top Debtors** -- customers with the highest outstanding overdue amounts:\n",
            "| Rank | Customer | Overdue Amount | Invoices |",
            "|:---|:---|:---|:---|",
        ]
        for i, r in enumerate(rows, 1):
            pct = round((float(r.overdue_total or 0) / total) * 100) if total else 0
            lines.append(f"| {i} | **{r.customer}** | ₹{float(r.overdue_total or 0):,.0f} ({pct}%) | {r.invoices} |")
        lines.append(f"\n**Total overdue: ₹{total:,.0f}** across {len(rows)} customer{'s' if len(rows) != 1 else ''}.")
        return "\n".join(lines)
    finally:
        db.close()
