from fastapi import APIRouter, Header, HTTPException
from database.db import SessionLocal
from database.models import (
    Invoice,
    Inventory,
    Payment,
    UploadedFile
)
from sqlalchemy import func
from services.auth import get_active_user

router = APIRouter()

# ===================================
# BUSINESS INSIGHTS
# ===================================

@router.get("/insights")
def get_business_insights(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    db = SessionLocal()
    insights = []

    # Overdue analysis
    overdue = db.query(Invoice).filter(
        Invoice.business_id == active_user_id,
        Invoice.status == "Overdue"
    ).all()

    total_overdue = sum(invoice.amount or 0 for invoice in overdue)

    if total_overdue > 0:
        insights.append({
            "type": "overdue",
            "message": f"₹{total_overdue} is currently overdue across {len(overdue)} invoices."
        })

    # Pending payments
    pending = db.query(Invoice).filter(
        Invoice.business_id == active_user_id,
        Invoice.status == "Pending"
    ).all()

    if len(pending) > 0:
        insights.append({
            "type": "pending",
            "message": f"{len(pending)} invoices are pending payment."
        })

    # Inventory expiry
    inventory = db.query(Inventory).filter(
        Inventory.business_id == active_user_id
    ).all()

    expiring = [item for item in inventory if item.expiry_date]

    if len(expiring) > 0:
        insights.append({
            "type": "expiry",
            "message": f"{len(expiring)} products have expiry tracking enabled."
        })

    # Revenue summary
    invoices = db.query(Invoice).filter(
        Invoice.business_id == active_user_id
    ).all()

    total_revenue = sum(invoice.amount or 0 for invoice in invoices)

    insights.append({
        "type": "revenue",
        "message": f"Total tracked revenue is ₹{total_revenue}"
    })

    db.close()
    return {
        "total_insights": len(insights),
        "insights": insights
    }

# ===================================
# UPLOAD HISTORY
# ===================================

@router.get("/uploads")
def get_uploads(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    db = SessionLocal()

    uploads = db.query(UploadedFile).filter(
        UploadedFile.business_id == active_user_id
    ).order_by(
        UploadedFile.id.desc()
    ).all()

    result = []
    for file in uploads:
        result.append({
            "id": file.id,
            "filename": file.filename,
            "type": file.file_type,
            "rows": file.rows_count,
            "uploaded": file.upload_time
        })

    db.close()
    return result

# ===================================
# DASHBOARD SUMMARY
# ===================================

@router.get("/dashboard-summary")
def dashboard_summary(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    db = SessionLocal()

    invoices = db.query(Invoice).filter(
        Invoice.business_id == active_user_id
    ).all()

    inventory = db.query(Inventory).filter(
        Inventory.business_id == active_user_id
    ).all()

    total_revenue = sum(invoice.amount or 0 for invoice in invoices)
    overdue_amount = sum(invoice.amount or 0 for invoice in invoices if invoice.status == "Overdue")
    pending_count = len([invoice for invoice in invoices if invoice.status == "Pending"])

    summary = {
        "total_revenue": total_revenue,
        "invoice_count": len(invoices),
        "overdue_amount": overdue_amount,
        "pending_invoices": pending_count,
        "inventory_count": len(inventory)
    }

    db.close()
    return summary

# ===================================
# DATABASE VIEWER
# ===================================

@router.get("/database")
def get_database(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    db = SessionLocal()

    invoices = db.query(Invoice).filter(
        Invoice.business_id == active_user_id
    ).all()

    inventory = db.query(Inventory).filter(
        Inventory.business_id == active_user_id
    ).all()

    uploads = db.query(UploadedFile).filter(
        UploadedFile.business_id == active_user_id
    ).all()

    database_data = {
        "invoice_count": len(invoices),
        "inventory_count": len(inventory),
        "upload_count": len(uploads),
        "invoices": [
            {
                "id": invoice.id,
                "customer": invoice.customer,
                "amount": invoice.amount,
                "status": invoice.status,
                "invoice_id": invoice.invoice_id
            }
            for invoice in invoices[:50]
        ],
        "inventory": [
            {
                "id": item.id,
                "product": item.product_name,
                "stock": item.stock,
                "expiry": item.expiry_date
            }
            for item in inventory[:50]
        ],
        "uploads": [
            {
                "id": upload.id,
                "filename": upload.filename,
                "type": upload.file_type,
                "rows": upload.rows_count,
                "uploaded": upload.upload_time
            }
            for upload in uploads
        ]
    }

    db.close()
    return database_data

# ===================================
# DELETE ENTIRE DATABASE
# ===================================

@router.delete("/database/delete")
def delete_entire_database(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    db = SessionLocal()
    
    try:
        # Count deleted records
        invoice_count = db.query(Invoice).filter(Invoice.business_id == active_user_id).count()
        inventory_count = db.query(Inventory).filter(Inventory.business_id == active_user_id).count()
        upload_count = db.query(UploadedFile).filter(UploadedFile.business_id == active_user_id).count()
        
        # Delete all records
        db.query(Invoice).filter(Invoice.business_id == active_user_id).delete()
        db.query(Inventory).filter(Inventory.business_id == active_user_id).delete()
        db.query(Payment).filter(Payment.business_id == active_user_id).delete()
        db.query(UploadedFile).filter(UploadedFile.business_id == active_user_id).delete()
        
        db.commit()
        
        # Invalidate cache
        from services.context_cache import invalidate
        invalidate()
        
        return {
            "message": "Database deleted successfully",
            "deleted": {
                "invoices": invoice_count,
                "inventory": inventory_count,
                "uploads": upload_count
            }
        }
    
    except Exception as e:
        db.rollback()
        return {
            "error": str(e),
            "message": "Failed to delete database"
        }
    
    finally:
        db.close()

# ===================================
# TOP CUSTOMERS
# ===================================

@router.get("/top-customers")
def top_customers(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    db = SessionLocal()

    invoices = db.query(Invoice).filter(
        Invoice.business_id == active_user_id
    ).all()

    customer_totals = {}
    for invoice in invoices:
        customer = invoice.customer or "Unknown"
        amount = invoice.amount or 0
        if customer not in customer_totals:
            customer_totals[customer] = 0
        customer_totals[customer] += amount

    sorted_customers = sorted(
        customer_totals.items(),
        key=lambda x: x[1],
        reverse=True
    )

    result = []
    for customer, total in sorted_customers[:5]:
        result.append({
            "customer": customer,
            "total": total
        })

    db.close()
    return result

# ===================================
# PAYMENTS
# ===================================

@router.get("/payments")
def get_payments(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    db = SessionLocal()
    try:
        payments = db.query(Payment).filter(Payment.business_id == active_user_id).all()
        invoices = db.query(Invoice).filter(
            Invoice.business_id == active_user_id,
            Invoice.status.in_(["Overdue", "Pending"])
        ).all()

        payment_records = [
            {
                "id":        p.id,
                "customer":  p.customer,
                "amount":    p.amount,
                "due_date":  p.due_date,
                "paid":      p.paid,
            }
            for p in payments
        ]

        invoice_pending = [
            {
                "id":         inv.id,
                "invoice_id": inv.invoice_id,
                "customer":   inv.customer,
                "amount":     inv.amount,
                "status":     inv.status,
                "due_date":   inv.due_date,
            }
            for inv in invoices
        ]

        total_overdue = sum(inv.amount or 0 for inv in invoices if inv.status == "Overdue")
        total_pending = sum(inv.amount or 0 for inv in invoices if inv.status == "Pending")

        return {
            "payments":      payment_records,
            "invoice_dues":  invoice_pending,
            "total_overdue": total_overdue,
            "total_pending": total_pending,
            "overdue_count": sum(1 for inv in invoices if inv.status == "Overdue"),
            "pending_count": sum(1 for inv in invoices if inv.status == "Pending"),
        }
    finally:
        db.close()

# ===================================
# CLIENTS
# ===================================

@router.get("/clients")
def get_clients(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    db = SessionLocal()
    try:
        invoices = db.query(Invoice).filter(Invoice.business_id == active_user_id).all()

        # Aggregate per customer
        clients = {}
        for inv in invoices:
            c = inv.customer or "Unknown"
            if c not in clients:
                clients[c] = {"customer": c, "total": 0, "invoices": 0,
                               "paid": 0, "pending": 0, "overdue": 0}
            clients[c]["total"]    += inv.amount or 0
            clients[c]["invoices"] += 1
            s = (inv.status or "").lower()
            if s == "paid":    clients[c]["paid"]    += 1
            elif s == "pending": clients[c]["pending"] += 1
            elif s == "overdue": clients[c]["overdue"] += 1

        sorted_clients = sorted(clients.values(), key=lambda x: x["total"], reverse=True)

        return {
            "clients":       sorted_clients,
            "total_clients": len(sorted_clients),
        }
    finally:
        db.close()

# ===================================
# DELETE UPLOAD
# ===================================

@router.delete("/delete-upload/{upload_id}")
def delete_upload(upload_id: int, authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    db = SessionLocal()

    upload = db.query(UploadedFile).filter(
        UploadedFile.id == upload_id,
        UploadedFile.business_id == active_user_id
    ).first()

    if not upload:
        db.close()
        return {
            "error": "Upload not found"
        }

    file_type = upload.file_type

    # Delete all database records parsed from this specific file
    if file_type == "invoice":
        db.query(Invoice).filter(
            Invoice.file_id == upload_id,
            Invoice.business_id == active_user_id
        ).delete()
    elif file_type == "inventory":
        db.query(Inventory).filter(
            Inventory.file_id == upload_id,
            Inventory.business_id == active_user_id
        ).delete()
    elif file_type == "payment":
        db.query(Payment).filter(
            Payment.file_id == upload_id,
            Payment.business_id == active_user_id
        ).delete()

    db.delete(upload)
    db.commit()
    db.close()

    # Invalidate cache
    from services.context_cache import invalidate
    invalidate()

    return {
        "message": "Upload deleted successfully"
    }