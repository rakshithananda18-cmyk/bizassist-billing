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
import re
from datetime import datetime, timedelta
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, Inventory
from services.dates import parse_date

logger = logging.getLogger("bizassist.handlers.invoices")

# Invoice IDs look like SUP-INV-0138 / ROY-INV-0001 — a 2–6 letter prefix, INV, digits.
# Matches both bare IDs ("INV-0007") and prefixed ones ("SUP-INV-0138"). The
# real data uses bare INV-#### — the old prefix-required pattern silently failed
# on it, so the handler returned None and the LLM hallucinated an invoice (B3).
INVOICE_ID_RE = re.compile(r"\b((?:[A-Za-z]{2,6}-)?INV-\d+)\b", re.I)


def _invoice_detail(user_id: int, query: str, invoice_id: str = None) -> str:
    """Details for ONE invoice by its ID — straight from the DB, never generated.

    `invoice_id`, when supplied (e.g. by the LLM router's extracted entity), is
    authoritative; otherwise we parse it out of the query text.
    """
    inv_id = (invoice_id or "").strip()
    if not inv_id:
        m = INVOICE_ID_RE.search(query or "")
        if not m:
            return None   # no ID present → let another layer handle it
        inv_id = m.group(1)
    db = SessionLocal()
    try:
        r = (
            db.query(Invoice)
            .filter(Invoice.business_id == user_id,
                    func.lower(Invoice.invoice_id) == inv_id.lower())
            .first()
        )
        if not r:
            return (f"No invoice with ID **{inv_id}** exists in your records. "
                    f"Check the ID, or ask for a customer's invoices to see valid IDs.")
        return "\n".join([
            f"**Invoice {r.invoice_id}**\n",
            f"- Customer     : {r.customer or '—'}",
            f"- Amount       : ₹{(r.amount or 0):,.0f}",
            f"- Status       : {r.status or '—'}",
            f"- Invoice date : {r.invoice_date or '—'}",
            f"- Due date     : {r.due_date or '—'}",
            f"- Product      : {r.product}" if getattr(r, "product", None) else "",
        ]).rstrip()
    except Exception as e:
        logger.error("invoice_detail failed: %s", e, exc_info=True)
        return None
    finally:
        db.close()

def _product_performance(user_id: int) -> str:
    """Markdown product-performance answer — top sellers + dead stock, from the DB."""
    import json as _j
    from services.tools.invoices import get_product_performance
    try:
        data = _j.loads(get_product_performance(user_id, 10))
    except Exception as e:
        logger.error("product_performance handler: %s", e)
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None
    top = data.get("top_products", [])
    dead = data.get("dead_stock", [])
    if not top:
        return "No sales data yet to rank products."
    lines = [
        "**Product Performance — top sellers**\n",
        "| Product | Billed | Invoices | Overdue | Stock |",
        "|:---|---:|---:|---:|---:|",
    ]
    for p in top:
        st = p["stock"] if p.get("stock") is not None else "—"
        lines.append(f"| {p['product']} | ₹{p['billed']:,.0f} | {p['invoices']} | ₹{p['overdue']:,.0f} | {st} |")
    if dead:
        lines.append("\n**Dead stock** (in inventory, never sold):")
        for d in dead:
            lines.append(f"- {d['product']} — {d['stock']} units")
    return "\n".join(lines)


def _profit_summary(user_id: int) -> str:
    """Markdown margin/profit answer — blended margin, top products by est. profit,
    and below-cost / thin-margin flags, from the DB."""
    import json as _j
    from services.tools.invoices import get_product_margins
    try:
        d = _j.loads(get_product_margins(user_id, 10))
    except Exception as e:
        logger.error("profit_summary handler: %s", e)
        return None
    if not isinstance(d, dict):
        return None
    if d.get("error"):
        return d["error"]   # honest "no prices on file" message
    lines = [
        "**Profitability (estimated)**\n",
        f"- Blended margin : **{d.get('blended_margin_pct')}%**",
        f"- Billed revenue : ₹{d.get('total_billed', 0):,.0f}",
        f"- Est. gross profit : **₹{d.get('est_gross_profit', 0):,.0f}**",
        "\n| Product | Cost | Selling | Margin % | Est. profit |",
        "|:---|---:|---:|---:|---:|",
    ]
    for p in d.get("top_by_profit", []):
        mp = f"{p['margin_pct']}%" if p.get("margin_pct") is not None else "—"
        lines.append(f"| {p['product']} | ₹{p['cost']:,.0f} | ₹{p['selling']:,.0f} | {mp} | ₹{p['est_gross_profit']:,.0f} |")
    if d.get("below_cost"):
        lines.append(f"\n⚠ **Sold at/below cost:** {', '.join(d['below_cost'])}")
    if d.get("thin_margin_under_10pct"):
        lines.append(f"🔸 **Thin margin (<10%):** {', '.join(d['thin_margin_under_10pct'])}")
    lines.append(f"\n_{d.get('note', '')}_")
    return "\n".join(lines)


