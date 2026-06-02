import logging
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
from datetime import datetime

router = APIRouter()
logger = logging.getLogger("bizassist.insights")

# ===================================
# BUSINESS INSIGHTS
# ===================================

@router.get("/insights")
def get_business_insights(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    logger.info(f"User {active_user_id} fetching business insights...")
    db = SessionLocal()
    try:
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

        logger.info(f"User {active_user_id} successfully retrieved {len(insights)} business insights.")
        return {
            "total_insights": len(insights),
            "insights": insights
        }
    except Exception as e:
        logger.error(f"Error fetching insights for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch business insights")
    finally:
        db.close()

# ===================================
# UPLOAD HISTORY
# ===================================

@router.get("/uploads")
def get_uploads(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    logger.info(f"User {active_user_id} fetching uploads list...")
    db = SessionLocal()
    try:
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

        logger.info(f"User {active_user_id} successfully retrieved {len(result)} upload files.")
        return result
    except Exception as e:
        logger.error(f"Error fetching uploads for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch uploads list")
    finally:
        db.close()

# ===================================
# DASHBOARD SUMMARY
# ===================================

@router.get("/dashboard-summary")
def dashboard_summary(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    logger.info(f"User {active_user_id} fetching dashboard summary...")
    db = SessionLocal()
    try:
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

        logger.info(f"Dashboard summary generated for user {active_user_id}: Revenue={total_revenue}, Invoices={len(invoices)}, Overdue={overdue_amount}, Pending={pending_count}, Inventory={len(inventory)}")
        return summary
    except Exception as e:
        logger.error(f"Error generating dashboard summary for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate dashboard summary")
    finally:
        db.close()

# ===================================
# DATABASE VIEWER
# ===================================

@router.get("/database")
def get_database(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    logger.info(f"User {active_user_id} requesting database tables state...")
    db = SessionLocal()
    try:
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

        logger.info(f"Database state successfully fetched for user {active_user_id}. Invoices={len(invoices)}, Inventory={len(inventory)}, Uploads={len(uploads)}")
        return database_data
    except Exception as e:
        logger.error(f"Error retrieving database state for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve database state")
    finally:
        db.close()

# ===================================
# DELETE ENTIRE DATABASE
# ===================================

@router.delete("/database/delete")
def delete_entire_database(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    logger.warning(f"User {active_user_id} has requested full database wipe!")
    db = SessionLocal()
    
    try:
        # Count deleted records
        invoice_count = db.query(Invoice).filter(Invoice.business_id == active_user_id).count()
        inventory_count = db.query(Inventory).filter(Inventory.business_id == active_user_id).count()
        upload_count = db.query(UploadedFile).filter(UploadedFile.business_id == active_user_id).count()
        
        logger.info(f"Wiping user {active_user_id} data: {invoice_count} invoices, {inventory_count} inventory, {upload_count} uploads...")

        # Delete all records
        db.query(Invoice).filter(Invoice.business_id == active_user_id).delete()
        db.query(Inventory).filter(Inventory.business_id == active_user_id).delete()
        db.query(Payment).filter(Payment.business_id == active_user_id).delete()
        db.query(UploadedFile).filter(UploadedFile.business_id == active_user_id).delete()
        
        db.commit()
        logger.info(f"Database wipe successful for user {active_user_id}. All records deleted and committed.")
        
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
        logger.error(f"Failed to wipe database for user {active_user_id}: {str(e)}", exc_info=True)
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
    logger.info(f"User {active_user_id} fetching top customers list...")
    db = SessionLocal()
    try:
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

        logger.info(f"Top customers successfully fetched for user {active_user_id}. Found {len(sorted_customers)} distinct customers.")
        return result
    except Exception as e:
        logger.error(f"Error fetching top customers for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch top customers")
    finally:
        db.close()

# ===================================
# PAYMENTS
# ===================================

@router.get("/payments")
def get_payments(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    logger.info(f"User {active_user_id} fetching payments database records...")
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

        logger.info(f"Payments query returned {len(payment_records)} records, {len(invoice_pending)} pending invoices for user {active_user_id}.")
        return {
            "payments":      payment_records,
            "invoice_dues":  invoice_pending,
            "total_overdue": total_overdue,
            "total_pending": total_pending,
            "overdue_count": sum(1 for inv in invoices if inv.status == "Overdue"),
            "pending_count": sum(1 for inv in invoices if inv.status == "Pending"),
        }
    except Exception as e:
        logger.error(f"Error fetching payments for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch payments database records")
    finally:
        db.close()

# ===================================
# CLIENTS
# ===================================

@router.get("/clients")
def get_clients(authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    logger.info(f"User {active_user_id} fetching client list metrics...")
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

        logger.info(f"Clients query returned {len(sorted_clients)} records for user {active_user_id}.")
        return {
            "clients":       sorted_clients,
            "total_clients": len(sorted_clients),
        }
    except Exception as e:
        logger.error(f"Error fetching clients list for user {active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch clients list metrics")
    finally:
        db.close()

# ===================================
# DELETE UPLOAD
# ===================================

@router.delete("/delete-upload/{upload_id}")
def delete_upload(upload_id: int, authorization: str = Header(None)):
    user = get_active_user(authorization)
    active_user_id = user["id"]
    logger.info(f"User {active_user_id} deleting upload file ID {upload_id} from insights...")
    db = SessionLocal()

    try:
        upload = db.query(UploadedFile).filter(
            UploadedFile.id == upload_id,
            UploadedFile.business_id == active_user_id
        ).first()

        if not upload:
            logger.warning(f"File ID {upload_id} not found or doesn't belong to user {active_user_id}")
            db.close()
            return {
                "error": "Upload not found"
            }

        file_type = upload.file_type
        logger.info(f"Deleting upload database associations for file '{upload.filename}' type '{file_type}'...")

        # Delete all database records parsed from this specific file
        if file_type == "invoice":
            deleted = db.query(Invoice).filter(
                Invoice.file_id == upload_id,
                Invoice.business_id == active_user_id
            ).delete()
            logger.info(f"Deleted {deleted} associated invoices.")
        elif file_type == "inventory":
            deleted = db.query(Inventory).filter(
                Inventory.file_id == upload_id,
                Inventory.business_id == active_user_id
            ).delete()
            logger.info(f"Deleted {deleted} associated inventory records.")
        elif file_type == "payment":
            deleted = db.query(Payment).filter(
                Payment.file_id == upload_id,
                Payment.business_id == active_user_id
            ).delete()
            logger.info(f"Deleted {deleted} associated payments.")

        db.delete(upload)
        db.commit()
        logger.info(f"Successfully deleted file upload ID {upload_id} from insights.")
        
        # Invalidate cache
        from services.context_cache import invalidate
        invalidate()

        return {
            "message": "Upload deleted successfully"
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting upload file ID {upload_id} for user {active_user_id}: {str(e)}", exc_info=True)
        return {
            "error": str(e),
            "message": "Failed to delete upload"
        }
    finally:
        db.close()

# ===================================
# DASHBOARD CHARTS DATA
# ===================================

def parse_date(date_str):
    if not date_str or str(date_str).strip() == "":
        return None
    # Strip any time component if present
    date_str = str(date_str).strip().split(" ")[0].split("T")[0]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

@router.get("/dashboard-charts")
def dashboard_charts(authorization: str = Header(None)):
    """
    Computes business data aggregations to build dashboard interactive charts.
    Calculates:
      1. Monthly revenue trends sorted chronologically.
      2. Invoice debt aging ranges (0-30, 31-60, 61-90, 90+ days overdue).
      3. Top product sales distribution.
    """
    user = get_active_user(authorization)
    active_user_id = user["id"]
    db = SessionLocal()
    
    logger.info(f"Generating dashboard charts data for user_id={active_user_id}...")
    try:
        invoices = db.query(Invoice).filter(
            Invoice.business_id == active_user_id
        ).all()
        
        # 1. Monthly Revenue Trends (grouped by Year-Month)
        monthly_rev = {}
        for inv in invoices:
            dt = parse_date(inv.invoice_date)
            if dt:
                ym_key = dt.strftime("%Y-%m")
                month_name = dt.strftime("%b %y")
                amount = inv.amount or 0
                if ym_key not in monthly_rev:
                    monthly_rev[ym_key] = {"month": month_name, "revenue": 0}
                monthly_rev[ym_key]["revenue"] += amount
                
        sorted_monthly = [monthly_rev[k] for k in sorted(monthly_rev.keys())]
        
        # Fallback empty state
        if not sorted_monthly:
            sorted_monthly = [
                {"month": "Jan", "revenue": 0},
                {"month": "Feb", "revenue": 0},
                {"month": "Mar", "revenue": 0}
            ]
            
        # 2. Invoice Aging (Group outstanding invoices by days overdue compared to today)
        now = datetime.now()
        aging = {
            "0-30 days": 0,
            "31-60 days": 0,
            "61-90 days": 0,
            "90+ days": 0
        }
        
        for inv in invoices:
            if inv.status in ("Overdue", "Pending"):
                due_dt = parse_date(inv.due_date)
                if due_dt:
                    delta = (now - due_dt).days
                    amount = inv.amount or 0
                    if delta <= 0:
                        continue
                    elif delta <= 30:
                        aging["0-30 days"] += amount
                    elif delta <= 60:
                        aging["31-60 days"] += amount
                    elif delta <= 90:
                        aging["61-90 days"] += amount
                    else:
                        aging["90+ days"] += amount
                        
        aging_list = [{"range": k, "amount": v} for k, v in aging.items()]
        
        # 3. Product Sales / Category breakdown (top 5 categories by total revenue)
        product_totals = {}
        for inv in invoices:
            prod = inv.product or "Services"
            amount = inv.amount or 0
            if prod not in product_totals:
                product_totals[prod] = 0
            product_totals[prod] += amount
            
        sorted_products = sorted(product_totals.items(), key=lambda x: x[1], reverse=True)
        top_products = [{"name": name, "value": val} for name, val in sorted_products[:5]]
        
        if not top_products:
            top_products = [{"name": "No data", "value": 0}]
            
        logger.info(f"Dashboard charts data successfully generated for user_id={active_user_id}.")
        return {
            "monthly_revenue": sorted_monthly,
            "aging_overview": aging_list,
            "top_products": top_products
        }
    except Exception as e:
        logger.error(f"Failed to generate dashboard charts for user_id={active_user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch dashboard data.")
    finally:
        db.close()