"""Invoice and customer tool functions + schemas."""
import json
import logging
from datetime import date, datetime, timedelta
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, Inventory
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


def get_revenue_trend(user_id: int, months: int = 12) -> str:
    """Monthly billed vs collected revenue (last N months) from invoice_date —
    for sales-trend / growth questions. Dates are ISO (YYYY-MM-DD) at ingest."""
    from collections import defaultdict
    db = SessionLocal()
    try:
        agg = defaultdict(lambda: {"billed": 0.0, "collected": 0.0, "invoices": 0})
        for r in (db.query(Invoice.invoice_date, Invoice.amount, Invoice.status)
                  .filter(Invoice.business_id == user_id).all()):
            m = (r.invoice_date or "")[:7]          # YYYY-MM
            if len(m) != 7:
                continue
            amt = float(r.amount or 0)
            agg[m]["billed"] += amt
            agg[m]["invoices"] += 1
            if r.status == "Paid":
                agg[m]["collected"] += amt
        keys = sorted(agg.keys())[-months:]
        trend = [{"month": m, "billed": round(agg[m]["billed"]),
                  "collected": round(agg[m]["collected"]), "invoices": agg[m]["invoices"]}
                 for m in keys]
        return json.dumps(trend)
    except Exception as e:
        logger.error("get_revenue_trend failed: %s", e)
        return json.dumps({"error": str(e)})
    finally:
        db.close()


def get_product_performance(user_id: int, limit: int = 10) -> str:
    """Top products by billed amount (+ invoices, overdue, current stock) and
    DEAD STOCK (in inventory but never invoiced). Joins invoices↔inventory by name."""
    from collections import defaultdict
    db = SessionLocal()
    try:
        agg = defaultdict(lambda: {"billed": 0.0, "overdue": 0.0, "invoices": 0})
        for r in (db.query(Invoice.product, Invoice.amount, Invoice.status)
                  .filter(Invoice.business_id == user_id).all()):
            p = r.product or "Unknown"
            amt = float(r.amount or 0)
            agg[p]["billed"] += amt
            agg[p]["invoices"] += 1
            if r.status == "Overdue":
                agg[p]["overdue"] += amt
        sold = set(agg.keys())
        stock = {i.product_name: i.stock
                 for i in db.query(Inventory).filter(Inventory.business_id == user_id).all()}
        top = sorted(agg.items(), key=lambda x: -x[1]["billed"])[:limit]
        top_list = [{"product": p, "billed": round(v["billed"]), "invoices": v["invoices"],
                     "overdue": round(v["overdue"]), "stock": stock.get(p)}
                    for p, v in top]
        dead = [{"product": name, "stock": st}
                for name, st in stock.items() if name not in sold and (st or 0) > 0]
        return json.dumps({"top_products": top_list, "dead_stock": dead[:10]})
    except Exception as e:
        logger.error("get_product_performance failed: %s", e)
        return json.dumps({"error": str(e)})
    finally:
        db.close()


def get_product_margins(user_id: int, limit: int = 10) -> str:
    """
    Per-product margins (selling vs cost) + blended margin + ESTIMATED gross
    profit (billed revenue × margin%, since invoices carry no per-unit qty) +
    below-cost / thin-margin flags. Grounded; the estimate is labelled.
    """
    from collections import defaultdict
    db = SessionLocal()
    try:
        inv = {i.product_name: (float(i.cost_price or 0), float(i.selling_price or 0))
               for i in db.query(Inventory).filter(Inventory.business_id == user_id).all()}
        if not any(s > 0 for _, s in inv.values()):
            return json.dumps({"error": "No selling/cost prices on file — upload inventory with "
                                        "cost_price and selling_price to analyse margins."})
        billed = defaultdict(float)
        for r in (db.query(Invoice.product, Invoice.amount)
                  .filter(Invoice.business_id == user_id).all()):
            billed[r.product or "Unknown"] += float(r.amount or 0)

        products, total_billed, total_profit = [], 0.0, 0.0
        below_cost, thin = [], []
        for name, (cost, sell) in inv.items():
            margin_pct = round((sell - cost) / sell * 100, 1) if sell > 0 else None
            b = billed.get(name, 0.0)
            est = round(b * (margin_pct / 100)) if (margin_pct is not None and b) else 0
            total_billed += b
            total_profit += est
            products.append({"product": name, "cost": round(cost, 2), "selling": round(sell, 2),
                             "margin_pct": margin_pct, "billed": round(b), "est_gross_profit": est})
            if sell > 0 and 0 < sell <= cost:
                below_cost.append(name)
            elif margin_pct is not None and margin_pct < 10:
                thin.append(name)

        products.sort(key=lambda x: x["est_gross_profit"], reverse=True)
        blended = round(total_profit / total_billed * 100, 1) if total_billed else None
        return json.dumps({
            "blended_margin_pct": blended,
            "total_billed": round(total_billed),
            "est_gross_profit": round(total_profit),
            "top_by_profit": products[:limit],
            "below_cost": below_cost,
            "thin_margin_under_10pct": thin,
            "note": "Gross profit is ESTIMATED as billed revenue × product margin% "
                    "(invoices have no per-unit quantity).",
        })
    except Exception as e:
        logger.error("get_product_margins failed: %s", e)
        return json.dumps({"error": str(e)})
    finally:
        db.close()


