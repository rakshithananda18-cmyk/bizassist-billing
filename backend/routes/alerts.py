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

import json
import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from sqlalchemy.orm import Session

from database.db import get_db
from database.models import AlertConfig, User
from services.auth import get_active_user, restrict_cashier
from services.scheduler import get_scheduler

# ── Customer Offer Schemas ────────────────────────────────────

class CustomerOfferIn(BaseModel):
    title: str
    discount_text: str
    description: Optional[str] = None
    valid_until: Optional[str] = None
    customer_id: Optional[int] = None
    coupon_code: Optional[str] = None


class CustomerNoticeIn(BaseModel):
    customer_id: int
    customer_name: Optional[str] = None
    phone: Optional[str] = None
    offer_id: Optional[str] = None
    message: str
    channel: str = "whatsapp"


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
                "kind": "overdue", "severity": "warning", "category": "billing",
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
                "category": "billing",
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
                "kind": "expired", "severity": "danger", "category": "billing",
                "title": f"{len(expired)} batch{'' if len(expired) == 1 else 'es'} past expiry",
                "detail": f"Still counted in stock. Oldest: {expired[0][0]}.",
                "count": len(expired),
                "route": "/stock",
            })
        if expiring:
            name, _date, left = expiring[0]
            items.append({
                "kind": "expiring", "severity": "warning", "category": "billing",
                "title": f"{len(expiring)} batch{'' if len(expiring) == 1 else 'es'} expiring soon",
                "detail": f"Within {days} days. Soonest: {name} "
                          f"({left} day{'' if left == 1 else 's'}).",
                "count": len(expiring),
                "route": "/stock",
            })

    # ── Field Team Activities (when present) ────────────────────
    try:
        from sqlalchemy import inspect as sa_insp, text as sa_text
        t_names = set(sa_insp(db.bind).get_table_names())
        if "ft_item_requests" in t_names:
            field_req_cnt = db.execute(
                sa_text("SELECT COUNT(*) FROM ft_item_requests WHERE business_id = :bid AND status IN ('new', 'pending')"),
                {"bid": bid}
            ).scalar() or 0
            if field_req_cnt > 0:
                plural = "" if field_req_cnt == 1 else "s"
                items.append({
                    "kind": "field_requests",
                    "category": "field",
                    "severity": "info",
                    "title": f"{field_req_cnt} new store request{plural}",
                    "detail": f"{field_req_cnt} shop order/requirement request(s) awaiting review in Field Team.",
                    "count": field_req_cnt,
                    "route": "/requests",
                    "app": "field",
                })
        if "ft_tasks" in t_names:
            now_utc = datetime.now(timezone.utc)
            overdue_task_cnt = db.execute(
                sa_text("SELECT COUNT(*) FROM ft_tasks WHERE business_id = :bid AND status = 'pending' AND due_at < :now"),
                {"bid": bid, "now": now_utc}
            ).scalar() or 0
            if overdue_task_cnt > 0:
                plural = "" if overdue_task_cnt == 1 else "s"
                items.append({
                    "kind": "field_tasks_overdue",
                    "category": "field",
                    "severity": "warning",
                    "title": f"{overdue_task_cnt} overdue field task{plural}",
                    "detail": f"{overdue_task_cnt} delivery / collection task(s) past their scheduled time.",
                    "count": overdue_task_cnt,
                    "route": "/tasks",
                    "app": "field",
                })
    except Exception as e:
        logger.debug("[Alerts] Field tables scan skipped: %s", e)

    # ── Active Customer Offers ──────────────────────────────────
    user_row = db.query(User).filter(User.id == bid).first()
    if user_row and user_row.settings:
        try:
            s_obj = json.loads(user_row.settings) if isinstance(user_row.settings, str) else user_row.settings
            c_offers = s_obj.get("customer_offers", [])
            for off in c_offers[:2]:
                items.append({
                    "kind": f"offer_{off.get('id', 'deal')}",
                    "category": "offers",
                    "severity": "offer",
                    "title": f"Offer: {off.get('title', 'Special Deal')}",
                    "detail": f"{off.get('discount_text', '')} - {off.get('description', '')}".strip(" -"),
                    "route": "/parties",
                    "action": "send_offer",
                    "offer_id": off.get("id"),
                    "offer_data": off,
                })
        except Exception:
            pass

    # ── Active Admin Campaigns & Announcements ──────────────────
    try:
        from services import campaign_service as camp
        announcements = camp.announcements_for(bid, db)
        for a in announcements:
            items.append({
                "kind": f"campaign_{a['id']}",
                "category": "offers",
                "severity": "offer",
                "title": a.get("title", "Special Announcement"),
                "detail": (a.get("body_md", "") or "Special announcement from BizAssist Admin.").replace("#", "").replace("*", "").strip()[:140],
                "route": "/",
                "action": "view_campaign",
                "campaign_id": a["id"],
                "offer_code": a.get("offer_code"),
            })
    except Exception as e:
        logger.debug("[Alerts] Campaign fetch skipped: %s", e)

    # Most-urgent first: danger (red) -> warning (amber) -> offer (purple) -> update (emerald) -> info (blue)
    order = {"danger": 0, "warning": 1, "offer": 2, "update": 3, "info": 4}
    items.sort(key=lambda i: order.get(i.get("severity", "info"), 5))

    # Calculate category counts
    counts = {
        "all": len(items),
        "billing": sum(1 for i in items if i.get("category") == "billing"),
        "field": sum(1 for i in items if i.get("category") == "field"),
        "offers": sum(1 for i in items if i.get("category") == "offers"),
        "updates": sum(1 for i in items if i.get("category") == "updates"),
    }

    # Operational severity (danger or warning) lights up the main trigger
    active_op_severity = next((i["severity"] for i in items if i.get("severity") in ("danger", "warning")), None)

    return {
        "items": items,
        "count": len(items),
        "severity": active_op_severity or (items[0]["severity"] if items else None),
        "categories": ["all", "billing", "field", "offers", "updates"],
        "counts": counts,
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


# ── Customer Offer Endpoints ──────────────────────────────────

@router.get("/customer-offers")
def list_customer_offers(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """List active customer promotional offers configured for this business."""
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        return {"offers": []}
    settings = json.loads(user.settings or "{}") if isinstance(user.settings, str) else (user.settings or {})
    return {"offers": settings.get("customer_offers", [])}


@router.post("/customer-offers")
def create_customer_offer(body: CustomerOfferIn, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Create a new customer offer that can be sent to individual customers via WhatsApp/SMS."""
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    settings = json.loads(user.settings or "{}") if isinstance(user.settings, str) else (user.settings or {})
    offers = settings.get("customer_offers", [])
    new_offer = {
        "id": f"off_{uuid.uuid4().hex[:6]}",
        "title": body.title,
        "discount_text": body.discount_text,
        "description": body.description or "",
        "valid_until": body.valid_until,
        "customer_id": body.customer_id,
        "coupon_code": body.coupon_code or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "business_name": user.business_name or "BizAssist Store",
    }
    offers.insert(0, new_offer)
    settings["customer_offers"] = offers[:20]
    user.settings = json.dumps(settings)
    db.commit()
    return {"success": True, "offer": new_offer}


@router.post("/send-customer-notice")
def send_customer_notice(body: CustomerNoticeIn, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Generate a direct WhatsApp click-to-chat URL with pre-filled offer text for an individual customer."""
    from services.auth import resolve_business_id_in_db
    bid = resolve_business_id_in_db(current_user, db)
    user = db.query(User).filter(User.id == bid).first()
    biz_name = user.business_name if user else "Our Store"

    phone = (body.phone or "").strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    elif len(phone) == 10:
        phone = "91" + phone

    msg = body.message.strip()
    if not msg:
        msg = f"Special Offer from {biz_name}! Get exclusive savings on your next visit."

    import urllib.parse
    encoded_text = urllib.parse.quote(msg)
    wa_url = f"https://api.whatsapp.com/send?phone={phone}&text={encoded_text}" if phone else None

    return {
        "success": True,
        "customer_id": body.customer_id,
        "phone": phone,
        "whatsapp_url": wa_url,
        "message": msg,
    }
