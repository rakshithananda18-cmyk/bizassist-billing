"""
routes/admin.py
===============
Thin HTTP adapters for admin endpoints.
All business logic lives in services/admin_service.py.

Every route is behind svc.require_admin (which also enforces the
ADMIN_API_ENABLED env gate — fail closed, 404 when unset). Mutations pass an
`action` so require_admin audit-logs who/what/when to logs/admin_audit.jsonl.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
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


class RouterModeRequest(BaseModel):
    mode: str   # legacy | shadow | new


class SubscriptionRequest(BaseModel):
    plan:       str                    # free | pro  (free = revoke)
    status:     Optional[str] = None   # active | trial | suspended
    expires_at: Optional[str] = None   # ISO date; None = no expiry
    note:       Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/admin/router-mode")
def get_router_mode(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Current routing mode: legacy (old stack) | shadow (compare) | new (LLM router)."""
    try:
        svc.require_admin(current_user["id"], db)
        from services.router_mode import get_mode, pretty, VALID_MODES
        return {"mode": pretty(), "internal": get_mode(),
                "options": ["legacy", "shadow", "new"]}
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/router-mode GET: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/router-mode")
def set_router_mode(req: RouterModeRequest,
                    current_user: dict = Depends(get_active_user),
                    db: Session = Depends(get_db)):
    """
    Switch routing LIVE — no restart. legacy = exact previous behaviour;
    shadow = legacy answers + LLM comparison logging; new = LLM router steers
    (legacy stays as automatic fallback). Resets to the .env default on restart.
    """
    try:
        svc.require_admin(current_user["id"], db, action="set_router_mode", details={"mode": req.mode})
        from services.router_mode import set_mode, pretty
        try:
            mode = set_mode(req.mode)
        except ValueError as ve:
            raise HTTPException(status_code=422, detail=str(ve))
        return {"status": "success", "mode": pretty(mode),
                "message": f"Routing switched to '{pretty(mode)}' — effective immediately."}
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/router-mode POST: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/businesses")
def admin_businesses(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Fleet monitor: per business — stats, hosting mode, last sync + queue depth,
    online-in-last-24h, and subscription plan."""
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
        svc.require_admin(current_user["id"], db, action="wipe_all_data")
        return svc.wipe_all_data(db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/wipe-all-data: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/admin/flush-cache/{user_id}")
def flush_user_cache(user_id: int, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db, action="flush_user_cache", details={"target": user_id})
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
        svc.require_admin(current_user["id"], db, action="wipe_user_data", details={"target": user_id})
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
        svc.require_admin(current_user["id"], db, action="flush_all_cache")
        invalidate()
        return {"status": "success", "message": "Global query response cache flushed."}
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/flush-all-cache: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/admin/reset-chroma-documents")
def reset_chroma_documents(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db, action="reset_chroma_documents")
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
        svc.require_admin(current_user["id"], db, action="set_rate_limits",
                          details={"target": user_id, "config": body.dict()})
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
        svc.require_admin(current_user["id"], db, action="create_user", details={"username": req.username})
        return svc.create_merchant(req.username, req.password, req.business_name, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/create-user: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.put("/admin/update-user/{user_id}")
def update_merchant_user(user_id: int, req: AdminUpdateUserRequest, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db, action="update_user", details={"target": user_id})
        return svc.update_merchant(user_id, req, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/update-user/%s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Phase B: telemetry / logs viewer ─────────────────────────────────────────

@router.get("/admin/telemetry")
def get_telemetry(device: Optional[str] = None, event: Optional[str] = None,
                  level: Optional[str] = None, since: Optional[str] = None,
                  bizid: Optional[str] = None,
                  limit: int = Query(200, ge=1, le=1000),
                  current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Filterable, newest-first telemetry view. With ?bizid= it reads that
    business's segregated file (logs/businesses/<bizid>/telemetry.jsonl)."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.read_telemetry(device=device, event=event, level=level,
                                  since=since, bizid=bizid, limit=limit)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/telemetry: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/telemetry/businesses")
def get_telemetry_businesses(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Per-business telemetry folders (logs/businesses/<bizid>/)."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.telemetry_businesses()
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/telemetry/businesses: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/telemetry/devices")
def get_telemetry_devices(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Latest entry per device — app version, platform, last seen."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.telemetry_devices()
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/telemetry/devices: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/server-log")
def get_server_log(lines: int = Query(200, ge=1, le=2000),
                   q: Optional[str] = None,
                   current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Tail of bizassist.log for the Debug tab. Optional ?q= substring filter
    (BizID / username) for a segregated per-business view."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.server_log_tail(lines=lines, q=q)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/server-log: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/audit-log")
def get_audit_log(limit: int = Query(200, ge=1, le=1000),
                  current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Newest-first view over logs/admin_audit.jsonl (who did what, when)."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.read_audit_log(limit=limit)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/audit-log: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Phase B: subscriptions (schema-free — users.settings JSON) ──────────────

@router.get("/admin/subscription/{business_id}")
def get_subscription(business_id: int, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return svc.get_subscription(business_id, db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/subscription GET %s: %s", business_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/subscription/{business_id}")
def set_subscription(business_id: int, body: SubscriptionRequest,
                     current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Grant / extend / revoke a plan (plan='free' revokes)."""
    try:
        admin = svc.require_admin(current_user["id"], db, action="set_subscription",
                                  details={"target": business_id, "plan": body.plan,
                                           "expires_at": body.expires_at, "note": body.note})
        return svc.set_subscription(business_id, body, admin, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/subscription POST %s: %s", business_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
