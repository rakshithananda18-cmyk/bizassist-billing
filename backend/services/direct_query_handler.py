from datetime import datetime, timedelta
from sqlalchemy import func
from database.db import SessionLocal
from database.models import Invoice, Inventory, Payment


# ── Public entry point ──────────────────────────────────────────────

def handle(handler_key: str, user_query: str, user_id: int) -> str:
    """
    Routes to the right DB handler and returns a formatted answer.
    All handlers open/close their own DB session.
    """
    handlers = {
        "invoice_count"    : _invoice_count,
        "total_revenue"    : _total_revenue,
        "overdue_list"     : _overdue_list,
        "overdue_amount"   : _overdue_amount,
        "pending_list"     : _pending_list,
        "top_customers"    : _top_customers,
        "inventory_count"  : _inventory_count,
        "low_stock"        : _low_stock,
        "expiring_soon"    : _expiring_soon,
        "business_summary" : _business_summary,
    }

    fn = handlers.get(handler_key)

    if fn is None:
        return None   # fall through to AI layer

    try:
        return fn(user_id)
    except Exception as e:
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
        lines = [f"**Overdue Invoices** ({len(rows)} total — ₹{total:,.0f})\n"]

        for r in rows:
            lines.append(
                f"- **{r.customer}** — ₹{r.amount:,.0f}"
                f"{f'  |  Due: {r.due_date}' if r.due_date else ''}"
            )
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
        lines = [f"**Pending Invoices** (top {len(rows)} — ₹{total:,.0f} total)\n"]

        for r in rows:
            lines.append(f"- **{r.customer}** — ₹{r.amount:,.0f}")

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

        lines = ["**Top 5 Customers by Revenue**\n"]
        for i, r in enumerate(rows, 1):
            lines.append(f"{i}. **{r.customer}** — ₹{r.total:,.0f} ({r.invoices} invoices)")

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
        lines = [f"**Low Stock Items** ({len(low)} products at ≤ 10 units)\n"]

        for item in low:
            lines.append(
                f"- **{item.product_name}** — {item.stock} units left"
                f"{f'  |  Supplier: {item.supplier}' if item.supplier else ''}"
            )
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
        lines = [f"**Expiring Within 30 Days** ({len(expiring)} products)\n"]

        for item, exp in expiring:
            days_left = (exp - today).days
            lines.append(
                f"- **{item.product_name}** — expires {item.expiry_date}"
                f"  ({days_left} day{'s' if days_left != 1 else ''} left)"
                f"{f'  |  Stock: {item.stock}' if item.stock is not None else ''}"
            )
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
            db.query(Invoice.customer, func.sum(Invoice.amount).label("t"))
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
            f"- {top.customer} — ₹{top.t:,.0f}" if top else ""
        )
    finally:
        db.close()