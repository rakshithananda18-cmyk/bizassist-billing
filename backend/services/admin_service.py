"""
services/admin_service.py
==========================
Business logic for admin endpoints.
Routes call these functions; all DB/logic lives here.
"""
import logging
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import HTTPException
from database.models import (
    User, Invoice, InvoiceLineItem, Inventory, Payment, UploadedFile,
    DocumentEmbedding, ChatMessage, TokenUsage, RateLimitConfig,
    Customer, Vendor, Product, PurchaseOrder, PurchaseOrderLineItem,
    PurchaseInvoice, PurchaseInvoiceLineItem, Feedback, QueryOverride,
    BusinessFact, AlertConfig
)
from core.models import (
    StockLedger, ProductBarcode, BusinessSettings, InvoicePayment,
    B2BConnection, ConnectionCode, B2BOrder, B2BOrderLineItem,
    SharedLedger, Expense, Godown, StockTransfer, StockTransferLineItem,
    JournalEntry, JournalLine, PeriodLock
)
from services.auth import hash_password
from services.context_cache import invalidate, invalidate_user_cache, get_cache_stats
from services.rate_limiter import get_usage_summary

logger = logging.getLogger("bizassist.admin_service")


def require_admin(user_id: int, db: Session) -> User:
    """Raises 403 if the current user is not an admin. Returns the admin User row."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u or u.role != "admin":
        logger.warning(f"[AUTH] Admin access denied for user_id={user_id} (role={getattr(u, 'role', None)})")
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
    return u


def require_target_user(user_id: int, db: Session) -> User:
    """Raises 404 if target user does not exist."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


def list_businesses(db: Session) -> list:
    businesses = db.query(User).filter(User.role == "enterprise").all()
    result = []
    for b in businesses:
        result.append({
            "id":              b.id,
            "username":        b.username,
            "business_name":   b.business_name,
            "invoice_count":   db.query(Invoice).filter(Invoice.business_id == b.id).count(),
            "total_revenue":   db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == b.id).scalar() or 0,
            "inventory_count": db.query(Inventory).filter(Inventory.business_id == b.id).count(),
            "upload_count":    db.query(UploadedFile).filter(UploadedFile.business_id == b.id).count(),
        })
    return result


def wipe_all_data(db: Session) -> dict:
    db.query(Invoice).delete()
    db.query(Inventory).delete()
    db.query(Payment).delete()
    db.query(UploadedFile).delete()
    db.query(DocumentEmbedding).delete()
    db.query(ChatMessage).delete()
    db.commit()
    invalidate()
    return {"status": "success", "message": "All business data deleted and cache flushed."}