def get_sales_growth(user_id: int) -> str:
    """Year-over-year and recent month-over-month revenue growth (from invoice_date)."""
    from collections import defaultdict
    db = SessionLocal()
    try:
        now = datetime.now()
        by_year, by_month = defaultdict(float), defaultdict(float)
        for r in (db.query(Invoice.invoice_date, Invoice.amount)
                  .filter(Invoice.business_id == user_id).all()):
            d = r.invoice_date or ""
            if len(d) < 7:
                continue
            a = float(r.amount or 0)
            by_year[d[:4]] += a
            by_month[d[:7]] += a
        this_y = by_year.get(str(now.year), 0.0)
        last_y = by_year.get(str(now.year - 1), 0.0)
        yoy = round((this_y - last_y) / last_y * 100, 1) if last_y else None
        months = sorted(by_month.keys())
        last_m = by_month[months[-1]] if months else 0.0
        prev_m = by_month[months[-2]] if len(months) > 1 else 0.0
        mom = round((last_m - prev_m) / prev_m * 100, 1) if prev_m else None
        return json.dumps({
            "this_year_billed": round(this_y), "last_year_billed": round(last_y),
            "yoy_growth_pct": yoy,
            "latest_month": months[-1] if months else None, "latest_month_billed": round(last_m),
            "mom_growth_pct": mom,
            "recent_months": [{"month": m, "billed": round(by_month[m])} for m in months[-6:]],
        })
    except Exception as e:
        logger.error("get_sales_growth failed: %s", e)
        return json.dumps({"error": str(e)})
    finally:
        db.close()


def get_dso(user_id: int) -> str:
    """Days Sales Outstanding (annualised approx) + average days overdue — collection speed."""
    db = SessionLocal()
    try:
        now = date.today()
        total = outstanding = 0.0
        overdue_days = []
        for r in (db.query(Invoice.amount, Invoice.status, Invoice.due_date)
                  .filter(Invoice.business_id == user_id).all()):
            a = float(r.amount or 0)
            total += a
            if r.status in ("Overdue", "Pending"):
                outstanding += a
            if r.status == "Overdue":
                due = parse_date_only(r.due_date)
                if due:
                    overdue_days.append((now - due).days)
        if total <= 0:
            return json.dumps({"error": "No invoice data."})
        dso = round(outstanding / total * 365)
        avg_overdue = round(sum(overdue_days) / len(overdue_days)) if overdue_days else 0
        return json.dumps({
            "dso_days": dso, "outstanding": round(outstanding), "total_billed": round(total),
            "avg_days_overdue": avg_overdue, "overdue_invoices": len(overdue_days),
            "note": "DSO ≈ (outstanding / total billed) × 365. Lower is better.",
        })
    except Exception as e:
        logger.error("get_dso failed: %s", e)
        return json.dumps({"error": str(e)})
    finally:
        db.close()


def get_dormant_customers(user_id: int, days: int = 90, limit: int = 10) -> str:
    """Customers who bought before but not in the last `days` — ranked by lifetime value."""
    from collections import defaultdict
    db = SessionLocal()
    try:
        now = date.today()
        cutoff = now - timedelta(days=days)
        last_buy, total = {}, defaultdict(float)
        for r in (db.query(Invoice.customer, Invoice.invoice_date, Invoice.amount)
                  .filter(Invoice.business_id == user_id).all()):
            c = r.customer or "Unknown"
            total[c] += float(r.amount or 0)
            d = parse_date_only(r.invoice_date)
            if d and (c not in last_buy or d > last_buy[c]):
                last_buy[c] = d
        dormant = [{"customer": c, "last_purchase": last.strftime("%Y-%m-%d"),
                    "days_since": (now - last).days, "lifetime_revenue": round(total[c])}
                   for c, last in last_buy.items() if last < cutoff]
        dormant.sort(key=lambda x: -x["lifetime_revenue"])
        return json.dumps({"threshold_days": days, "count": len(dormant), "customers": dormant[:limit]})
    except Exception as e:
        logger.error("get_dormant_customers failed: %s", e)
        return json.dumps({"error": str(e)})
    finally:
        db.close()


