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
    from core.billing.balances import outstanding_rows
    db = SessionLocal()
    try:
        all_rows = outstanding_rows(db, user_id, overdue=True)
        total_count, total_amount = len(all_rows), sum(row.amount for row in all_rows)
        rows = all_rows if limit == 0 else all_rows[:limit]
        if not rows:
            return "No overdue invoices. All payments are on track."
        effective = len(rows)
        capped = effective < total_count
        header = (f"**Showing top {effective} of {total_count} overdue invoices** (₹{total_amount:,.0f} total outstanding)"
                  if capped else f"**All {total_count} overdue invoices** (₹{total_amount:,.0f} outstanding)")
        lines = [header + ":\n", "| Customer | Invoice ID | Amount | Due Date |", "|:---|:---|:---|:---|"]
        for row in rows:
            lines.append(f"| **{row.customer}** | {row.invoice_id or '-'} | ₹{row.amount:,.0f} | {row.due_date or '-'} |")
        if capped:
            lines.append("\n" + large_data_note(effective, total_count, "overdue invoices"))
        return "\n".join(lines)
    finally:
        db.close()


def _overdue_amount(user_id: int) -> str:
    from core.billing.balances import outstanding_rows
    db = SessionLocal()
    try:
        rows = outstanding_rows(db, user_id, overdue=True)
        amount, count = sum(row.amount for row in rows), len(rows)
        return f"**Total Overdue Amount**\n\n₹{amount:,.0f} across **{count} invoice{'s' if count != 1 else ''}**."
    finally:
        db.close()


def _pending_list(user_id: int, limit: int = LIST_CAP) -> str:
    from core.billing.balances import outstanding_rows
    db = SessionLocal()
    try:
        all_rows = outstanding_rows(db, user_id, overdue=False)
        total_count, total_amount = len(all_rows), sum(row.amount for row in all_rows)
        rows = all_rows if limit == 0 else all_rows[:limit]
        if not rows:
            return "No pending invoices found."
        effective = len(rows)
        capped = effective < total_count
        header = (f"**Showing top {effective} of {total_count} pending invoices** (₹{total_amount:,.0f} total outstanding)"
                  if capped else f"**All {total_count} pending invoices** (₹{total_amount:,.0f} outstanding)")
        lines = [header + ":\n", "| Customer | Invoice ID | Amount | Due Date |", "|:---|:---|:---|:---|"]
        for row in rows:
            lines.append(f"| **{row.customer}** | {row.invoice_id or '-'} | ₹{row.amount:,.0f} | {row.due_date or '-'} |")
        if capped:
            lines.append("\n" + large_data_note(effective, total_count, "pending invoices"))
        return "\n".join(lines)
    finally:
        db.close()


def _top_debtors(user_id: int) -> str:
    """Rank customers by total outstanding (overdue) amount."""
    db = SessionLocal()
    try:
        from core.billing.balances import debtor_rows
        rows = debtor_rows(db, user_id)[:10]
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
