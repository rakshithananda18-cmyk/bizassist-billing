"""
app/services.py — shared domain helpers: audit trail, GPS trail, points,
and the JSON shapes every router returns.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.billing_context import billing_context, prime_billing_reads

from app.db import utc_now
from app.geo import GeoFix
from app.models import (
    FieldActivity, FieldAttendance, FieldItemRequest, FieldLocationPing,
    FieldPointsEntry, FieldRoute, FieldRun, FieldRunStop, FieldSettings,
    FieldShop, FieldStaff, FieldTask,
)
from app.security import Principal
from app.timeutil import biz_today, iso_utc, parse_client_time

logger = logging.getLogger("bizassist.task")


# ── Audit + GPS trail ─────────────────────────────────────────────────────────

def log_activity(db: Session, p: Principal, action: str, *, entity: str | None = None,
                 entity_id: int | None = None, summary: str | None = None,
                 fix: GeoFix | None = None) -> None:
    db.add(FieldActivity(
        business_id=p.business_id,
        actor=p.actor,
        staff_id=p.staff.id if p.staff else None,
        action=action,
        entity=entity,
        entity_id=entity_id,
        summary=summary,
        lat=fix.lat if fix else None,
        lng=fix.lng if fix else None,
    ))
    logger.info("[FIELD] biz=%s actor=%s action=%s %s#%s %s",
                p.business_id, p.actor, action, entity or "-", entity_id or "-", summary or "")


def record_fix(db: Session, staff: FieldStaff, fix: GeoFix, *, source: str = "event",
               event: str | None = None) -> FieldLocationPing:
    """Store a GPS point and refresh the staff's last-known position."""
    now = utc_now()
    ping = FieldLocationPing(
        business_id=staff.business_id,
        staff_id=staff.id,
        recorded_at=now,
        client_at=parse_client_time(fix.client_time),
        lat=fix.lat,
        lng=fix.lng,
        accuracy_m=fix.accuracy,
        speed_mps=fix.speed,
        heading=fix.heading,
        battery_pct=fix.battery,
        source=source,
        event=event,
    )
    db.add(ping)
    staff.last_seen_at = now
    staff.last_lat = fix.lat
    staff.last_lng = fix.lng
    staff.last_accuracy_m = fix.accuracy
    return ping


# ── Points (append-only) ──────────────────────────────────────────────────────

def award_task_points(db: Session, task: FieldTask, settings: FieldSettings) -> int:
    """Decide on-time vs late against SERVER completion time and post the points."""
    done = task.completed_at or utc_now()
    on_time = task.due_at is None or done <= task.due_at
    base = int(task.points or 0)
    pts = base if on_time else (base * int(settings.late_points_pct or 0)) // 100
    task.on_time = on_time
    task.points_awarded = pts
    if pts and task.staff_id:
        db.add(FieldPointsEntry(
            business_id=task.business_id,
            staff_id=task.staff_id,
            points=pts,
            reason="task_on_time" if on_time else "task_late",
            task_id=task.id,
            work_date=biz_today(done),
        ))
    return pts


def award_checkin_points(db: Session, att: FieldAttendance, settings: FieldSettings) -> int:
    pts = int(settings.on_time_checkin_points or 0) if att.status == "present" else 0
    if pts:
        db.add(FieldPointsEntry(
            business_id=att.business_id,
            staff_id=att.staff_id,
            points=pts,
            reason="checkin_on_time",
            attendance_id=att.id,
            work_date=att.work_date,
        ))
    return pts


# ── JSON shapes ───────────────────────────────────────────────────────────────

def settings_out(s: FieldSettings) -> dict:
    return {
        "device_policy": s.device_policy,
        "max_accuracy_m": s.max_accuracy_m,
        "geofence_radius_m": s.geofence_radius_m,
        "geofence_enforced": bool(s.geofence_enforced),
        "ping_interval_s": s.ping_interval_s,
        "workday_start": s.workday_start,
        "late_grace_min": s.late_grace_min,
        "default_task_points": s.default_task_points,
        "late_points_pct": s.late_points_pct,
        "on_time_checkin_points": s.on_time_checkin_points,
    }