def wipe_user_data(user_id: int, db: Session) -> dict:
    target = require_target_user(user_id, db)
    
    # 1. Delete child lines that do NOT have business_id directly
    db.query(InvoiceLineItem).filter(
        InvoiceLineItem.invoice_id.in_(
            db.query(Invoice.id).filter(Invoice.business_id == user_id)
        )
    ).delete(synchronize_session=False)
    
    db.query(PurchaseInvoiceLineItem).filter(
        PurchaseInvoiceLineItem.purchase_invoice_id.in_(
            db.query(PurchaseInvoice.id).filter(PurchaseInvoice.business_id == user_id)
        )
    ).delete(synchronize_session=False)
    
    db.query(PurchaseOrderLineItem).filter(
        PurchaseOrderLineItem.purchase_order_id.in_(
            db.query(PurchaseOrder.id).filter(PurchaseOrder.business_id == user_id)
        )
    ).delete(synchronize_session=False)
    
    db.query(B2BOrderLineItem).filter(
        B2BOrderLineItem.order_id.in_(
            db.query(B2BOrder.id).filter(
                (B2BOrder.seller_business_id == user_id) | (B2BOrder.buyer_business_id == user_id)
            )
        )
    ).delete(synchronize_session=False)
    
    db.query(JournalLine).filter(
        JournalLine.entry_id.in_(
            db.query(JournalEntry.id).filter(JournalEntry.business_id == user_id)
        )
    ).delete(synchronize_session=False)
    
    db.query(StockTransferLineItem).filter(
        StockTransferLineItem.transfer_id.in_(
            db.query(StockTransfer.id).filter(StockTransfer.business_id == user_id)
        )
    ).delete(synchronize_session=False)
    
    db.query(ProductBarcode).filter(
        ProductBarcode.product_id.in_(
            db.query(Product.id).filter(Product.business_id == user_id)
        )
    ).delete(synchronize_session=False)

    # 2. Delete parent records in correct dependency order
    db.query(InvoicePayment).filter(InvoicePayment.business_id == user_id).delete(synchronize_session=False)
    db.query(Invoice).filter(Invoice.business_id == user_id).delete(synchronize_session=False)
    db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == user_id).delete(synchronize_session=False)
    db.query(PurchaseOrder).filter(PurchaseOrder.business_id == user_id).delete(synchronize_session=False)
    db.query(B2BOrder).filter(
        (B2BOrder.seller_business_id == user_id) | (B2BOrder.buyer_business_id == user_id)
    ).delete(synchronize_session=False)
    db.query(JournalEntry).filter(JournalEntry.business_id == user_id).delete(synchronize_session=False)
    db.query(StockTransfer).filter(StockTransfer.business_id == user_id).delete(synchronize_session=False)
    db.query(StockLedger).filter(StockLedger.business_id == user_id).delete(synchronize_session=False)
    db.query(Inventory).filter(Inventory.business_id == user_id).delete(synchronize_session=False)
    db.query(Product).filter(Product.business_id == user_id).delete(synchronize_session=False)
    db.query(Customer).filter(Customer.business_id == user_id).delete(synchronize_session=False)
    db.query(Vendor).filter(Vendor.business_id == user_id).delete(synchronize_session=False)
    
    # B2B network relationships (use correct key names)
    db.query(B2BConnection).filter(
        (B2BConnection.seller_business_id == user_id) | (B2BConnection.buyer_business_id == user_id)
    ).delete(synchronize_session=False)
    db.query(ConnectionCode).filter(ConnectionCode.seller_business_id == user_id).delete(synchronize_session=False)
    db.query(SharedLedger).filter(
        (SharedLedger.seller_business_id == user_id) | (SharedLedger.buyer_business_id == user_id)
    ).delete(synchronize_session=False)

    # 3. Delete all other business-scoped data
    for model in (
        Payment, UploadedFile, DocumentEmbedding, ChatMessage, TokenUsage,
        RateLimitConfig, AlertConfig, Feedback, QueryOverride, BusinessFact,
        BusinessSettings, Expense, Godown, PeriodLock
    ):
        db.query(model).filter(model.business_id == user_id).delete(synchronize_session=False)

    # 4. Purge embeddings from Chroma vector store
    try:
        from services.embeddings import delete_user_chroma_memories
        delete_user_chroma_memories(user_id)
    except Exception as e:
        logger.error("Chroma purge failed for user %s: %s", user_id, e, exc_info=True)
        
    # 5. Delete the target user and invalidate cache
    db.delete(target)
    db.commit()
    invalidate_user_cache(user_id)
    return {"status": "success", "message": "All data for " + target.username + " deleted."}


def token_usage(db: Session) -> list:
    rows = db.query(
        TokenUsage.business_id, TokenUsage.model_tier, TokenUsage.model,
        func.sum(TokenUsage.input_tokens).label("total_input"),
        func.sum(TokenUsage.output_tokens).label("total_output"),
        func.sum(TokenUsage.total_tokens).label("total_tokens"),
        func.sum(TokenUsage.cached_tokens).label("total_cached"),
        func.count(TokenUsage.id).label("call_count"),
    ).group_by(TokenUsage.business_id, TokenUsage.model_tier, TokenUsage.model).all()
    result = []
    for r in rows:
        u = db.query(User).filter(User.id == r.business_id).first()
        result.append({
            "business_id":   r.business_id,
            "business_name": u.business_name if u else "Unknown",
            "model_tier":    r.model_tier,
            "model":         r.model,
            "call_count":    r.call_count,
            "input_tokens":  r.total_input,
            "output_tokens": r.total_output,
            "total_tokens":  r.total_tokens,
            "cached_tokens": r.total_cached,
        })
    return result


def reset_chroma_docs() -> dict:
    from services.embeddings import get_chroma_client
    client = get_chroma_client()
    deleted = []
    for name in ("document_embeddings", "document_embeddings_v2"):
        try:
            client.delete_collection(name=name)
            deleted.append(name)
        except Exception:
            pass
    client.get_or_create_collection(name="document_embeddings_v2")
    return {"status": "success", "deleted_collections": deleted,
            "message": "Chroma document collections reset. Re-upload your files to rebuild the index."}


