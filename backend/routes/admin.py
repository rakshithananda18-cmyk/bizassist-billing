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
from sqlalchemy import text
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

@router.post("/admin/force-logout/{user_id}")
def force_logout_business(user_id: int, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Revoke every outstanding session (owner + staff) for a business.
    Stolen laptop / fired staff / stale token — takes effect within ~30s."""
    try:
        svc.require_admin(current_user["id"], db, action="force_logout", details={"target": user_id})
        return svc.force_logout(user_id, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/force-logout/%s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/metrics")
def get_business_metrics(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Growth metrics: plan mix, activation funnel, activity cohorts, churn risk (§4.4)."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.business_metrics(db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/metrics: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Admin TOTP 2FA (§4.1) ────────────────────────────────────────────────────

class TotpCodeRequest(BaseModel):
    code: str


@router.get("/admin/2fa/status")
def get_2fa_status(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        admin = svc.require_admin(current_user["id"], db)
        return svc.totp_status(admin)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/2fa/status: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/2fa/setup")
def setup_2fa(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        admin = svc.require_admin(current_user["id"], db, action="totp_setup")
        return svc.totp_setup(admin, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/2fa/setup: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/2fa/confirm")
def confirm_2fa(body: TotpCodeRequest, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        admin = svc.require_admin(current_user["id"], db, action="totp_confirm")
        return svc.totp_confirm(admin, body.code, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/2fa/confirm: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/2fa/disable")
def disable_2fa(body: TotpCodeRequest, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        admin = svc.require_admin(current_user["id"], db, action="totp_disable")
        return svc.totp_disable(admin, body.code, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/2fa/disable: %s", e, exc_info=True)
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

@router.get("/admin/business-logs/{user_id}")
def download_business_logs(user_id: int, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Download the most recent log archive a business uploaded to the cloud
    (via feedback / the daily log-upload job). Stored under
    logs/remote_clients/<business_id>/. 404 if the business never uploaded any."""
    import os, glob
    from fastapi.responses import FileResponse
    try:
        svc.require_admin(current_user["id"], db, action="download_business_logs", details={"target": user_id})
        upload_dir = os.path.join("logs", "remote_clients", str(user_id))
        files = sorted(glob.glob(os.path.join(upload_dir, "*")), key=os.path.getmtime, reverse=True)
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            raise HTTPException(status_code=404, detail="No uploaded logs for this business yet.")
        latest = files[0]
        return FileResponse(latest, media_type="application/gzip", filename=os.path.basename(latest))
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/business-logs/%s: %s", user_id, e, exc_info=True)
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
    """Filterable, newest-first telemetry view. DB-first (persistent
    telemetry_events table); JSONL file fallback. ?bizid= scopes to one
    business."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.read_telemetry(device=device, event=event, level=level,
                                  since=since, bizid=bizid, limit=limit, db=db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/telemetry: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/telemetry/businesses")
def get_telemetry_businesses(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Businesses with telemetry (DB-first; folder fallback)."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.telemetry_businesses(db=db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/telemetry/businesses: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/telemetry/devices")
def get_telemetry_devices(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Latest entry per device — app version, platform, last seen."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.telemetry_devices(db=db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/telemetry/devices: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/telemetry/stats")
def get_telemetry_stats(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Health of the persistent telemetry store: rows, bounds, size vs the
    TELEMETRY_MAX_MB cap — powers the Admin Console storage panel."""
    try:
        svc.require_admin(current_user["id"], db)
        from services import telemetry_maintenance as tm
        return tm.stats(db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/telemetry/stats: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/telemetry/archive")
def download_telemetry_archive(purge: bool = Query(False),
                               current_user: dict = Depends(get_active_user),
                               db: Session = Depends(get_db)):
    """Download EVERY telemetry row as gzip JSONL (telemetry-archive-*.jsonl.gz).
    With ?purge=1 the archived rows are deleted after the archive is built
    (max-id watermark: rows ingested during the export are kept). This is the
    'when the store hits ~200 MB, archive to a file on my machine and clean
    the cloud' flow."""
    try:
        svc.require_admin(current_user["id"], db,
                          action="telemetry_archive_purge" if purge else None)
        from services import telemetry_maintenance as tm
        from fastapi.responses import Response
        blob, filename, max_id = tm.build_archive(db)
        purged = tm.purge_archived(db, max_id) if purge else 0
        return Response(
            content=blob,
            media_type="application/gzip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Telemetry-Archived-Max-Id": str(max_id),
                "X-Telemetry-Purged-Rows": str(purged),
            },
        )
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/telemetry/archive: %s", e, exc_info=True)
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
    """Newest-first view over DB action_logs table, falling back to logs/admin_audit.jsonl."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.read_audit_log(limit=limit, db=db)
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


from fastapi.responses import FileResponse
import os
import httpx
from datetime import datetime

@router.get("/admin/health-check")
def get_admin_health_check(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Health check endpoint for the Admin Console displaying DB connections and server status."""
    try:
        svc.require_admin(current_user["id"], db)
        
        sqlite_status = "unknown"
        postgres_status = "unknown"
        
        db_type = db.bind.dialect.name
        try:
            db.execute(text("SELECT 1")).fetchone()
            db_conn_ok = True
        except Exception:
            db_conn_ok = False
            
        if db_type == "sqlite":
            sqlite_status = "connected" if db_conn_ok else "error"
        else:
            postgres_status = "connected" if db_conn_ok else "error"
            
        if db_type == "sqlite":
            from services.sync_worker import CLOUD_URL
            try:
                resp = httpx.get(f"{CLOUD_URL}/health", timeout=2.0)
                postgres_status = "reachable" if resp.status_code == 200 else "error"
            except Exception:
                postgres_status = "unreachable"

        log_size = 0
        log_exists = False
        log_path = "logs/bizassist.log"
        if os.path.exists(log_path):
            log_exists = True
            log_size = os.path.getsize(log_path)
            
        from services import telemetry_maintenance as tm
        telemetry_stats = {}
        try:
            telemetry_stats = tm.stats(db)
        except Exception:
            pass
            
        return {
            "status": "ok",
            "db_type": db_type,
            "sqlite": sqlite_status,
            "postgres": postgres_status,
            "log_file": {
                "exists": log_exists,
                "size_bytes": log_size
            },
            "telemetry": telemetry_stats,
            "server_time": datetime.utcnow().isoformat()
        }
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/health-check: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/feedbacks")
def get_admin_feedbacks(limit: int = Query(100, ge=1, le=1000), current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Retrieve submitted merchant feedback forms and logs."""
    try:
        svc.require_admin(current_user["id"], db)
        from database.models import UserFeedback
        feedbacks = db.query(UserFeedback).order_by(UserFeedback.id.desc()).limit(limit).all()
        return feedbacks
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/feedbacks: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/feedback/logs/{feedback_id}")
def download_feedback_logs(feedback_id: int, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Download the zipped logs associated with a merchant feedback submission."""
    try:
        svc.require_admin(current_user["id"], db)
        from database.models import UserFeedback
        feedback = db.query(UserFeedback).filter(UserFeedback.id == feedback_id).first()
        if not feedback or not feedback.log_file_path:
            raise HTTPException(status_code=404, detail="Feedback or log file not found.")
        if not os.path.exists(feedback.log_file_path):
            raise HTTPException(status_code=404, detail="Log file archive does not exist on disk.")
        return FileResponse(
            path=feedback.log_file_path,
            filename=os.path.basename(feedback.log_file_path),
            media_type="application/gzip"
        )
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/feedback/logs: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


from fastapi import Query

@router.get("/admin/table-alterations")
def get_admin_table_alterations(limit: int = Query(100, ge=1, le=1000), current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Retrieve database table alterations (audit logs) from the system."""
    try:
        svc.require_admin(current_user["id"], db)
        from database.models import TableAlteration
        alterations = db.query(TableAlteration).order_by(TableAlteration.id.desc()).limit(limit).all()
        return alterations
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/table-alterations: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
# (end of admin routes)
