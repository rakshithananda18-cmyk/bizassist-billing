"""
services/charts.py
==================
Presentation service for building Chart.js-compatible payloads from DB tables.
"""

import logging
import re as _re
from typing import Optional
from collections import defaultdict
from datetime import datetime as _dt
from sqlalchemy import func

from database.db import SessionLocal
from database.models import Invoice
from services.dates import parse_date

logger = logging.getLogger("bizassist.charts")


def build_chart_data(user_query: str, user_id: int) -> Optional[dict]:
    q = user_query.lower()
    if not _re.search(r"chart|graph|visuali[sz]e|plot|trend", q):
        return None
    from core.billing.balances import business_revenue_summary, customer_revenue_rows, monthly_revenue_rows
    db = SessionLocal()
    try:
        if any(word in q for word in ("monthly", "month", "trend", "over time")):
            rows = monthly_revenue_rows(db, user_id)
            if not rows:
                return None
            return {"type": "line", "title": "Monthly Revenue Trend",
                "labels": [_dt.strptime(row["month"], "%Y-%m").strftime("%b %Y") for row in rows],
                "datasets": [{"label": "Net revenue (₹)", "data": [row["billed"] for row in rows],
                              "borderColor": "#6366f1", "backgroundColor": "rgba(99,102,241,0.15)", "tension": 0.4, "fill": True}]}
        if any(word in q for word in ("customer", "client", "top", "debtor")) and not any(word in q for word in ("status", "payment", "overdue", "pending")):
            rows = customer_revenue_rows(db, user_id)[:7]
            if not rows:
                return None
            return {"type": "bar", "title": "Top Customers by Revenue", "labels": [row.customer for row in rows],
                "datasets": [{"label": "Net revenue (₹)", "data": [row.total_amount for row in rows], "backgroundColor": "#6366f1", "borderRadius": 6}]}
        summary = business_revenue_summary(db, user_id)
        if not summary["invoice_count"]:
            return None
        specific = any(word in q for word in ("revenue", "invoice", "payment", "overdue", "pending", "status"))
        return {"type": "doughnut" if specific else "bar", "title": "Revenue by Status" if specific else "Invoice Status Breakdown",
            "labels": ["Paid", "Pending", "Overdue"], "basis": "Net cash collected and remaining receivables, after refunds/returns",
            "datasets": [{"label": "Amount (₹)", "data": [summary["collected_revenue"],
                max(summary["outstanding_revenue"] - summary["overdue_revenue"], 0), summary["overdue_revenue"]],
                "backgroundColor": ["#22c55e", "#f59e0b", "#ef4444"]}]}
    except Exception as error:
        logger.warning("[CHART] Financial chart failed: %s", error)
        return None
    finally:
        db.close()
