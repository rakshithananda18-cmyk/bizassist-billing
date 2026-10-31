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
    from core.billing.balances import invoice_balances, collection_status
    from collections import defaultdict
    db = SessionLocal()
    try:
        invoices = db.query(Invoice).filter(Invoice.business_id == user_id,
            func.coalesce(Invoice.invoice_type, "") != "credit_note").all()
        balances = invoice_balances(db, invoices)
        summary = defaultdict(lambda: {"count": 0, "total_amount": 0.0})
        for invoice in invoices:
            balance = balances[invoice.id]
            status = collection_status(balance, invoice.status)
            from services.dates import biz_today_str
            if balance["outstanding"] > 0 and (invoice.status == "Overdue" or
                    bool(invoice.due_date and invoice.due_date < biz_today_str())):
                status = "Overdue"
            summary[status]["count"] += 1
            summary[status]["total_amount"] += balance["effective_total"]
        return json.dumps(summary)
    finally:
        db.close()


def get_invoice_list(user_id: int, status: str = None, customer: str = None, limit: int = 15) -> str:
    """Gets a filtered list of invoices."""
    db = SessionLocal()
    try:
        query = db.query(Invoice).filter(Invoice.business_id == user_id)
        if customer:
            query = query.filter(Invoice.customer.ilike(f"%{customer}%"))
            # A single customer's full ledger is small — don't truncate it to the
            # global default (which would drop rows and tempt the model to fill in
            # the rest). Show the whole account.
            if limit == 15:
                limit = 200

        from core.billing.balances import invoice_balances, collection_status
        from services.dates import biz_today_str
        invoices = query.order_by(Invoice.amount.desc()).all()
        balances = invoice_balances(db, invoices)
        result = []
        for inv in invoices:
            balance = balances[inv.id]
            note = inv.invoice_type == "credit_note"
            derived_status = "Credit Note" if note else collection_status(balance, inv.status)
            if not note and balance["outstanding"] > 0 and (inv.status == "Overdue" or
                    bool(inv.due_date and inv.due_date < biz_today_str())):
                derived_status = "Overdue"
            if status and derived_status.lower() != status.lower():
                continue
            result.append({
                "invoice_id": inv.invoice_id,
                "customer":   inv.customer,
                "amount":     -balance["total"] if note else balance["effective_total"],
                "outstanding": balance["outstanding"],
                "paid_amount": balance["paid"],
                "status":     derived_status,
                "invoice_date": inv.invoice_date,
                "due_date":   inv.due_date,
            })
        result = result[:max(0, min(int(limit), 500))]
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
        from core.billing.balances import outstanding_rows
        overdue = outstanding_rows(db, user_id, overdue=True)

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
    from core.billing.balances import customer_revenue_rows
    db = SessionLocal()
    try:
        return json.dumps([{"customer": row.customer, "total_revenue": row.total_amount, "invoice_count": row.invoice_count}
                           for row in customer_revenue_rows(db, user_id)[:limit]])
    finally:
        db.close()


def get_revenue_trend(user_id: int, months: int = 12) -> str:
    from core.billing.balances import monthly_revenue_rows
    db = SessionLocal()
    try:
        return json.dumps(monthly_revenue_rows(db, user_id, months=months))
    finally:
        db.close()


def get_product_performance(user_id: int, limit: int = 10) -> str:
    """Top products by billed amount (+ invoices, overdue, current stock) and
    DEAD STOCK (in inventory but never invoiced). Joins invoices↔inventory by name."""
    from collections import defaultdict
    db = SessionLocal()
    try:
        agg = defaultdict(lambda: {"billed": 0.0, "overdue": 0.0, "invoices": 0})
        from core.billing.balances import invoice_balances
        from services.dates import biz_today_str
        invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()
        balances = invoice_balances(db, invoices)
        for r in invoices:
            note = r.invoice_type == "credit_note"
            parts = ([(line.product_name or "Unknown", float(line.line_total or 0)) for line in r.line_items]
                     if r.line_items else [(r.product or "Unknown", float(r.total_amount or r.amount or 0))])
            line_total = sum(amount for _, amount in parts)
            overdue = not note and (r.status == "Overdue" or bool(r.due_date and r.due_date < biz_today_str()))
            seen = set()
            for p, amount in parts:
                agg[p]["billed"] += -abs(amount) if note else amount
                if not note and p not in seen:
                    agg[p]["invoices"] += 1
                seen.add(p)
                if overdue and line_total > 0:
                    agg[p]["overdue"] += balances[r.id]["outstanding"] * amount / line_total
        sold = set(agg.keys())
        stock = dict(db.query(Inventory.product_name, func.sum(Inventory.stock)).filter(
            Inventory.business_id == user_id).group_by(Inventory.product_name).all())
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
        from core.billing.balances import signed_invoice_amount
        for r in (db.query(Invoice.product, signed_invoice_amount().label("amount"))
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
            "basis": "current_catalog_estimate",
            "note": "Gross profit is ESTIMATED as net billed revenue × current catalogue margin%. "
                    "Use the P&L report for historical snapshot costs and missing-cost disclosure.",
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
        from core.billing.balances import signed_invoice_amount
        for r in (db.query(Invoice.invoice_date, signed_invoice_amount().label("amount"))
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
        from core.billing.balances import business_revenue_summary, outstanding_rows
        summary = business_revenue_summary(db, user_id)
        total, outstanding = summary["net_revenue"], summary["outstanding_revenue"]
        overdue_days = []
        for r in outstanding_rows(db, user_id, overdue=True):
            due = parse_date_only(r.due_date)
            if due:
                overdue_days.append(max((now - due).days, 0))
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
        from core.billing.balances import signed_invoice_amount
        for r in (db.query(Invoice.customer, Invoice.invoice_date, Invoice.invoice_type,
                          signed_invoice_amount().label("amount"))
                  .filter(Invoice.business_id == user_id).all()):
            c = r.customer or "Unknown"
            total[c] += float(r.amount or 0)
            d = parse_date_only(r.invoice_date)
            if r.invoice_type != "credit_note" and d and (c not in last_buy or d > last_buy[c]):
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
        from core.billing.balances import signed_invoice_amount
        for r in (db.query(Invoice.customer, Invoice.product, signed_invoice_amount().label("amount"))
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
        return json.dumps({"top_by_profit": rows[:limit], "basis": "current_catalog_estimate",
                           "note": "Estimated: net invoice amount × current catalogue product margin%. "
                                   "Use P&L for historical snapshot costs and missing-cost disclosure."})
    except Exception as e:
        logger.error("get_customer_margins failed: %s", e)
        return json.dumps({"error": str(e)})
    finally:
        db.close()


def get_top_debtors(user_id: int, limit: int = 5) -> str:
    from core.billing.balances import debtor_rows
    db = SessionLocal()
    try:
        return json.dumps([{"customer": row.customer, "overdue_total": row.overdue_total, "overdue_count": row.overdue_count}
                           for row in debtor_rows(db, user_id)[:limit]])
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