def get_customer_margins(user_id: int, limit: int = 10) -> str:
    """Estimated gross profit per CUSTOMER = Σ(invoice amount × that product's margin%)."""
    from collections import defaultdict
    db = SessionLocal()
    try:
        margin = {}
        for i in db.query(Inventory).filter(Inventory.business_id == user_id).all():
            c, s = float(i.cost_price or 0), float(i.selling_price or 0)
            if s > 0:
                # use the rounded margin% (same basis as product_margins) so a
                # customer's est. profit ties out with the per-product figures
                margin[i.product_name] = round((s - c) / s * 100, 1) / 100
        if not margin:
            return json.dumps({"error": "No product prices on file to estimate customer margins."})
        billed, profit = defaultdict(float), defaultdict(float)
        for r in (db.query(Invoice.customer, Invoice.product, Invoice.amount)
                  .filter(Invoice.business_id == user_id).all()):
            cust = r.customer or "Unknown"
            a = float(r.amount or 0)
            billed[cust] += a
            m = margin.get(r.product)
            if m is not None:
                profit[cust] += a * m
        rows = [{"customer": c, "billed": round(billed[c]), "est_gross_profit": round(profit[c]),
                 "margin_pct": round(profit[c] / billed[c] * 100, 1) if billed[c] else None}
                for c in billed]
        rows.sort(key=lambda x: -x["est_gross_profit"])
        return json.dumps({"top_by_profit": rows[:limit],
                           "note": "Estimated: invoice amount × the product's margin% (no per-unit qty)."})
    except Exception as e:
        logger.error("get_customer_margins failed: %s", e)
        return json.dumps({"error": str(e)})
    finally:
        db.close()


def get_top_debtors(user_id: int, limit: int = 5) -> str:
    """Top N customers by TOTAL OVERDUE amount — i.e. who owes the most (their
    aggregated outstanding debt), NOT individual invoices and NOT revenue."""
    db = SessionLocal()
    try:
        rows = (
            db.query(
                Invoice.customer,
                func.sum(Invoice.amount).label("overdue_total"),
                func.count(Invoice.id).label("overdue_count"),
            )
            .filter(Invoice.business_id == user_id, Invoice.status == "Overdue")
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .limit(limit)
            .all()
        )
        return json.dumps([
            {"customer": r.customer, "overdue_total": float(r.overdue_total or 0),
             "overdue_count": r.overdue_count}
            for r in rows
        ])
    except Exception as e:
        logger.error("get_top_debtors failed: %s", e)
        return json.dumps({"error": f"Failed to fetch top debtors: {e}"})
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
            "description": "Returns top customers ranked by total billing REVENUE (their value to you).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Max customers to return. Defaults to 5."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_top_debtors",
            "description": "Returns customers ranked by their TOTAL OVERDUE amount — i.e. WHO OWES YOU THE MOST. "
                           "Use this for 'who owes the most', 'biggest debtors', or prioritising collections. "
                           "Do NOT use list_invoices for this — that returns individual bills, not per-customer totals.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Max customers to return. Defaults to 5."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "overdue_aging_summary",
            "description": "Returns overdue totals bucketed by age (0-30, 31-90, 91-180, 180+ days) — "
                           "use to triage recoverability (recent vs likely bad debt).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revenue_trend",
            "description": "Monthly billed vs collected revenue over the last N months — "
                           "use for sales-trend, growth, or seasonality questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "months": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "How many recent months. Defaults to 12."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sales_growth",
            "description": "Year-over-year and recent month-over-month revenue growth. Use for "
                           "'are sales growing', YoY, or momentum questions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dso",
            "description": "Days Sales Outstanding (how long cash is tied up) + average days overdue. "
                           "Use for collection-speed / 'how fast am I getting paid' questions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dormant_customers",
            "description": "Customers who used to buy but have gone quiet (no purchase in N days), "
                           "ranked by lifetime value. Use for retention / win-back questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Inactivity threshold in days. Defaults to 90."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "customer_margins",
            "description": "Estimated gross profit per CUSTOMER (which accounts actually make you money "
                           "vs just move volume). Use for customer profitability questions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "product_margins",
            "description": "Per-product margins (cost vs selling), blended margin %, ESTIMATED gross "
                           "profit, and below-cost / thin-margin flags. Use for profit, margin, or "
                           "'how to make more profit' questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Max products by profit. Defaults to 10."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "product_performance",
            "description": "Top products by billed revenue (with invoice count, overdue, current stock) "
                           "plus DEAD STOCK (in inventory but never sold). Use for 'what's selling', "
                           "best/worst products, or what to push/clear.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}], "description": "Max top products. Defaults to 10."},
                },
            },
        },
    },
]