def business_details(user_id: int, db: Session) -> dict:
    target = require_target_user(user_id, db)
    uploads  = db.query(UploadedFile).filter(UploadedFile.business_id == user_id).all()
    invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()
    inventory = db.query(Inventory).filter(Inventory.business_id == user_id).all()
    payments = db.query(Payment).filter(Payment.business_id == user_id).all()
    msgs = db.query(ChatMessage).filter(ChatMessage.business_id == user_id).order_by(ChatMessage.timestamp.desc()).all()
    return {
        "id": target.id, "username": target.username, "business_name": target.business_name,
        "uploads":  [{"id": u.id, "filename": u.filename, "file_type": u.file_type, "rows_count": u.rows_count, "upload_time": u.upload_time} for u in uploads],
        "invoices": [{"id": i.id, "invoice_id": i.invoice_id, "customer": i.customer, "product": i.product, "amount": i.amount, "status": i.status, "invoice_date": i.invoice_date, "due_date": i.due_date} for i in invoices],
        "inventory":[{"id": it.id, "product_name": it.product_name, "stock": it.stock, "expiry_date": it.expiry_date, "supplier": it.supplier} for it in inventory],
        "payments": [{"id": p.id, "customer": p.customer, "amount": p.amount, "due_date": p.due_date, "paid": p.paid} for p in payments],
        "chat_history": [{"id": m.id, "role": m.role, "content": m.content, "session_id": m.session_id, "session_title": m.session_title, "timestamp": m.timestamp.isoformat() if m.timestamp else None} for m in msgs],
    }


def get_rate_limit_config(user_id: int, db: Session) -> dict:
    cfg = db.query(RateLimitConfig).filter(RateLimitConfig.business_id == user_id).first()
    if not cfg:
        return {"configured": False, "defaults": {"requests_per_minute": 10, "requests_per_day": 500, "max_tokens_per_day": 50000, "complex_per_day": 20, "active": True}}
    return {"configured": True, "requests_per_minute": cfg.requests_per_minute, "requests_per_day": cfg.requests_per_day, "max_tokens_per_day": cfg.max_tokens_per_day, "complex_per_day": cfg.complex_per_day, "active": cfg.active}


def set_rate_limit_config(user_id: int, body, db: Session) -> dict:
    require_target_user(user_id, db)
    cfg = db.query(RateLimitConfig).filter(RateLimitConfig.business_id == user_id).first()
    if cfg:
        cfg.requests_per_minute = body.requests_per_minute
        cfg.requests_per_day    = body.requests_per_day
        cfg.max_tokens_per_day  = body.max_tokens_per_day
        cfg.complex_per_day     = body.complex_per_day
        cfg.active              = body.active
        cfg.updated_at          = datetime.utcnow()
    else:
        db.add(RateLimitConfig(business_id=user_id, requests_per_minute=body.requests_per_minute, requests_per_day=body.requests_per_day, max_tokens_per_day=body.max_tokens_per_day, complex_per_day=body.complex_per_day, active=body.active))
    db.commit()
    target = db.query(User).filter(User.id == user_id).first()
    return {"success": True, "message": "Rate limits saved for " + (target.business_name if target else str(user_id)) + "."}


def all_usage_stats(db: Session) -> list:
    businesses = db.query(User).filter(User.role == "enterprise").all()
    result = []
    for b in businesses:
        s = get_usage_summary(b.id)
        s["business_name"] = b.business_name
        s["username"]      = b.username
        result.append(s)
    return result


def create_merchant(username: str, password: str, business_name: str, db: Session) -> dict:
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    u = User(username=username, password=hash_password(password), business_name=business_name, role="enterprise")
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"status": "success", "message": "Merchant user " + username + " created successfully.", "user_id": u.id}


def update_merchant(user_id: int, req, db: Session) -> dict:
    target = require_target_user(user_id, db)
    if req.username and req.username != target.username:
        if db.query(User).filter(User.username == req.username).first():
            raise HTTPException(status_code=400, detail="Username already exists")
        target.username = req.username
    if req.business_name:
        target.business_name = req.business_name
    if req.password:
        target.password = hash_password(req.password)
    db.commit()
    invalidate_user_cache(user_id)
    return {"status": "success", "message": "Merchant user " + target.username + " updated successfully."}
