"""
routes/alerts.py
================
REST endpoints for managing alert configurations and manual triggers.

Endpoints:
  GET  /alerts/config          — fetch current alert config for logged-in business
  POST /alerts/config          — save/update alert config
  POST /alerts/test/{type}     — manually fire an alert (for testing)
  GET  /alerts/scheduler       — view scheduler job statuses
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from sqlalchemy.orm import Session

from database.db import get_db
from database.models import AlertConfig, User
from services.auth import get_active_user
from services.scheduler import get_scheduler

logger = logging.getLogger("bizassist.routes.alerts")

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Request schema ────────────────────────────────────────────

class AlertConfigRequest(BaseModel):
    email: Optional[str] = None
    whatsapp_number: Optional[str] = None
    alert_overdue: bool = True
    alert_low_stock: bool = True
    alert_expiry: bool = True
    alert_daily_summary: bool = True
    low_stock_threshold: int = 10
    expiry_days_threshold: int = 30
    active: bool = True


# ── GET config ────────────────────────────────────────────────

@router.get("/config")
def get_alert_config(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Returns the current alert configuration for the authenticated business."""
    config = db.query(AlertConfig).filter(
        AlertConfig.business_id == current_user["id"]
    ).first()

    if not config:
        return {"configured": False}

    return {
        "configured":            True,
        "email":                 config.email,
        "whatsapp_number":       config.whatsapp_number,
        "alert_overdue":         config.alert_overdue,
        "alert_low_stock":       config.alert_low_stock,
        "alert_expiry":          config.alert_expiry,
        "alert_daily_summary":   config.alert_daily_summary,
        "low_stock_threshold":   config.low_stock_threshold,
        "expiry_days_threshold": config.expiry_days_threshold,
        "active":                config.active,
    }


# ── POST config ───────────────────────────────────────────────

@router.post("/config")
def save_alert_config(
    body: AlertConfigRequest,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Create or update the alert configuration for the authenticated business."""
    try:
        user = db.query(User).filter(User.id == current_user["id"]).first()
        business_name = user.business_name if user else f"Business {current_user['id']}"

        config = db.query(AlertConfig).filter(
            AlertConfig.business_id == current_user["id"]
        ).first()

        if config:
            config.email                 = body.email
            config.whatsapp_number       = body.whatsapp_number
            config.alert_overdue         = body.alert_overdue
            config.alert_low_stock       = body.alert_low_stock
            config.alert_expiry          = body.alert_expiry
            config.alert_daily_summary   = body.alert_daily_summary
            config.low_stock_threshold   = body.low_stock_threshold
            config.expiry_days_threshold = body.expiry_days_threshold
            config.active                = body.active
            config.business_name         = business_name
        else:
            config = AlertConfig(
                business_id=current_user["id"],
                business_name=business_name,
                email=body.email,
                whatsapp_number=body.whatsapp_number,
                alert_overdue=body.alert_overdue,
                alert_low_stock=body.alert_low_stock,
                alert_expiry=body.alert_expiry,
                alert_daily_summary=body.alert_daily_summary,
                low_stock_threshold=body.low_stock_threshold,
                expiry_days_threshold=body.expiry_days_threshold,
                active=body.active,
            )
            db.add(config)

        db.commit()
        logger.info(f"[Alerts] Config saved for business_id={current_user['id']}")
        return {"success": True, "message": "Alert configuration saved."}

    except Exception as e:
        db.rollback()
        logger.error(f"[Alerts] Failed to save config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to save alert configuration.")


# ── POST test trigger ─────────────────────────────────────────

@router.post("/test/{alert_type}")
def trigger_alert_manually(
    alert_type: str,
    current_user: dict = Depends(get_active_user)
):
    """
    Manually trigger a specific alert job for testing purposes.
    alert_type: one of 'overdue', 'low_stock', 'expiry', 'daily_summary', 'memory_distillation'
    """
    allowed = ["overdue", "low_stock", "expiry", "daily_summary", "memory_distillation"]
    if alert_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown alert type '{alert_type}'. Choose from: {allowed}"
        )

    try:
        from services.alert_jobs import (
            run_overdue_alerts,
            run_low_stock_alerts,
            run_expiry_alerts,
            run_daily_summary,
            run_memory_distillation,
        )
        dispatch = {
            "overdue":              run_overdue_alerts,
            "low_stock":            run_low_stock_alerts,
            "expiry":               run_expiry_alerts,
            "daily_summary":        run_daily_summary,
            "memory_distillation":  run_memory_distillation,
        }
        dispatch[alert_type]()
        return {"success": True, "message": f"Alert '{alert_type}' triggered manually."}
    except Exception as e:
        logger.error(f"[Alerts] Manual trigger failed for '{alert_type}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to trigger alert manually.")


# ── GET scheduler status ──────────────────────────────────────

@router.get("/scheduler")
def scheduler_status(current_user: dict = Depends(get_active_user)):
    """Returns current APScheduler job list and next run times."""
    scheduler = get_scheduler()

    if not scheduler or not scheduler.running:
        return {"running": False, "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id":       job.id,
            "name":     job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })

    return {"running": True, "jobs": jobs}


# ── GET memory facts ─────────────────────────────────────────

@router.get("/memory-facts")
def get_memory_facts(current_user: dict = Depends(get_active_user)):
    """
    Phase 4 — Returns all distilled business memory facts for the
    current user's business. Facts are written weekly by the memory
    distillation job and injected into every LLM prompt.
    """
    from database.db import SessionLocal
    from database.models import BusinessFact

    business_id = current_user["id"]
    db = SessionLocal()
    try:
        facts = (
            db.query(BusinessFact)
            .filter(BusinessFact.business_id == business_id)
            .order_by(BusinessFact.category, BusinessFact.fact_key)
            .all()
        )
        return {
            "business_id": business_id,
            "count": len(facts),
            "facts": [
                {
                    "id":         f.id,
                    "fact_key":   f.fact_key,
                    "category":   f.category,
                    "fact_text":  f.fact_text,
                    "confidence": f.confidence,
                    "updated_at": f.updated_at.isoformat() if f.updated_at else None,
                }
                for f in facts
            ],
        }
    finally:
        db.close()


# ── DELETE one memory fact ───────────────────────────────────────

@router.delete("/memory-facts/{fact_id}")
def delete_memory_fact(fact_id: int, current_user: dict = Depends(get_active_user)):
    """
    Phase 4 - delete a single distilled fact (scoped to the current business),
    so the owner can remove anything wrong or stale. The weekly job may re-derive
    it if the underlying pattern still holds.
    """
    from database.db import SessionLocal
    from database.models import BusinessFact

    business_id = current_user["id"]
    db = SessionLocal()
    try:
        fact = (
            db.query(BusinessFact)
            .filter(BusinessFact.id == fact_id, BusinessFact.business_id == business_id)
            .first()
        )
        if not fact:
            raise HTTPException(status_code=404, detail="Fact not found")
        logger.info(f"[MEMORY] delete fact id={fact_id} key='{fact.fact_key}' business_id={business_id}")
        db.delete(fact)
        db.commit()
        return {"deleted": fact_id}
    finally:
        db.close()
