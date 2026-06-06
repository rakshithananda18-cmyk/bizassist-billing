import logging
from datetime import datetime, timedelta
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, Inventory, Payment

logger = logging.getLogger("bizassist.direct_query")

# ── Public entry point ──────────────────────────────────────────────

def handle(handler_key: str, user_query: str, user_id: int, params: dict = None) -> str:
    """
    Routes to the right DB handler and returns a formatted answer.
    All handlers open/close their own DB session.
    """
    handlers = {
        "invoice_count"        : _invoice_count,
        "total_revenue"        : _total_revenue,
        "overdue_list"         : _overdue_list,
        "overdue_amount"       : _overdue_amount,
        "pending_list"         : _pending_list,
        "top_customers"        : _top_customers,
        "inventory_count"      : _inventory_count,
        "low_stock"            : _low_stock,
        "expiring_soon"        : _expiring_soon,
        "business_summary"     : _business_summary,
        "overdue_range_detail" : _overdue_range_detail,
        "revenue_month_detail" : _revenue_month_detail,
        "client_summary"       : _client_summary,
    }

    fn = handlers.get(handler_key)

    if fn is None:
        return None   # fall through to AI layer

    try:
        if handler_key in ("overdue_range_detail", "revenue_month_detail"):
            return fn(user_id, user_query)
        if handler_key == "client_summary":
            return fn(user_id, params)
        return fn(user_id)
    except Exception as e:
        logger.error(f"DB Error in direct handler '{handler_key}': {str(e)}", exc_info=True)
        return None   # on any DB error, fall through to AI layer


# ── Individual handlers ─────────────────────────────────────────────

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


def _overdue_list(user_id: int) -> str:
    db = SessionLocal()
    try:
        rows = (
            db.query(Invoice)
            .filter(Invoice.business_id == user_id, Invoice.status == "Overdue")
            .order_by(Invoice.amount.desc())
            .all()
        )
        if not rows:
            return "✅ No overdue invoices. All payments are on track."

        total = sum(r.amount or 0 for r in rows)
        lines = [
            f"There are **{len(rows)}** overdue invoices totaling **₹{total:,.0f}**:\n",
            "| Customer | Invoice ID | Amount | Due Date |",
            "|:---|:---|:---|:---|"
        ]
        for r in rows:
            lines.append(f"| **{r.customer}** | {r.invoice_id or '—'} | ₹{r.amount:,.0f} | {r.due_date or '—'} |")
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


def _pending_list(user_id: int) -> str:
    db = SessionLocal()
    try:
        rows = (
            db.query(Invoice)
            .filter(Invoice.business_id == user_id, Invoice.status == "Pending")
            .order_by(Invoice.amount.desc())
            .limit(15)
            .all()
        )
        if not rows:
            return "✅ No pending invoices found."

        total = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Pending").scalar() or 0
        lines = [
            f"There are **{len(rows)}** pending invoices totaling **₹{total:,.0f}**:\n",
            "| Customer | Invoice ID | Amount | Due Date |",
            "|:---|:---|:---|:---|"
        ]
        for r in rows:
            lines.append(f"| **{r.customer}** | {r.invoice_id or '—'} | ₹{r.amount:,.0f} | {r.due_date or '—'} |")
        return "\n".join(lines)
    finally:
        db.close()


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


def _inventory_count(user_id: int) -> str:
    db = SessionLocal()
    try:
        total = db.query(Inventory).filter(Inventory.business_id == user_id).count()
        return f"**Inventory Count**\n\nYou have **{total} product{'s' if total != 1 else ''}** tracked in inventory."
    finally:
        db.close()


def _low_stock(user_id: int) -> str:
    db = SessionLocal()
    try:
        items = db.query(Inventory).filter(Inventory.business_id == user_id).all()
        low   = [i for i in items if i.stock is not None and int(i.stock) <= 10]

        if not low:
            return "✅ All products have sufficient stock (above 10 units)."

        low.sort(key=lambda x: int(x.stock))
        lines = [
            f"There are **{len(low)}** products with low stock (≤ 10 units):\n",
            "| Product Name | Stock | Supplier |",
            "|:---|:---|:---|"
        ]
        for item in low:
            lines.append(f"| **{item.product_name}** | `{item.stock}` units | {item.supplier or '—'} |")
        return "\n".join(lines)
    finally:
        db.close()


def _expiring_soon(user_id: int) -> str:
    db = SessionLocal()
    try:
        today = datetime.today()
        soon  = today + timedelta(days=30)
        items = db.query(Inventory).filter(Inventory.business_id == user_id).all()

        expiring = []
        for item in items:
            if not item.expiry_date:
                continue
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    exp = datetime.strptime(str(item.expiry_date), fmt)
                    if today <= exp <= soon:
                        expiring.append((item, exp))
                    break
                except ValueError:
                    continue

        if not expiring:
            return "✅ No products expiring within the next 30 days."

        expiring.sort(key=lambda x: x[1])
        lines = [
            f"There are **{len(expiring)}** products expiring within the next 30 days:\n",
            "| Product Name | Expiry Date | Days Left | Stock |",
            "|:---|:---|:---|:---|"
        ]
        for item, exp in expiring:
            days_left = (exp - today).days
            lines.append(f"| **{item.product_name}** | {item.expiry_date} | {days_left} days left | `{item.stock}` units |")
        return "\n".join(lines)
    finally:
        db.close()


def _business_summary(user_id: int) -> str:
    db = SessionLocal()
    try:
        total_rev  = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id).scalar() or 0
        inv_count  = db.query(Invoice).filter(Invoice.business_id == user_id).count()
        paid_amt   = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Paid").scalar()    or 0
        overdue_amt= db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").scalar() or 0
        pending_ct = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Pending").count()
        inv_items  = db.query(Inventory).filter(Inventory.business_id == user_id).count()

        top = (
            db.query(Invoice.customer, func.sum(Invoice.amount).label("total_amount"))
            .filter(Invoice.business_id == user_id)
            .group_by(Invoice.customer)
            .order_by(func.sum(Invoice.amount).desc())
            .first()
        )

        collection_rate = round((paid_amt / total_rev) * 100) if total_rev else 0

        return (
            f"**Business Snapshot**\n\n"
            f"**Revenue**\n"
            f"- Total       : ₹{total_rev:,.0f}\n"
            f"- Collected   : ₹{paid_amt:,.0f}  ({collection_rate}% rate)\n"
            f"- Overdue     : ₹{overdue_amt:,.0f}\n\n"
            f"**Invoices**\n"
            f"- Total       : {inv_count}\n"
            f"- Pending     : {pending_ct}\n\n"
            f"**Inventory**\n"
            f"- Products tracked : {inv_items}\n\n"
            f"**Top Customer**\n"
            f"- {top.customer} — ₹{top.total_amount:,.0f}" if top else ""
        )
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
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    due = datetime.strptime(str(r.due_date), fmt)
                    overdue_days = (today - due).days
                    if min_days <= overdue_days <= max_days:
                        matched.append(r)
                    break
                except ValueError:
                    continue

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