def staff_out(s: FieldStaff, *, points: int | None = None) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "login_name": s.login_name,
        "phone": s.phone,
        "role": s.role,
        "is_active": bool(s.is_active),
        "device_bound": bool(s.bound_device_id),
        "bound_device_label": s.bound_device_label,
        "bound_at": iso_utc(s.bound_at),
        "signed_in": bool(s.active_session_id),
        "active_device_label": s.active_device_label,
        "last_login": iso_utc(s.last_login),
        "last_seen_at": iso_utc(s.last_seen_at),
        "last_location": (
            {"lat": s.last_lat, "lng": s.last_lng, "accuracy": s.last_accuracy_m}
            if s.last_lat is not None else None
        ),
        **({"points": points} if points is not None else {}),
    }


def shop_out(s: FieldShop) -> dict:
    context = billing_context(s)
    customer = context.customer(s) if context is not None and s.customer_id is not None else None
    return {
        "id": s.id,
        "name": (customer.name or f"Customer {customer.id}") if customer else s.name,
        "contact_name": s.contact_name,
        "phone": customer.phone if customer else s.phone,
        "address": customer.address if customer else s.address,
        "area": s.area,
        "lat": s.lat,
        "lng": s.lng,
        "location_source": s.location_source,
        "customer_id": s.customer_id,
        "billing_linked": s.customer_id is not None,
        "billing_customer_available": customer is not None if s.customer_id is not None else None,
        "billing_customer": ({"id": customer.id, "name": customer.name, "phone": customer.phone,
                              "address": customer.address, "gstin": customer.gstin,
                              "is_active": customer.is_active is not False} if customer else None),
        "notes": s.notes,
        "is_active": bool(s.is_active),
    }


def route_out(r: FieldRoute) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "weekdays": [int(x) for x in (r.weekdays or "").split(",") if x.strip()],
        "default_staff_id": r.default_staff_id,
        "due_time": r.due_time,
        "is_active": bool(r.is_active),
        "stops": [{"id": st.id, "seq": st.seq, "shop": shop_out(st.shop)} for st in r.stops],
    }


def task_out(t: FieldTask, *, confirmed: Optional[dict] = None) -> dict:
    """`confirmed` (task uid → amount, app/collections.confirmed_in_billing) adds
    how much of a collection the owner has confirmed in billing."""
    context = billing_context(t)
    balances, live = context.task_balances(t) if context is not None else (
        {"billing_balance_available": False if t.invoices else None, "current_amount_due": None}, {})
    return {
        "id": t.id,
        "task_type": t.task_type,
        "title": t.title,
        "description": t.description,
        "staff_id": t.staff_id,
        "staff_name": t.staff.name if t.staff else None,
        "shop_id": t.shop_id,
        "shop_name": shop_out(t.shop)["name"] if t.shop else None,
        "run_id": t.run_id,
        "run_stop_id": t.run_stop_id,
        "due_at": iso_utc(t.due_at),
        "points": t.points,
        "status": t.status,
        "boxes_planned": t.boxes_planned,
        "boxes_delivered": t.boxes_delivered,
        "orders_count": t.orders_count,
        "reference": t.reference,
        "amount_expected": t.amount_expected,
        **balances,
        "amount_collected": t.amount_collected,
        "payment_mode": t.payment_mode,
        "payment_ref": t.payment_ref,
        "billing_confirmed": (confirmed.get(t.uid, 0.0) if confirmed is not None
                              and t.task_type == "payment_collect" and (t.amount_collected or 0) > 0 else None),
        "invoices": [{"id": ln.invoice_id, "number": ln.invoice_number, "date": ln.invoice_date,
                      "total": ln.total, "balance_due": ln.balance_due,
                      **live.get(ln.invoice_id, {"available": False, "current_total": None,
                                               "current_paid": None, "current_balance_due": None,
                                               "current_status": None})} for ln in t.invoices],
        "completed_at": iso_utc(t.completed_at),
        "completion_note": t.completion_note,
        "completion_distance_m": t.completion_distance_m,
        "on_time": t.on_time,
        "points_awarded": t.points_awarded,
        "overdue": bool(t.status == "pending" and t.due_at is not None and utc_now() > t.due_at),
    }


