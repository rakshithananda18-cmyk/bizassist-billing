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
    """
    Detects chart/graph intent and returns a Chart.js-compatible data payload.
    Returns None if no chart is needed.
    """
    q = user_query.lower()
    is_chart = bool(_re.search(r"chart|graph|visuali[sz]e|plot|bar chart|pie chart|line chart|show.*graph|trend", q))
    if not is_chart:
        return None

    db2 = SessionLocal()
    try:
        # Monthly revenue trend (line chart) — checked FIRST before generic "revenue" match
        if any(k in q for k in ["monthly", "month", "trend", "month wise", "per month", "over time"]):
            rows = (
                db2.query(Invoice.invoice_date, func.sum(Invoice.amount).label("total"))
                .filter(Invoice.business_id == user_id, Invoice.invoice_date.isnot(None))
                .group_by(Invoice.invoice_date)
                .all()
            )
            if rows:
                # Aggregate by YYYY-MM
                monthly = defaultdict(float)
                for r in rows:
                    parsed = parse_date(r.invoice_date)
                    if parsed is not None:
                        monthly[parsed.strftime("%Y-%m")] += float(r.total or 0)
                if monthly:
                    sorted_keys = sorted(monthly.keys())
                    labels = [_dt.strptime(k, "%Y-%m").strftime("%b %Y") for k in sorted_keys]
                    data   = [round(monthly[k], 2) for k in sorted_keys]
                    return {
                        "type":  "line",
                        "title": "Monthly Revenue Trend",
                        "labels": labels,
                        "datasets": [{
                            "label":           "Revenue (₹)",
                            "data":            data,
                            "borderColor":     "#6366f1",
                            "backgroundColor": "rgba(99,102,241,0.15)",
                            "tension":         0.4,
                            "fill":            True,
                            "pointRadius":     4,
                            "pointBackgroundColor": "#6366f1"
                        }]
                    }

        # Revenue by status (pie/doughnut) — for revenue/invoice/payment queries
        if any(k in q for k in ["revenue", "invoice", "payment", "overdue", "pending", "status"]):
            rows = (
                db2.query(Invoice.status, func.sum(Invoice.amount).label("total"))
                .filter(Invoice.business_id == user_id)
                .group_by(Invoice.status)
                .all()
            )
            if rows:
                color_map = {"Paid": "#22c55e", "Pending": "#f59e0b", "Overdue": "#ef4444", "Disputed": "#8b5cf6"}
                labels = [r.status for r in rows]
                data   = [round(float(r.total or 0), 2) for r in rows]
                return {
                    "type": "doughnut",
                    "title": "Revenue by Status",
                    "labels": labels,
                    "datasets": [{
                        "label": "Amount",
                        "data": data,
                        "backgroundColor": [color_map.get(l, "#94a3b8") for l in labels]
                    }]
                }

        # Top customers by revenue (bar) — for customer/client/top queries
        if any(k in q for k in ["customer", "client", "top", "debtor"]):
            rows = (
                db2.query(Invoice.customer, func.sum(Invoice.amount).label("total"))
                .filter(Invoice.business_id == user_id)
                .group_by(Invoice.customer)
                .order_by(func.sum(Invoice.amount).desc())
                .limit(7).all()
            )
            if rows:
                return {
                    "type": "bar",
                    "title": "Top Customers by Revenue",
                    "labels": [r.customer for r in rows],
                    "datasets": [{
                        "label": "Revenue (₹)",
                        "data": [round(float(r.total or 0), 2) for r in rows],
                        "backgroundColor": "#6366f1",
                        "borderRadius": 6
                    }]
                }

        # Default: revenue breakdown bar chart
        rows = (
            db2.query(Invoice.status, func.sum(Invoice.amount).label("total"))
            .filter(Invoice.business_id == user_id)
            .group_by(Invoice.status)
            .all()
        )
        if rows:
            color_map = {"Paid": "#22c55e", "Pending": "#f59e0b", "Overdue": "#ef4444", "Disputed": "#8b5cf6"}
            labels = [r.status for r in rows]
            data   = [round(float(r.total or 0), 2) for r in rows]
            return {
                "type": "bar",
                "title": "Invoice Status Breakdown",
                "labels": labels,
                "datasets": [{
                    "label": "Amount (₹)",
                    "data": data,
                    "backgroundColor": [color_map.get(l, "#94a3b8") for l in labels],
                    "borderRadius": 6
                }]
            }
        return None
    except Exception as e:
        logger.warning(f"[CHART] Failed to build chart data: {e}")
        return None
    finally:
        db2.close()