def _sales_growth(user_id: int) -> str:
    import json as _j
    from services.tools.invoices import get_sales_growth
    try:
        d = _j.loads(get_sales_growth(user_id))
    except Exception:
        return None
    if d.get("error"):
        return d["error"]
    yoy = f"{d['yoy_growth_pct']}%" if d.get("yoy_growth_pct") is not None else "n/a (no prior-year data)"
    mom = f"{d['mom_growth_pct']}%" if d.get("mom_growth_pct") is not None else "n/a"
    lines = [
        "**Sales Growth**\n",
        f"- This year billed : ₹{d['this_year_billed']:,.0f}",
        f"- Last year billed : ₹{d['last_year_billed']:,.0f}",
        f"- **YoY growth : {yoy}**",
        f"- Latest month ({d.get('latest_month')}) : ₹{d['latest_month_billed']:,.0f}  (MoM {mom})",
        "\nRecent months:",
    ]
    for m in d.get("recent_months", []):
        lines.append(f"- {m['month']}: ₹{m['billed']:,.0f}")
    return "\n".join(lines)


def _dso_summary(user_id: int) -> str:
    import json as _j
    from services.tools.invoices import get_dso
    try:
        d = _j.loads(get_dso(user_id))
    except Exception:
        return None
    if d.get("error"):
        return d["error"]
    return ("**Collection Speed**\n\n"
            f"- Days Sales Outstanding (approx) : **{d['dso_days']} days**\n"
            f"- Avg days overdue (on {d['overdue_invoices']} overdue invoices) : {d['avg_days_overdue']} days\n"
            f"- Outstanding : ₹{d['outstanding']:,.0f} of ₹{d['total_billed']:,.0f} billed\n\n"
            f"_{d['note']}_")


def _dormant_customers(user_id: int) -> str:
    import json as _j
    from services.tools.invoices import get_dormant_customers
    try:
        d = _j.loads(get_dormant_customers(user_id))
    except Exception:
        return None
    if d.get("error"):
        return d["error"]
    cs = d.get("customers", [])
    if not cs:
        return f"No dormant customers — everyone has bought within {d['threshold_days']} days."
    lines = [f"**Dormant customers** (no purchase in {d['threshold_days']}+ days) — {d['count']} total\n",
             "| Customer | Last purchase | Days quiet | Lifetime ₹ |", "|:---|:---|---:|---:|"]
    for c in cs:
        lines.append(f"| {c['customer']} | {c['last_purchase']} | {c['days_since']} | ₹{c['lifetime_revenue']:,.0f} |")
    return "\n".join(lines)


def _customer_margins(user_id: int) -> str:
    import json as _j
    from services.tools.invoices import get_customer_margins
    try:
        d = _j.loads(get_customer_margins(user_id))
    except Exception:
        return None
    if d.get("error"):
        return d["error"]
    rows = d.get("top_by_profit", [])
    if not rows:
        return "Not enough data to estimate customer margins."
    lines = ["**Customer profitability (estimated)**\n",
             "| Customer | Billed | Margin % | Est. profit |", "|:---|---:|---:|---:|"]
    for r in rows:
        mp = f"{r['margin_pct']}%" if r.get("margin_pct") is not None else "—"
        lines.append(f"| {r['customer']} | ₹{r['billed']:,.0f} | {mp} | ₹{r['est_gross_profit']:,.0f} |")
    lines.append(f"\n_{d['note']}_")
    return "\n".join(lines)


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
