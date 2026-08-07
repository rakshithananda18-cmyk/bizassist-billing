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
from services.auth import get_active_user, restrict_cashier
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
    current_user: dict = Depends(restrict_cashier),
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
    current_user: dict = Depends(restrict_cashier),
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
    current_user: dict = Depends(restrict_cashier)
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


# ── GET in-app notifications ──────────────────────────────────
#
# The scheduled jobs in services/alert_jobs.py already work out everything an
# owner needs told — overdue invoices, low stock, expiring batches — and then
# hand the result to notifier.notify(), which drops it on the floor when SMTP is
# not configured (the default). So the app has always known that fifteen products
# are below threshold and has never had a way to say so.
#
# Computed on request rather than stored. There is no state a notifications table
# would hold that the source rows do not already hold, and a stored copy would
# need invalidating every time stock moved or an invoice was paid — which is
# most of what this application does. These are three indexed reads scoped to one
# business; the freshness is free.
#
# Read-only by construction: no writes, no side effects, safe to poll.

# Defaults matching AlertConfig's column defaults, for the businesses — the
# majority — that never opened the alerts screen. Returning nothing for them
# would make the feature look broken rather than quiet.
_DEFAULT_ALERT_PREFS = {
    "alert_overdue": True, "alert_low_stock": True, "alert_expiry": True,
    "low_stock_threshold": 10, "expiry_days_threshold": 30,
}


_ALERTS_OFF = {"alert_overdue": False, "alert_low_stock": False, "alert_expiry": False,
               "low_stock_threshold": 10, "expiry_days_threshold": 30}


def _alert_prefs(db: Session, business_id: int) -> dict:
    """This business's alert preferences, or the defaults."""
    cfg = db.query(AlertConfig).filter(AlertConfig.business_id == business_id).first()
    if not cfg:
        return _DEFAULT_ALERT_PREFS
    if not cfg.active:
        # `active=False` is an explicit "stop telling me". The bell honours it
        # rather than treating itself as a separate channel the switch missed.
        return _ALERTS_OFF
    return {
        "alert_overdue":         bool(cfg.alert_overdue),
        "alert_low_stock":       bool(cfg.alert_low_stock),
        "alert_expiry":          bool(cfg.alert_expiry),
        "low_stock_threshold":   cfg.low_stock_threshold or 10,
        "expiry_days_threshold": cfg.expiry_days_threshold or 30,
    }


@router.get("/notifications")
def list_notifications(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """What this business needs told, right now.

    Same findings as the scheduled email alerts, from the same queries, minus
    the delivery channel that silently discards them.
    """
    from database.models import Invoice
    from services.auth import resolve_business_id_in_db
    from services.insights_service import low_stock_products, expiring_batches

    # The canonical resolver, not `current_user["id"]`. A token's integer id
    # means nothing outside the database that issued it, and for a manager's
    # staff token it is the STAFF row — which owns no stock and no invoices, so
    # the bell would have shown them a permanently empty list. This resolves
    # through the BizID to the owner row. See core/identity.py.
    bid = resolve_business_id_in_db(current_user, db)
    prefs = _alert_prefs(db, bid)
    items: list[dict] = []

    if prefs.get("alert_overdue"):
        overdue = (
            db.query(Invoice)
            .filter(Invoice.business_id == bid, Invoice.status == "Overdue")
            .order_by(Invoice.amount.desc())
            .all()
        )
        if overdue:
            total = sum(inv.amount or 0 for inv in overdue)
            items.append({
                "kind": "overdue", "severity": "warning",
                "title": f"{len(overdue)} overdue invoice{'' if len(overdue) == 1 else 's'}",
                "detail": f"₹{total:,.0f} outstanding. Largest: {overdue[0].customer or 'unnamed'}.",
                "count": len(overdue),
                "route": "/sales",
            })

    if prefs.get("alert_low_stock"):
        # The SAME function the dashboard's "Low Stock Items" KPI calls. They sat
        # on screen together disagreeing — "0 need restocking" beside "3 out of
        # stock" — because this endpoint had its own copy that counted inventory
        # BATCHES. One definition now; they cannot drift again.
        low = low_stock_products(db, bid)
        if low:
            out_of_stock = [r for r in low if r[1] <= 0]
            name, qty, floor = low[0]
            detail = f"At or below {floor:g} units. Lowest: {name} ({qty:g})."
            if out_of_stock:
                detail = f"{len(out_of_stock)} already out of stock. " + detail
            items.append({
                "kind": "low_stock",
                # Out of stock is not the same warning as running low — you
                # cannot sell it at all, so it outranks the rest of the list.
                "severity": "danger" if out_of_stock else "warning",
                "title": f"{len(low)} product{'' if len(low) == 1 else 's'} low on stock",
                "detail": detail,
                "count": len(low),
                "route": "/stock",
            })

    if prefs.get("alert_expiry"):
        days = prefs["expiry_days_threshold"]
        # Shared with the scheduled email and the daily summary. Expiry stays
        # per BATCH — unlike stock levels, the lot is the thing that goes off.
        expired, expiring = expiring_batches(db, bid, days)

        # Already-expired is its own item, and it sorts above "expiring soon".
        # It is not an early warning, it is stock on the shelf that must come
        # off — a different instruction, so a different line.
        if expired:
            items.append({
                "kind": "expired", "severity": "danger",
                "title": f"{len(expired)} batch{'' if len(expired) == 1 else 'es'} past expiry",
                "detail": f"Still counted in stock. Oldest: {expired[0][0]}.",
                "count": len(expired),
                "route": "/stock",
            })
        if expiring:
            name, _date, left = expiring[0]
            items.append({
                "kind": "expiring", "severity": "warning",
                "title": f"{len(expiring)} batch{'' if len(expiring) == 1 else 'es'} expiring soon",
                "detail": f"Within {days} days. Soonest: {name} "
                          f"({left} day{'' if left == 1 else 's'}).",
                "count": len(expiring),
                "route": "/stock",
            })

    # Most-urgent first, so the bell's colour and the first row agree.
    order = {"danger": 0, "warning": 1, "info": 2}
    items.sort(key=lambda i: order.get(i["severity"], 3))
    return {
        "items": items,
        "count": len(items),
        "severity": items[0]["severity"] if items else None,
    }


# ── GET scheduler status ──────────────────────────────────────

@router.get("/scheduler")
def scheduler_status(current_user: dict = Depends(restrict_cashier)):
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
def get_memory_facts(current_user: dict = Depends(restrict_cashier)):
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
def delete_memory_fact(fact_id: int, current_user: dict = Depends(restrict_cashier)):
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
