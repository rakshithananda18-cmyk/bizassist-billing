"""
services/bi_analytics.py
========================
Dynamic Business Intelligence (BI) Analytics Service for STATER Bill.
Aggregates platform-wide sales volume, revenue velocity, payment mode breakdown,
top performing merchants, and merchant cohorts.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from sqlalchemy import text, func
from sqlalchemy.orm import Session
from database.models import User, Invoice, Product


def get_bi_dashboard_metrics(db: Session, days: int = 30) -> Dict[str, Any]:
    """Calculate platform-wide BI analytics over the specified timeframe."""
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)
    is_pg = db.bind.dialect.name == "postgresql"

    # 1. Executive Headline KPIs
    # Total revenue & invoices (All-time and within window)
    total_rev_all = db.query(func.coalesce(func.sum(Invoice.total_amount), 0.0)).scalar() or 0.0
    total_inv_all = db.query(func.count(Invoice.id)).scalar() or 0
    total_merchants_all = db.query(func.count(User.id)).filter(User.parent_business_id.is_(None)).scalar() or 0
    total_products_all = db.query(func.count(Product.id)).scalar() or 0

    # Window revenue & invoices
    window_rev = db.query(func.coalesce(func.sum(Invoice.total_amount), 0.0)).filter(
        Invoice.created_at >= start_date
    ).scalar() or 0.0
    
    window_inv = db.query(func.count(Invoice.id)).filter(
        Invoice.created_at >= start_date
    ).scalar() or 0

    aov = round(total_rev_all / max(1, total_inv_all), 2)
    aov_window = round(window_rev / max(1, window_inv), 2)

    # 2. Daily Revenue & Volume Trend (Time series for graphs)
    daily_trends: List[Dict[str, Any]] = []
    
    if is_pg:
        # Group by day via PostgreSQL date_trunc
        daily_query = text("""
            SELECT 
                to_char(date_trunc('day', created_at), 'YYYY-MM-DD') as day,
                COUNT(id) as count,
                COALESCE(SUM(total_amount), 0.0) as revenue
            FROM invoices
            WHERE created_at >= :start
            GROUP BY date_trunc('day', created_at)
            ORDER BY date_trunc('day', created_at) ASC
        """)
        rows = db.execute(daily_query, {"start": start_date}).fetchall()
        data_by_day = {r[0]: {"count": int(r[1]), "revenue": round(float(r[2]), 2)} for r in rows}
    else:
        # SQLite date function fallback
        daily_query = text("""
            SELECT 
                strftime('%Y-%m-%d', created_at) as day,
                COUNT(id) as count,
                COALESCE(SUM(total_amount), 0.0) as revenue
            FROM invoices
            WHERE created_at >= :start
            GROUP BY strftime('%Y-%m-%d', created_at)
            ORDER BY day ASC
        """)
        rows = db.execute(daily_query, {"start": start_date}).fetchall()
        data_by_day = {r[0]: {"count": int(r[1]), "revenue": round(float(r[2]), 2)} for r in rows}

    # Fill every single day in the window (no missing dates in chart)
    curr = start_date
    while curr <= now:
        d_str = curr.strftime("%Y-%m-%d")
        entry = data_by_day.get(d_str, {"count": 0, "revenue": 0.0})
        daily_trends.append({
            "date": d_str,
            "display_date": curr.strftime("%b %d"),
            "invoices": entry["count"],
            "revenue": entry["revenue"]
        })
        curr += timedelta(days=1)

    # 3. Payment Mode Distribution
    # Group payments by payment_mode
    payment_modes: Dict[str, float] = {}
    total_payment_val = 0.0
    pm_rows = db.query(
        Invoice.payment_mode,
        func.count(Invoice.id),
        func.coalesce(func.sum(Invoice.paid_amount), 0.0)
    ).group_by(Invoice.payment_mode).all()

    for mode, count, amount in pm_rows:
        label = (mode or "Cash").strip().capitalize()
        amt = float(amount or 0.0)
        payment_modes[label] = round(amt, 2)
        total_payment_val += amt

    # Convert to percentage breakdown
    payment_breakdown = [
        {
            "mode": mode,
            "amount": amt,
            "percentage": round((amt / max(1.0, total_payment_val)) * 100, 1)
        }
        for mode, amt in sorted(payment_modes.items(), key=lambda x: x[1], reverse=True)
    ]
    if not payment_breakdown:
        payment_breakdown = [{"mode": "Cash / UPI", "amount": 0.0, "percentage": 100.0}]

    # 4. Top Performing Merchants by Revenue
    top_merchants_query = (
        db.query(
            User.id,
            User.business_name,
            User.public_id,
            User.username,
            func.count(Invoice.id).label("invoice_count"),
            func.coalesce(func.sum(Invoice.total_amount), 0.0).label("revenue")
        )
        .join(Invoice, Invoice.business_id == User.id)
        .filter(User.parent_business_id.is_(None))
        .group_by(User.id, User.business_name, User.public_id, User.username)
        .order_by(text("revenue DESC"))
        .limit(10)
        .all()
    )

    top_merchants = [
        {
            "id": r[0],
            "business_name": r[1] or r[3] or f"Business #{r[0]}",
            "public_id": r[2] or f"BA-{r[0]:04d}",
            "invoice_count": int(r[4]),
            "revenue": round(float(r[5]), 2),
            "arpu": round(float(r[5]) / max(1, int(r[4])), 2)
        }
        for r in top_merchants_query
    ]

    return {
        "timeframe_days": days,
        "kpis": {
            "total_revenue_all": round(float(total_rev_all), 2),
            "window_revenue": round(float(window_rev), 2),
            "total_invoices_all": int(total_inv_all),
            "window_invoices": int(window_inv),
            "total_merchants": int(total_merchants_all),
            "total_products": int(total_products_all),
            "average_order_value": aov,
            "window_average_order_value": aov_window,
        },
        "daily_trends": daily_trends,
        "payment_breakdown": payment_breakdown,
        "top_merchants": top_merchants,
        "generated_at": now.isoformat()
    }
