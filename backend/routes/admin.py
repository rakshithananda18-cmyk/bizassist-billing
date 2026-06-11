"""
routes/admin.py
===============
Thin HTTP adapters for admin endpoints.
All business logic lives in services/admin_service.py.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database.db import get_db
from services.auth import get_active_user
from services.context_cache import invalidate, invalidate_user_cache, get_cache_stats
import services.admin_service as svc

router = APIRouter()
logger = logging.getLogger("bizassist.routes.admin")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RateLimitRequest(BaseModel):
    requests_per_minute: int  = 10
    requests_per_day:    int  = 500
    max_tokens_per_day:  int  = 50000
    complex_per_day:     int  = 20
    active:              bool = True


class AdminCreateUserRequest(BaseModel):
    username:      str
    password:      str
    business_name: str


class AdminUpdateUserRequest(BaseModel):
    username:      Optional[str] = None
    password:      Optional[str] = None
    business_name: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/admin/businesses")
def admin_businesses(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.list_businesses(db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/businesses: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/admin/wipe-all-data")
def wipe_all_data(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.wipe_all_data(db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/wipe-all-data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/admin/flush-cache/{user_id}")
def flush_user_cache(user_id: int, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        svc.require_target_user(user_id, db)
        invalidate_user_cache(user_id)
        return {"status": "success", "message": "Cache flushed for user " + str(user_id) + "."}
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/flush-cache/%s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete("/admin/wipe-user-data/{user_id}")
def wipe_user_data(user_id: int, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.wipe_user_data(user_id, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/wipe-user-data/%s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/admin/token-usage")
def get_token_usage(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.token_usage(db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/token-usage: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/admin/flush-all-cache")
def flush_all_cache(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        invalidate()
        return {"status": "success", "message": "Global query response cache flushed."}
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/flush-all-cache: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/admin/reset-chroma-documents")
def reset_chroma_documents(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.reset_chroma_docs()
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/reset-chroma-documents: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/admin/cache-stats")
def get_admin_cache_stats(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return get_cache_stats()
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/cache-stats: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/admin/business-details/{user_id}")
def get_business_details(user_id: int, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.business_details(user_id, db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/business-details/%s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/admin/rate-limits/{user_id}")
def get_rate_limits(user_id: int, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.get_rate_limit_config(user_id, db)
    except HTTPException: raise

@router.post("/admin/rate-limits/{user_id}")
def set_rate_limits(user_id: int, body: RateLimitRequest, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.set_rate_limit_config(user_id, body, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/rate-limits/%s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error setting rate limits.")

@router.get("/admin/usage-stats")
def get_all_usage_stats(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    svc.require_admin(current_user["id"], db)
    return svc.all_usage_stats(db)


@router.post("/admin/create-user")
def create_merchant_user(req: AdminCreateUserRequest, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.create_merchant(req.username, req.password, req.business_name, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/create-user: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/admin/update-user/{user_id}")
def update_merchant_user(user_id: int, req: AdminUpdateUserRequest, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.update_merchant(user_id, req, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/update-user/%s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")