import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from typing import Optional
from datetime import datetime, date
from database.db import SessionLocal
from database.models import User, Invoice, Inventory, UploadedFile, Payment, ChatMessage, DocumentEmbedding, TokenUsage, RateLimitConfig
from services.auth import get_active_user, hash_password
from services.context_cache import invalidate, invalidate_user_cache, get_cache_stats
from services.rate_limiter import get_usage_summary

router = APIRouter()
logger = logging.getLogger("bizassist.admin")


@router.get("/admin/businesses")
def admin_businesses(current_user: dict = Depends(get_active_user)):
    logger.info(f"User {current_user['id']} requesting admin businesses directory...")
    db = SessionLocal()
    try:
        # Verify admin role
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            logger.warning(f"Access denied: User {current_user['id']} is not an admin (role={getattr(admin_user, 'role', None)})")
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
        # Get all businesses (excluding admins)
        businesses = db.query(User).filter(User.role == "enterprise").all()
        result = []
        
        logger.info(f"Admin found {len(businesses)} enterprise accounts. Aggregating statistics...")
        for b in businesses:
            inv_count = db.query(Invoice).filter(Invoice.business_id == b.id).count()
            total_rev = db.query(func.sum(Invoice.amount)).filter(Invoice.business_id == b.id).scalar() or 0
            stock_count = db.query(Inventory).filter(Inventory.business_id == b.id).count()
            uploads = db.query(UploadedFile).filter(UploadedFile.business_id == b.id).count()
            
            result.append({
                "id": b.id,
                "username": b.username,
                "business_name": b.business_name,
                "invoice_count": inv_count,
                "total_revenue": total_rev,
                "inventory_count": stock_count,
                "upload_count": uploads
            })
        logger.info("Successfully loaded administrative stats for all businesses.")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching admin businesses database statistics: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error retrieving admin database records")
    finally:
        db.close()