def run_stop_out(st: FieldRunStop) -> dict:
    tasks = [task_out(t) for t in st.tasks if t.status != "cancelled"]
    delivery = [t for t in tasks if t["task_type"] == "delivery"]
    return {
        "id": st.id,
        "seq": st.seq,
        "status": st.status,
        "shop": shop_out(st.shop),
        "arrived_at": iso_utc(st.arrived_at),
        "arrival_distance_m": st.arrival_distance_m,
        "outside_geofence": bool(st.outside_geofence),
        "done_at": iso_utc(st.done_at),
        "skip_reason": st.skip_reason,
        "boxes_planned": sum(t["boxes_planned"] or 0 for t in delivery),
        "boxes_delivered": sum(t["boxes_delivered"] or 0 for t in delivery),
        "orders_count": sum(t["orders_count"] or 0 for t in delivery),
        "tasks": tasks,
    }


def run_out(r: FieldRun, *, with_stops: bool = True) -> dict:
    if with_stops:
        prime_billing_reads(shops=[s.shop for s in r.stops], tasks=[t for s in r.stops for t in s.tasks])
    stops = [run_stop_out(s) for s in r.stops] if with_stops else None
    total = len(r.stops)
    done = sum(1 for s in r.stops if s.status in ("done", "skipped"))
    out = {
        "id": r.id,
        "route_id": r.route_id,
        "name": r.name,
        "run_date": r.run_date,
        "staff_id": r.staff_id,
        "staff_name": r.staff.name if r.staff else None,
        "status": r.status,
        "started_at": iso_utc(r.started_at),
        "completed_at": iso_utc(r.completed_at),
        "notes": r.notes,
        "stops_total": total,
        "stops_done": done,
    }
    if stops is not None:
        out["stops"] = stops
        out["boxes_planned"] = sum(s["boxes_planned"] for s in stops)
        out["boxes_delivered"] = sum(s["boxes_delivered"] for s in stops)
        out["orders_count"] = sum(s["orders_count"] for s in stops)
    return out


def attendance_out(a: FieldAttendance) -> dict:
    return {
        "id": a.id,
        "staff_id": a.staff_id,
        "staff_name": a.staff.name if a.staff else None,
        "work_date": a.work_date,
        "status": a.status,
        "minutes_late": a.minutes_late,
        "check_in_at": iso_utc(a.check_in_at),
        "check_in_location": {"lat": a.check_in_lat, "lng": a.check_in_lng, "accuracy": a.check_in_accuracy_m},
        "check_out_at": iso_utc(a.check_out_at),
        "check_out_location": (
            {"lat": a.check_out_lat, "lng": a.check_out_lng, "accuracy": a.check_out_accuracy_m}
            if a.check_out_lat is not None else None
        ),
        # Phone clock vs server clock, in seconds. Large values = tampered or
        # badly-set phone clock; shown to the owner, never trusted.
        "client_clock_skew_s": (
            int((a.check_in_client_at - a.check_in_at).total_seconds())
            if a.check_in_client_at else None
        ),
    }


def item_request_out(r: FieldItemRequest) -> dict:
    try:
        items = json.loads(r.items_json or "[]")
    except ValueError:
        items = []
    return {
        "id": r.id,
        "kind": r.kind,
        "shop_id": r.shop_id,
        "shop_name": shop_out(r.shop)["name"] if r.shop else None,
        "staff_id": r.staff_id,
        "staff_name": r.staff.name if r.staff else None,
        "run_stop_id": r.run_stop_id,
        "items": items,
        "note": r.note,
        "status": r.status,
        "created_at": iso_utc(r.created_at),
        "location": {"lat": r.lat, "lng": r.lng, "accuracy": r.accuracy_m} if r.lat is not None else None,
    }


def scoped(query, model, business_id: int):
    """`WHERE business_id = :bid` — the one filter every read must carry."""
    return query.filter(model.business_id == business_id)


def get_scoped(db: Session, model, business_id: int, obj_id: int, what: str):
    from fastapi import HTTPException
    row = db.query(model).filter(model.id == obj_id, model.business_id == business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{what} not found")
    return row


def optional_staff(db: Session, business_id: int, staff_id: Optional[int]) -> Optional[FieldStaff]:
    if staff_id is None:
        return None
    return get_scoped(db, FieldStaff, business_id, staff_id, "Staff member")
