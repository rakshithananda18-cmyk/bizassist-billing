"""Invoice and customer tool functions + schemas."""
import json
import logging
from datetime import date, datetime
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice
from services.dates import parse_date_only

logger = logging.getLogger("bizassist.tools.invoices")


def get_invoice_summary(user_id: int) -> str:
    """Returns counts and total amounts of invoices grouped by status."""
    db = SessionLocal()
    try:
        results = db.query(
            Invoice.status,
            func.count(Invoice.id).label("count"),
            func.sum(Invoice.amount).label("total"),
        ).filter(Invoice.business_id == user_id).group_by(Invoice.status).all()

        summary = {
            row.status: {"count": row.count, "total_amount": float(row.total or 0)}
            for row in results
        }
        return json.dumps(summary)
    except Exception as e:
        logger.error("get_invoice_summary failed: %s", e)
        return json.dumps({"error": f"Failed to fetch invoice summary: {e}"})
    finally:
        db.close()


def get_invoice_list(user_id: int, status: str = None, customer: str = None, limit: int = 15) -> str:
    """Gets a filtered list of invoices."""
    db = SessionLocal()
    try:
        query = db.query(Invoice).filter(Invoice.business_id == user_id)
        if status:
            query = query.filter(Invoice.status.ilike(status))
        if customer:
            query = query.filter(Invoice.customer.ilike(f"%{customer}%"))
            # A single customer's full ledger is small — don't truncate it to the
            # global default (which would drop rows and tempt the model to fill in
            # the rest). Show the whole account.
            if limit == 15:
                limit = 200

        invoices = query.order_by(Invoice.amount.desc()).limit(limit).all()
        result = [
            {
                "invoice_id": inv.invoice_id,
                "customer":   inv.customer,
                "amount":     float(inv.amount or 0),
                "status":     inv.status,
                "invoice_date": inv.invoice_date,
                "due_date":   inv.due_date,
            }
            for inv in invoices
        ]
        return json.dumps(result)
    except Exception as e:
        logger.error("get_invoice_list failed: %s", e)
        return json.dumps({"error": f"Failed to fetch invoice list: {e}"})
    finally:
        db.close()


def get_overdue_aging_summary(user_id: int) -> str:
    """
    Returns overdue invoices bucketed by how long they are past due.
    Buckets: 0-30d (call now), 31-90d (follow up), 91-180d (escalate), 180+d (bad debt risk).
    Gives the synthesizer the recoverability context it needs for triage.
    """
    db = SessionLocal()
    today = date.today()
    buckets = {
        "0_30_days":   {"label": "0–30 days (call this week)",        "count": 0, "total": 0.0, "customers": []},
        "31_90_days":  {"label": "31–90 days (follow up urgently)",   "count": 0, "total": 0.0, "customers": []},
        "91_180_days": {"label": "91–180 days (payment plan / escalate)", "count": 0, "total": 0.0, "customers": []},
        "180_plus":    {"label": "180+ days (bad debt risk)",         "count": 0, "total": 0.0, "customers": []},
    }
    try:
        overdue = db.query(Invoice).filter(
            Invoice.business_id == user_id,
            Invoice.status.ilike("Overdue"),
        ).all()

        for inv in overdue:
            due = parse_date_only(inv.due_date)
            if due is None:
                continue
            days_past = (today - due).days
            amt = float(inv.amount or 0)
            cust = inv.customer or "Unknown"

            if days_past <= 30:
                b = buckets["0_30_days"]
            elif days_past <= 90:
                b = buckets["31_90_days"]
            elif days_past <= 180:
                b = buckets["91_180_days"]
            else:
                b = buckets["180_plus"]

            b["count"] += 1
            b["total"] += amt
            if cust not in b["customers"]:
                b["customers"].append(cust)

        # Trim customer lists to top 5 per bucket
        for b in buckets.values():
            b["customers"] = b["customers"][:5]
            b["total"] = round(b["total"], 2)

        return json.dumps(buckets, ensure_ascii=False)
    except Exception as e:
        logger.error("get_overdue_aging_summary failed: %s", e)
        return json.dumps({"error": str(e)})
    finally:
        db.close()


def get_top_customers(user_id: int, limit: int = 5) -> str:
    """Returns top N customers sorted by revenue."""
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Invoice.customer,
                func.sum(Invoice.amount).label("total_revenue"),
                func.count(Invoice.id).label("invoice_count"),
            )
            .filter(Invoice.business_id == user_id)
            
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .limit(limit)
            .all()
        )
        result = [
            {"customer": r.customer, "total_revenue": float(r.total_revenue or 0), "invoice_count": r.invoice_count}
            for r in rows
        ]
        return json.dumps(result)
    except Exception as e:
        logger.error("get_top_customers failed: %s", e)
        return json.dumps({"error": f"Failed to fetch top customers: {e}"})
    finally:
        db.close()


# ── Schemas ──────────────────────────────────────────────────────────────────

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "summarize_invoices",
            "description": "Returns counts and total amounts of invoices grouped by status (Paid, Pending, Overdue).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_invoices",
            "description": "Returns a list of invoices, optionally filtered by status or customer name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status":   {"type": "string", "description": "Filter by status: 'Paid', 'Pending', or 'Overdue'."},
                    "customer": {"type": "string", "description": "Filter by customer name (partial match)."},
                    "limit":    {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Max invoices to return. Defaults to 15."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_top_customers",
            "description": "Returns top customers ranked by total billing revenue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Max customers to return. Defaults to 5."},
                },
            },
        },
    },
]