@router.delete("/admin/wipe-all-data")
def wipe_all_data(current_user: dict = Depends(get_active_user)):
    logger.info(f"User {current_user['id']} requesting admin data wipe...")
    db = SessionLocal()
    try:
        # Verify admin role
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            logger.warning(f"Access denied: User {current_user['id']} is not an admin (role={getattr(admin_user, 'role', None)})")
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
        # Delete all dynamic data
        db.query(Invoice).delete()
        db.query(Inventory).delete()
        db.query(Payment).delete()
        db.query(UploadedFile).delete()
        db.query(DocumentEmbedding).delete()
        db.query(ChatMessage).delete()
        db.commit()
        
        # Invalidate all context and query response caches
        invalidate()
        logger.info("Admin successfully wiped all dynamic database records and flushed global context caches.")
        return {"status": "success", "message": "All business invoices, inventory, payments, uploads, document embeddings, and chat messages have been deleted, and cache is flushed."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error wiping all dynamic database records: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error wiping database records")
    finally:
        db.close()


@router.post("/admin/flush-cache/{user_id}")
def flush_user_cache(user_id: int, current_user: dict = Depends(get_active_user)):
    logger.info(f"User {current_user['id']} requesting cache flush for user {user_id}...")
    db = SessionLocal()
    try:
        # Verify admin role
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            logger.warning(f"Access denied: User {current_user['id']} is not an admin (role={getattr(admin_user, 'role', None)})")
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
        # Verify target user exists
        target_user = db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Invalidate user cache
        invalidate_user_cache(user_id)
        logger.info(f"Admin successfully flushed cache for user {user_id} ({target_user.username}).")
        return {"status": "success", "message": f"Cache flushed for user {target_user.username} (ID: {user_id})."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error flushing cache for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error flushing user cache")
    finally:
        db.close()


@router.delete("/admin/wipe-user-data/{user_id}")
def wipe_user_data(user_id: int, current_user: dict = Depends(get_active_user)):
    logger.info(f"User {current_user['id']} requesting admin data wipe for user {user_id}...")
    db = SessionLocal()
    try:
        # Verify admin role
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            logger.warning(f"Access denied: User {current_user['id']} is not an admin (role={getattr(admin_user, 'role', None)})")
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
        # Verify target user exists
        target_user = db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete dynamic data for target user
        db.query(Invoice).filter(Invoice.business_id == user_id).delete()
        db.query(Inventory).filter(Inventory.business_id == user_id).delete()
        db.query(Payment).filter(Payment.business_id == user_id).delete()
        db.query(UploadedFile).filter(UploadedFile.business_id == user_id).delete()
        db.query(DocumentEmbedding).filter(DocumentEmbedding.business_id == user_id).delete()
        db.query(ChatMessage).filter(ChatMessage.business_id == user_id).delete()
        
        # Sync deletion with Chroma persistent vector database
        try:
            from services.embeddings import delete_user_chroma_memories
            delete_user_chroma_memories(user_id)
        except Exception as chroma_err:
            logger.error(f"Error purging Chroma user data: {chroma_err}", exc_info=True)

        # Also delete the User account itself
        db.delete(target_user)
        db.commit()
        
        # Invalidate target user's context and query response cache
        invalidate_user_cache(user_id)
        logger.info(f"Admin successfully wiped dynamic database records and flushed context cache for user {user_id} ({target_user.username}).")
        return {"status": "success", "message": f"All dynamic business data for user {target_user.username} has been deleted and cache is flushed."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error wiping dynamic database records for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error wiping user database records")
    finally:
        db.close()


@router.get("/admin/token-usage")
def get_token_usage(current_user: dict = Depends(get_active_user)):
    """Returns token usage summary per business and per model tier. Admin only."""
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

        rows = db.query(
            TokenUsage.business_id,
            TokenUsage.model_tier,
            TokenUsage.model,
            func.sum(TokenUsage.input_tokens).label("total_input"),
            func.sum(TokenUsage.output_tokens).label("total_output"),
            func.sum(TokenUsage.total_tokens).label("total_tokens"),
            func.sum(TokenUsage.cached_tokens).label("total_cached"),
            func.count(TokenUsage.id).label("call_count"),
        ).group_by(
            TokenUsage.business_id, TokenUsage.model_tier, TokenUsage.model
        ).all()

        result = []
        for r in rows:
            user = db.query(User).filter(User.id == r.business_id).first()
            result.append({
                "business_id":    r.business_id,
                "business_name":  user.business_name if user else "Unknown",
                "model_tier":     r.model_tier,
                "model":          r.model,
                "call_count":     r.call_count,
                "input_tokens":   r.total_input,
                "output_tokens":  r.total_output,
                "total_tokens":   r.total_tokens,
                "cached_tokens":  r.total_cached,
            })
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        db.close()


@router.post("/admin/flush-all-cache")
def flush_all_cache(current_user: dict = Depends(get_active_user)):
    """Flushes the entire in-memory query response cache for all users."""
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        invalidate()
        logger.info(f"Admin {current_user['id']} flushed global in-memory cache.")
        return {"status": "success", "message": "Global query response cache flushed for all users."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error flushing global cache: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error flushing cache")
    finally:
        db.close()


@router.post("/admin/reset-chroma-documents")
def reset_chroma_documents(current_user: dict = Depends(get_active_user)):
    """
    Deletes and recreates the Chroma document embedding collections.
    Use this to fix dimension mismatch errors after switching embedding models.
    Chat memory collections are NOT affected.
    """
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

        from services.embeddings import get_chroma_client
        client = get_chroma_client()

        deleted = []
        # Delete all document embedding collections (old + v2)
        for name in ["document_embeddings", "document_embeddings_v2"]:
            try:
                client.delete_collection(name=name)
                deleted.append(name)
                logger.info(f"[Chroma] Deleted collection: {name}")
            except Exception:
                pass  # Collection didn't exist — fine

        # Recreate v2 fresh (384-dim, correct dimension)
        client.get_or_create_collection(name="document_embeddings_v2")
        logger.info("[Chroma] Recreated document_embeddings_v2 (384-dim, clean).")

        logger.info(f"Admin {current_user['id']} reset Chroma document collections.")
        return {
            "status": "success",
            "deleted_collections": deleted,
            "message": "Chroma document collections reset. Re-upload your files to rebuild the index."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting Chroma documents: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error resetting Chroma")
    finally:
        db.close()


@router.get("/admin/cache-stats")
def get_admin_cache_stats(current_user: dict = Depends(get_active_user)):
    logger.info(f"User {current_user['id']} requesting admin cache stats...")
    db = SessionLocal()
    try:
        # Verify admin role
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            logger.warning(f"Access denied: User {current_user['id']} is not an admin")
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
        return get_cache_stats()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching admin cache statistics: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error retrieving cache stats")
    finally:
        db.close()


@router.get("/admin/business-details/{user_id}")
def get_business_details(user_id: int, current_user: dict = Depends(get_active_user)):
    logger.info(f"User {current_user['id']} requesting details tree for user {user_id}...")
    db = SessionLocal()
    try:
        # Verify admin role
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            logger.warning(f"Access denied: User {current_user['id']} is not an admin")
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
        # Verify target user exists
        target_user = db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Retrieve all details
        uploads = db.query(UploadedFile).filter(UploadedFile.business_id == user_id).all()
        invoices = db.query(Invoice).filter(Invoice.business_id == user_id).all()
        inventory = db.query(Inventory).filter(Inventory.business_id == user_id).all()
        payments = db.query(Payment).filter(Payment.business_id == user_id).all()
        chat_messages = db.query(ChatMessage).filter(ChatMessage.business_id == user_id).order_by(ChatMessage.timestamp.desc()).all()
        
        return {
            "id": target_user.id,
            "username": target_user.username,
            "business_name": target_user.business_name,
            "uploads": [
                {
                    "id": u.id,
                    "filename": u.filename,
                    "file_type": u.file_type,
                    "rows_count": u.rows_count,
                    "upload_time": u.upload_time
                } for u in uploads
            ],
            "invoices": [
                {
                    "id": inv.id,
                    "invoice_id": inv.invoice_id,
                    "customer": inv.customer,
                    "product": inv.product,
                    "amount": inv.amount,
                    "status": inv.status,
                    "invoice_date": inv.invoice_date,
                    "due_date": inv.due_date
                } for inv in invoices
            ],
            "inventory": [
                {
                    "id": item.id,
                    "product_name": item.product_name,
                    "stock": item.stock,
                    "expiry_date": item.expiry_date,
                    "supplier": item.supplier
                } for item in inventory
            ],
            "payments": [
                {
                    "id": p.id,
                    "customer": p.customer,
                    "amount": p.amount,
                    "due_date": p.due_date,
                    "paid": p.paid
                } for p in payments
            ],
            "chat_history": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "session_id": m.session_id,
                    "session_title": m.session_title,
                    "timestamp": m.timestamp.isoformat() if m.timestamp else None
                } for m in chat_messages
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching details tree for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error retrieving user details tree")
    finally:
        db.close()


# ── USER MANAGEMENT SCHEMAS & ROUTES ─────────────────────────────────

# ── Rate Limit Config Schema ──────────────────────────────────────────

class RateLimitRequest(BaseModel):
    requests_per_minute: int = 10
    requests_per_day:    int = 500
    max_tokens_per_day:  int = 50000
    complex_per_day:     int = 20
    active:              bool = True


@router.get("/admin/rate-limits/{user_id}")
def get_rate_limits(user_id: int, current_user: dict = Depends(get_active_user)):
    """Get rate limit config for a specific business."""
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=403, detail="Access denied.")

        cfg = db.query(RateLimitConfig).filter(RateLimitConfig.business_id == user_id).first()
        if not cfg:
            return {"configured": False, "defaults": {
                "requests_per_minute": 10,
                "requests_per_day":    500,
                "max_tokens_per_day":  50000,
                "complex_per_day":     20,
                "active":              True
            }}
        return {
            "configured":          True,
            "requests_per_minute": cfg.requests_per_minute,
            "requests_per_day":    cfg.requests_per_day,
            "max_tokens_per_day":  cfg.max_tokens_per_day,
            "complex_per_day":     cfg.complex_per_day,
            "active":              cfg.active,
        }
    finally:
        db.close()


@router.post("/admin/rate-limits/{user_id}")
def set_rate_limits(user_id: int, body: RateLimitRequest, current_user: dict = Depends(get_active_user)):
    """Create or update rate limit config for a specific business."""
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=403, detail="Access denied.")

        target = db.query(User).filter(User.id == user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found.")

        cfg = db.query(RateLimitConfig).filter(RateLimitConfig.business_id == user_id).first()
        if cfg:
            cfg.requests_per_minute = body.requests_per_minute
            cfg.requests_per_day    = body.requests_per_day
            cfg.max_tokens_per_day  = body.max_tokens_per_day
            cfg.complex_per_day     = body.complex_per_day
            cfg.active              = body.active
            cfg.updated_at          = datetime.utcnow()
        else:
            cfg = RateLimitConfig(
                business_id         = user_id,
                requests_per_minute = body.requests_per_minute,
                requests_per_day    = body.requests_per_day,
                max_tokens_per_day  = body.max_tokens_per_day,
                complex_per_day     = body.complex_per_day,
                active              = body.active,
            )
            db.add(cfg)

        db.commit()
        logger.info(f"[Admin] Rate limits updated for user {user_id} by admin {current_user['id']}")
        return {"success": True, "message": f"Rate limits saved for {target.business_name}."}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error setting rate limits for user {user_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error setting rate limits.")
    finally:
        db.close()


@router.get("/admin/usage-stats")
def get_all_usage_stats(current_user: dict = Depends(get_active_user)):
    """Returns today's usage stats for all businesses."""
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            raise HTTPException(status_code=403, detail="Access denied.")

        businesses = db.query(User).filter(User.role == "enterprise").all()
        result = []
        for b in businesses:
            summary = get_usage_summary(b.id)
            summary["business_name"] = b.business_name
            summary["username"]      = b.username
            result.append(summary)
        return result
    finally:
        db.close()


class AdminCreateUserRequest(BaseModel):
    username: str
    password: str
    business_name: str

class AdminUpdateUserRequest(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    business_name: Optional[str] = None


@router.post("/admin/create-user")
def create_merchant_user(req: AdminCreateUserRequest, current_user: dict = Depends(get_active_user)):
    logger.info(f"User {current_user['id']} requesting admin user creation for username '{req.username}'...")
    db = SessionLocal()
    try:
        # Verify admin role
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            logger.warning(f"Access denied: User {current_user['id']} is not an admin")
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
        # Verify username uniqueness
        existing = db.query(User).filter(User.username == req.username).first()
        if existing:
            logger.warning(f"Failed user creation: username '{req.username}' already exists.")
            raise HTTPException(status_code=400, detail="Username already exists")
        
        # Create merchant user
        new_user = User(
            username=req.username,
            password=hash_password(req.password),
            business_name=req.business_name,
            role="enterprise"
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"Admin successfully created new merchant account ID {new_user.id} ({req.username}).")
        return {"status": "success", "message": f"Merchant user {req.username} created successfully.", "user_id": new_user.id}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating merchant account: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error creating merchant user")
    finally:
        db.close()


@router.put("/admin/update-user/{user_id}")
def update_merchant_user(user_id: int, req: AdminUpdateUserRequest, current_user: dict = Depends(get_active_user)):
    logger.info(f"User {current_user['id']} requesting admin user edit for user {user_id}...")
    db = SessionLocal()
    try:
        # Verify admin role
        admin_user = db.query(User).filter(User.id == current_user["id"]).first()
        if not admin_user or admin_user.role != "admin":
            logger.warning(f"Access denied: User {current_user['id']} is not an admin")
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
        # Verify target user exists
        target_user = db.query(User).filter(User.id == user_id).first()
        if not target_user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # If username is changing, verify uniqueness
        if req.username and req.username != target_user.username:
            existing = db.query(User).filter(User.username == req.username).first()
            if existing:
                logger.warning(f"Failed user update: username '{req.username}' already exists.")
                raise HTTPException(status_code=400, detail="Username already exists")
            target_user.username = req.username
        
        # Update fields if provided
        if req.business_name:
            target_user.business_name = req.business_name
        
        if req.password:
            target_user.password = hash_password(req.password)
            
        db.commit()
        
        # Invalidate target user's cache to avoid any inconsistencies
        invalidate_user_cache(user_id)
        
        logger.info(f"Admin successfully updated merchant account ID {user_id} ({target_user.username}).")
        return {"status": "success", "message": f"Merchant user {target_user.username} updated successfully."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating merchant account: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error updating merchant user")
    finally:
        db.close()
