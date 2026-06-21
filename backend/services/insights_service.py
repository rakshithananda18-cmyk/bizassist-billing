"""
services/insights_service.py
=============================
Business logic for the /insights, /database, /dashboard-* endpoints.
Routes call these functions and return the result directly.
"""
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from database.models import Invoice, Inventory, Payment, UploadedFile, DocumentEmbedding, ChatMessage

logger = logging.getLogger("bizassist.insights_service")


def parse_date(date_str):
    # Delegates to the single shared parser (H3); kept as a thin alias so
    # existing callers in this module are unaffected.
    from services.dates import parse_date as _parse_date
    return _parse_date(date_str)


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
    from core.models import InvoicePayment
    from core.stock import ledger as SL
    import json
    
    invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()
    products = db.query(Product).filter(Product.business_id == user_id).all()
    
    total_revenue = sum(i.total_amount or 0 for i in invoices)
    invoice_count = len(invoices)
    
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    rev_30d = sum(i.total_amount or 0 for i in invoices if i.invoice_date and i.invoice_date >= thirty_days_ago)
    
    pending_invoices = [i for i in invoices if i.status == "Pending"]
    pending_count = len(pending_invoices)
    pending_amount = sum((i.total_amount or 0) - (i.paid_amount or 0) for i in pending_invoices)
    
    payments_today = db.query(InvoicePayment).filter(
        InvoicePayment.business_id == user_id,
        InvoicePayment.payment_date == today_str
    ).all()
    paid_today = sum(p.amount_paid or 0.0 for p in payments_today)
    
    overdue_invoices = [i for i in invoices if i.status == "Overdue"]
    overdue_count = len(overdue_invoices)
    overdue_amount = sum((i.total_amount or 0) - (i.paid_amount or 0) for i in overdue_invoices)
    
    purchases = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.business_id == user_id,
        PurchaseInvoice.invoice_date >= thirty_days_ago
    ).all()
    purchases_30d = sum(p.total_amount or 0.0 for p in purchases)
    
    active_cust_set = {i.customer for i in invoices if i.invoice_date and i.invoice_date >= thirty_days_ago and i.customer}
    active_customers = len(active_cust_set)
    
    low_stock_items = []
    low_stock_count = 0
    for p in products:
        if p.track_inventory:
            stock = SL.current_stock(db, user_id, product_id=p.id)
            min_s = 0.0
            if p.attributes:
                try:
                    attrs = json.loads(p.attributes)
                    min_s = float(attrs.get("min_stock") or 0.0)
                except Exception:
                    pass
            if stock <= min_s:
                low_stock_count += 1
                low_stock_items.append({
                    "name": p.name,
                    "quantity": stock,
                    "min_stock": min_s
                })
                
    low_stock_items = low_stock_items[:5]
    
    recent_invoices_db = sorted(invoices, key=lambda i: (i.invoice_date or "", i.id), reverse=True)[:5]
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
        "gross_margin": 25.0,
        "recent_invoices": recent_invoices,
        "low_stock_items": low_stock_items
    }


def database_view(user_id: int, db: Session) -> dict:
    invoices  = db.query(Invoice).filter(Invoice.business_id == user_id).all()
    inventory = db.query(Inventory).filter(Inventory.business_id == user_id).all()
    uploads   = db.query(UploadedFile).filter(UploadedFile.business_id == user_id).all()
    payments  = db.query(Payment).filter(Payment.business_id == user_id).all()
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
    db.query(Payment).filter(Payment.business_id == user_id).delete()
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


def payments_view(user_id: int, db: Session) -> dict:
    payments = db.query(Payment).filter(Payment.business_id == user_id).all()
    invoices = db.query(Invoice).filter(
        Invoice.business_id == user_id, Invoice.status.in_(["Overdue", "Pending"])
    ).all()
    return {
        "payments":      [{"id": p.id, "customer": p.customer, "amount": p.amount, "due_date": p.due_date, "paid": p.paid} for p in payments],
        "invoice_dues":  [{"id": i.id, "invoice_id": i.invoice_id, "customer": i.customer, "amount": i.amount, "status": i.status, "due_date": i.due_date} for i in invoices],
        "total_overdue": sum(i.amount or 0 for i in invoices if i.status == "Overdue"),
        "total_pending": sum(i.amount or 0 for i in invoices if i.status == "Pending"),
        "overdue_count": sum(1 for i in invoices if i.status == "Overdue"),
        "pending_count": sum(1 for i in invoices if i.status == "Pending"),
    }


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
        db.query(Payment).filter(Payment.file_id == upload_id, Payment.business_id == user_id).delete()

    db.delete(upload)
    db.commit()

    from services.context_cache import invalidate_user_cache
    invalidate_user_cache(user_id)
    return {"message": "Upload deleted successfully"}


def dashboard_charts(user_id: int, db: Session) -> dict:
    invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()

    # Monthly revenue
    monthly_rev = {}
    for inv in invoices:
        dt = parse_date(inv.invoice_date)
        if dt:
            key = dt.strftime("%Y-%m")
            if key not in monthly_rev:
                monthly_rev[key] = {"month": dt.strftime("%b %y"), "revenue": 0}
            monthly_rev[key]["revenue"] += inv.amount or 0
    sorted_monthly = [monthly_rev[k] for k in sorted(monthly_rev.keys())] or [
        {"month": "Jan", "revenue": 0}, {"month": "Feb", "revenue": 0}, {"month": "Mar", "revenue": 0}
    ]

    # Invoice aging
    now = datetime.now()
    aging = {"0-30 days": 0, "31-60 days": 0, "61-90 days": 0, "90+ days": 0}
    for inv in invoices:
        if inv.status in ("Overdue", "Pending"):
            due_dt = parse_date(inv.due_date)
            if due_dt:
                delta = (now - due_dt).days
                if delta <= 0:    continue
                elif delta <= 30: aging["0-30 days"]  += inv.amount or 0
                elif delta <= 60: aging["31-60 days"] += inv.amount or 0
                elif delta <= 90: aging["61-90 days"] += inv.amount or 0
                else:             aging["90+ days"]   += inv.amount or 0
    aging_list = [{"range": k, "amount": v} for k, v in aging.items()]

    # Product breakdown
    product_totals = {}
    for inv in invoices:
        p = inv.product or "Services"
        product_totals[p] = (product_totals.get(p) or 0) + (inv.amount or 0)
    top_products = [{"name": n, "value": v} for n, v in sorted(product_totals.items(), key=lambda x: x[1], reverse=True)[:5]]
    if not top_products:
        top_products = [{"name": "No data", "value": 0}]

    return {"monthly_revenue": sorted_monthly, "aging_overview": aging_list, "top_products": top_products}
