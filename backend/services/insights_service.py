"""
services/insights_service.py
=============================
Business logic for the /insights, /database, /dashboard-* endpoints.
Routes call these functions and return the result directly.
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database.models import Invoice, Inventory, LegacyPayment, UploadedFile, DocumentEmbedding, ChatMessage
from services.dates import biz_today_str, biz_now

logger = logging.getLogger("bizassist.insights_service")


def parse_date(date_str):
    # Delegates to the single shared parser (H3); kept as a thin alias so
    # existing callers in this module are unaffected.
    from services.dates import parse_date as _parse_date
    return _parse_date(date_str)


def low_stock_products(db: Session, business_id: int) -> list[tuple]:
    """Products at or below their restock floor. ONE definition, two callers.

    Stock is per PRODUCT, summed from `stock_ledger` — the append-only truth —
    not from `inventory`, which holds one row per BATCH and is a cached
    projection. Counting batches makes a well-stocked product with three
    sold-through batches look like three stockouts; that is exactly what the
    notification bell did on its first day, while this dashboard, on the same
    data, correctly reported none.

    The floor is the product's own `attributes.min_stock` when the merchant set
    one, else the business's configured `low_stock_threshold` (10 by default).
    That fallback used to be 0, which meant the "needs restocking" panel stayed
    empty until a product hit exactly zero — by which point restocking is late,
    and for the many businesses that never set a per-product minimum the panel
    never said anything at all. A warning that only fires at zero is a warning
    that arrives after the sale is lost.

    Returns [(name, qty, floor)] sorted lowest first.
    """
    import json as _json
    from sqlalchemy import func as _func
    from database.models import Product, AlertConfig
    from core.models import StockLedger

    cfg = db.query(AlertConfig).filter(AlertConfig.business_id == business_id).first()
    default_floor = float((cfg.low_stock_threshold if cfg else None) or 10)

    stock_by_pid = dict(
        db.query(StockLedger.product_id,
                 _func.coalesce(_func.sum(StockLedger.qty_delta), 0.0))
        .filter(StockLedger.business_id == business_id)
        .group_by(StockLedger.product_id)
        .all()
    )

    rows = []
    for p in db.query(Product).filter(Product.business_id == business_id).all():
        if not p.track_inventory:      # services / prepared food hold no stock
            continue
        qty = float(stock_by_pid.get(p.id) or 0.0)
        floor = None
        if p.attributes:
            try:
                floor = float(_json.loads(p.attributes).get("min_stock") or 0.0) or None
            except Exception:
                floor = None
        if floor is None:
            floor = default_floor
        if qty <= floor:
            rows.append((p.name, qty, floor))

    rows.sort(key=lambda r: r[1])
    return rows


def expiring_batches(db: Session, business_id: int, days: int = None):
    """Batches gone off, and batches about to. ONE definition, three callers.

    Unlike stock levels, this IS per batch: expiry belongs to the lot, not to
    the product, so `inventory` is the right table here and summing it would
    destroy the very thing being asked about.

    Three things the scheduled email got wrong and this fixes:

      1. `datetime.today()` is the SERVER's wall clock. Expiry is a merchant
         question — a batch expiring "today" in Kolkata is not expiring today on
         a UTC host, and the alert fired on the wrong side of midnight. Uses
         `biz_now()`, which is what that helper exists for.
      2. The window was `0 <= days_left <= days`, so a batch that had ALREADY
         expired fell out of it and was never mentioned again. The one state
         where the owner most needs telling was the one state that was silent.
      3. Sold-out batches counted. A lot with zero stock cannot spoil; including
         it makes the warning permanent, and a permanent warning is furniture.

    `days` defaults to the business's configured `expiry_days_threshold` (30).
    Returns (expired, expiring), each [(name, expiry_date, days_left)] soonest
    first — `days_left` is negative for the expired.
    """
    from database.models import AlertConfig
    from services.dates import parse_date_only, biz_now

    if days is None:
        cfg = db.query(AlertConfig).filter(AlertConfig.business_id == business_id).first()
        days = int((cfg.expiry_days_threshold if cfg else None) or 30)

    today = biz_now().date()
    expired, expiring = [], []
    rows = (
        db.query(Inventory)
        .filter(Inventory.business_id == business_id,
                Inventory.expiry_date != None)          # noqa: E711 — SQL NULL
        .all()
    )
    for item in rows:
        exp = parse_date_only(item.expiry_date)
        if exp is None or (item.stock or 0) <= 0:
            continue
        left = (exp - today).days
        if left < 0:
            expired.append((item.product_name, item.expiry_date, left))
        elif left <= days:
            expiring.append((item.product_name, item.expiry_date, left))

    expired.sort(key=lambda r: r[2])          # longest expired first
    expiring.sort(key=lambda r: r[2])         # soonest first
    return expired, expiring


def business_insights(user_id: int, db: Session) -> dict:
    insights = []
    overdue = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Overdue").all()
    total_overdue = sum(i.amount or 0 for i in overdue)
    if total_overdue > 0:
        insights.append({"type": "overdue", "message": f"₹{total_overdue} is currently overdue across {len(overdue)} invoices."})

    pending = db.query(Invoice).filter(Invoice.business_id == user_id, Invoice.status == "Pending").all()
    if pending:
        insights.append({"type": "pending", "message": str(len(pending)) + " invoices are pending payment."})

    expiring = [i for i in db.query(Inventory).filter(Inventory.business_id == user_id).all() if i.expiry_date]
    if expiring:
        insights.append({"type": "expiry", "message": str(len(expiring)) + " products have expiry tracking enabled."})

    invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()
    total_rev = sum(i.amount or 0 for i in invoices)
    insights.append({"type": "revenue", "message": f"Total tracked revenue is ₹{total_rev}"})

    return {"total_insights": len(insights), "insights": insights}


def uploads_list(user_id: int, db: Session) -> list:
    uploads = db.query(UploadedFile).filter(UploadedFile.business_id == user_id).order_by(UploadedFile.id.desc()).all()
    return [{"id": f.id, "filename": f.filename, "type": f.file_type, "rows": f.rows_count, "uploaded": f.upload_time} for f in uploads]


def dashboard_summary(user_id: int, db: Session) -> dict:
    from datetime import datetime, timedelta
    from database.models import Invoice, Product, PurchaseInvoice, Customer
    from core.models import InvoicePayment, StockLedger
    from sqlalchemy import func as _func
    import json
    
    invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()
    products = db.query(Product).filter(Product.business_id == user_id).all()
    
    valid_invoices = [i for i in invoices if i.status not in ("Draft", "Cancelled")]
    total_revenue = sum(i.total_amount or 0 for i in valid_invoices)
    invoice_count = len(valid_invoices)
    
    # Use biz_today_str() / biz_now() so IST-local dates match what the counter
    # stamps on invoices and payments. datetime.now() is server-local (UTC on
    # the HF instance) and would miscount bills from 00:00–05:30 IST as
    # "yesterday". This is the same IST-aware function used everywhere else.
    today_str = biz_today_str()
    thirty_days_ago = (biz_now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    rev_30d = sum(i.total_amount or 0 for i in valid_invoices if i.invoice_date and i.invoice_date >= thirty_days_ago)
    
    pending_invoices = [i for i in valid_invoices if i.status == "Pending"]
    pending_count = len(pending_invoices)
    pending_amount = sum((i.total_amount or 0) - (i.paid_amount or 0) for i in pending_invoices)
    
    payments_today = db.query(InvoicePayment).filter(
        InvoicePayment.business_id == user_id,
        InvoicePayment.payment_date == today_str
    ).all()
    paid_today = sum(p.amount_paid or 0.0 for p in payments_today)
    
    overdue_invoices = [i for i in valid_invoices if i.status == "Overdue"]
    overdue_count = len(overdue_invoices)
    overdue_amount = sum((i.total_amount or 0) - (i.paid_amount or 0) for i in overdue_invoices)
    
    purchases = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.business_id == user_id,
        PurchaseInvoice.invoice_date >= thirty_days_ago
    ).all()
    purchases_30d = sum(p.total_amount or 0.0 for p in purchases)
    
    active_cust_set = {i.customer for i in valid_invoices if i.invoice_date and i.invoice_date >= thirty_days_ago and i.customer}
    active_customers = len(active_cust_set)
    
    gross_margin = 0.0
    if rev_30d > 0:
        gross_margin = round(max(-999.0, ((rev_30d - purchases_30d) / rev_30d) * 100), 1)
    
    # Shared with the notification bell so the two can never disagree — they
    # were on screen together saying "0 need restocking" and "3 out of stock".
    # See low_stock_products() for why stock is per product, from the ledger.
    _low = low_stock_products(db, user_id)
    low_stock_count = len(_low)
    low_stock_items = [
        {"name": name, "quantity": qty, "min_stock": floor}
        for name, qty, floor in _low[:5]
    ]
    
    recent_invoices_db = sorted(valid_invoices, key=lambda i: (i.invoice_date or "", i.id), reverse=True)[:5]
    recent_invoices = []
    for i in recent_invoices_db:
        recent_invoices.append({
            "id": i.id,
            "invoice_number": i.invoice_id,
            "customer_name": i.customer or "Cash Customer",
            "total_amount": i.total_amount,
            "status": i.status
        })
        
    return {
        "total_revenue": total_revenue,
        "invoice_count": invoice_count,
        "inventory_count": len(products),
        "overdue_amount": overdue_amount,
        "pending_invoices": pending_count,
        
        "revenue_30d": rev_30d,
        "pending_count": pending_count,
        "pending_amount": pending_amount,
        "paid_today": paid_today,
        "overdue_count": overdue_count,
        "low_stock_count": low_stock_count,
        "purchases_30d": purchases_30d,
        "active_customers": active_customers,
        "gross_margin": gross_margin,
        "recent_invoices": recent_invoices,
        "low_stock_items": low_stock_items
    }


def database_view(user_id: int, db: Session) -> dict:
    invoices  = db.query(Invoice).filter(Invoice.business_id == user_id).all()
    inventory = db.query(Inventory).filter(Inventory.business_id == user_id).all()
    uploads   = db.query(UploadedFile).filter(UploadedFile.business_id == user_id).all()
    payments  = db.query(LegacyPayment).filter(LegacyPayment.business_id == user_id).all()
    msgs      = db.query(ChatMessage).filter(ChatMessage.business_id == user_id).order_by(ChatMessage.timestamp.desc()).all()

    return {
        "invoice_count":   len(invoices),
        "inventory_count": len(inventory),
        "upload_count":    len(uploads),
        "payment_count":   len(payments),
        "invoices": [
            {"id": i.id, "invoice_id": i.invoice_id, "customer": i.customer, "product": i.product,
             "amount": i.amount, "status": i.status, "invoice_date": i.invoice_date, "due_date": i.due_date,
             "paid_amount": i.paid_amount or 0.0, "total_amount": i.total_amount or i.amount or 0.0}
            for i in invoices
        ],
        "inventory": [
            {"id": it.id, "product": it.product_name, "product_name": it.product_name,
             "stock": it.stock, "expiry": it.expiry_date, "expiry_date": it.expiry_date, "supplier": it.supplier}
            for it in inventory
        ],
        "uploads": [
            {"id": u.id, "filename": u.filename, "type": u.file_type, "file_type": u.file_type,
             "rows": u.rows_count, "rows_count": u.rows_count, "uploaded": u.upload_time, "upload_time": u.upload_time}
            for u in uploads
        ],
        "payments": [
            {"id": p.id, "customer": p.customer, "amount": p.amount, "due_date": p.due_date, "paid": p.paid}
            for p in payments
        ],
        "chat_history": [
            {"id": m.id, "role": m.role, "content": m.content, "session_id": m.session_id,
             "session_title": m.session_title,
             "timestamp": m.timestamp.isoformat() if m.timestamp else None}
            for m in msgs
        ],
    }


def wipe_database(user_id: int, db: Session) -> dict:
    invoice_count  = db.query(Invoice).filter(Invoice.business_id == user_id).count()
    inventory_count = db.query(Inventory).filter(Inventory.business_id == user_id).count()
    upload_count   = db.query(UploadedFile).filter(UploadedFile.business_id == user_id).count()

    db.query(Invoice).filter(Invoice.business_id == user_id).delete()
    db.query(Inventory).filter(Inventory.business_id == user_id).delete()
    db.query(LegacyPayment).filter(LegacyPayment.business_id == user_id).delete()
    db.query(UploadedFile).filter(UploadedFile.business_id == user_id).delete()
    db.query(DocumentEmbedding).filter(DocumentEmbedding.business_id == user_id).delete()
    db.commit()

    from services.context_cache import invalidate_user_cache
    invalidate_user_cache(user_id)

    return {"message": "Database deleted successfully",
            "deleted": {"invoices": invoice_count, "inventory": inventory_count, "uploads": upload_count}}


def top_customers(user_id: int, db: Session, limit: int = 5) -> list:
    invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()
    totals = {}
    for inv in invoices:
        c = inv.customer or "Unknown"
        totals[c] = (totals.get(c) or 0) + (inv.amount or 0)
    return [{"customer": c, "total": t} for c, t in sorted(totals.items(), key=lambda x: x[1], reverse=True)[:limit]]




def clients_view(user_id: int, db: Session) -> dict:
    invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()
    clients = {}
    for inv in invoices:
        c = inv.customer or "Unknown"
        if c not in clients:
            clients[c] = {"customer": c, "total": 0, "invoices": 0, "paid": 0, "pending": 0, "overdue": 0}
        clients[c]["total"]    += inv.amount or 0
        clients[c]["invoices"] += 1
        s = (inv.status or "").lower()
        if s == "paid":      clients[c]["paid"]    += 1
        elif s == "pending": clients[c]["pending"] += 1
        elif s == "overdue": clients[c]["overdue"] += 1
    sorted_clients = sorted(clients.values(), key=lambda x: x["total"], reverse=True)
    return {"clients": sorted_clients, "total_clients": len(sorted_clients)}


def delete_upload(user_id: int, upload_id: int, db: Session) -> dict:
    upload = db.query(UploadedFile).filter(UploadedFile.id == upload_id, UploadedFile.business_id == user_id).first()
    if not upload:
        return {"error": "Upload not found"}

    ft = upload.file_type
    if ft == "invoice":
        db.query(Invoice).filter(Invoice.file_id == upload_id, Invoice.business_id == user_id).delete()
    elif ft == "inventory":
        db.query(Inventory).filter(Inventory.file_id == upload_id, Inventory.business_id == user_id).delete()
    elif ft == "payment":
        db.query(LegacyPayment).filter(LegacyPayment.file_id == upload_id, LegacyPayment.business_id == user_id).delete()

    db.delete(upload)
    db.commit()

    from services.context_cache import invalidate_user_cache
    invalidate_user_cache(user_id)
    return {"message": "Upload deleted successfully"}


def dashboard_charts(user_id: int, db: Session) -> dict:
    """Current invoice totals and remaining receivables, including returns.

    Status labels are not balances: a partially paid overdue invoice contributes
    only what is still owed. A credit note reduces sales and is never a bill due.
    """
    from database.models import InvoiceLineItem

    invoices = [inv for inv in db.query(Invoice).filter(Invoice.business_id == user_id).all()
                if (inv.status or "").lower() not in {"cancelled", "canceled", "void", "draft"}]
    ids = [inv.id for inv in invoices]
    lines_by_invoice = {}
    if ids:
        for line in db.query(InvoiceLineItem).filter(InvoiceLineItem.invoice_id.in_(ids)).all():
            lines_by_invoice.setdefault(line.invoice_id, []).append(line)
    monthly, product_totals = {}, {}
    aging = {"0-30 days": 0.0, "31-60 days": 0.0, "61-90 days": 0.0, "90+ days": 0.0}
    today = biz_now().date()
    for inv in invoices:
        total = float(inv.total_amount if inv.total_amount is not None else (inv.amount or 0))
        sign = -1 if inv.invoice_type == "credit_note" else 1
        date = parse_date(inv.invoice_date)
        if date:
            key = date.strftime("%Y-%m")
            period = monthly.setdefault(key, {"month": date.strftime("%b %y"), "revenue": 0.0})
            period["revenue"] += sign * total
        due_date = parse_date(inv.due_date)
        paid = float(inv.paid_amount or 0)
        legacy_paid = inv.paid_amount is None and (inv.status or "").lower() == "paid"
        due = 0.0 if sign < 0 or legacy_paid else max(total - paid, 0.0)
        if due_date and due > 0:
            days = (today - due_date.date()).days
            if days > 0:
                bucket = "0-30 days" if days <= 30 else "31-60 days" if days <= 60 else "61-90 days" if days <= 90 else "90+ days"
                aging[bucket] += due
        lines = lines_by_invoice.get(inv.id, [])
        line_sum = sum(float(line.line_total or 0) for line in lines)
        if lines and line_sum > 0:
            for line in lines:
                name = line.product_name or "Other sales"
                product_totals[name] = product_totals.get(name, 0.0) + sign * total * float(line.line_total or 0) / line_sum
        else:
            name = inv.product or "Other sales"
            product_totals[name] = product_totals.get(name, 0.0) + sign * total
    return {
        "monthly_revenue": [{**monthly[key], "revenue": round(monthly[key]["revenue"], 2)} for key in sorted(monthly)],
        "aging_overview": [{"range": key, "amount": round(value, 2)} for key, value in aging.items()],
        "top_products": [{"name": name, "value": round(value, 2)}
                         for name, value in sorted(product_totals.items(), key=lambda item: item[1], reverse=True)[:5]],
    }
