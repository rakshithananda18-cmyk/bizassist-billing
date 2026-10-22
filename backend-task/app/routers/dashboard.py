"""
routers/dashboard.py — the owner's glance, the staff member's "today",
scorecards and the activity feed.
"""
from __future__ import annotations

from datetime import date as _date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db, utc_now
from app.models import (
    FieldActivity, FieldAttendance, FieldItemRequest, FieldPointsEntry, FieldRun,
    FieldStaff, FieldTask,
)
from app.routers.attendance import todays_attendance
from app.security import Principal, get_settings, require_owner, require_staff
from app.services import attendance_out, run_out, settings_out, staff_out, task_out
from app.timeutil import biz_today, day_bounds_utc, iso_utc

router = APIRouter(prefix="/api", tags=["dashboard"])


def _check_day(day: Optional[str]) -> str:
    day = day or biz_today()
    try:
        return _date.fromisoformat(day).isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail="Date must be YYYY-MM-DD")


@router.get("/dashboard")
def dashboard(day: Optional[str] = Query(None), p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    day = _check_day(day)
    bid = p.business_id
    staff_total = db.query(func.count(FieldStaff.id)).filter(
        FieldStaff.business_id == bid, FieldStaff.is_active.is_(True)).scalar() or 0
    atts = db.query(FieldAttendance).filter(FieldAttendance.business_id == bid,
                                            FieldAttendance.work_date == day).all()
    runs = db.query(FieldRun).filter(FieldRun.business_id == bid, FieldRun.run_date == day,
                                     FieldRun.status != "cancelled").all()
    start, end = day_bounds_utc(day)
    day_tasks = db.query(FieldTask).filter(
        FieldTask.business_id == bid, FieldTask.status != "cancelled",
        ((FieldTask.due_at >= start) & (FieldTask.due_at < end))
        | ((FieldTask.completed_at >= start) & (FieldTask.completed_at < end)),
    ).all()
    now = utc_now()
    deliveries = [t for t in day_tasks if t.task_type == "delivery"]
    stops = [s for r in runs for s in r.stops]

    points_rows = (db.query(FieldPointsEntry.staff_id, func.sum(FieldPointsEntry.points))
                   .filter(FieldPointsEntry.business_id == bid, FieldPointsEntry.work_date == day)
                   .group_by(FieldPointsEntry.staff_id).all())
    names = {s.id: s.name for s in db.query(FieldStaff).filter(FieldStaff.business_id == bid).all()}
    leaderboard = sorted(
        [{"staff_id": sid, "name": names.get(sid, "?"), "points": int(pts or 0)} for sid, pts in points_rows],
        key=lambda r: -r["points"],
    )
    open_requests = db.query(func.count(FieldItemRequest.id)).filter(
        FieldItemRequest.business_id == bid, FieldItemRequest.status == "new").scalar() or 0
    recent = (db.query(FieldActivity).filter(FieldActivity.business_id == bid)
              .order_by(FieldActivity.id.desc()).limit(15).all())

    return {
        "day": day,
        "attendance": {
            "staff_total": staff_total,
            "present": len(atts),
            "late": sum(1 for a in atts if a.status == "late"),
            "on_duty": sum(1 for a in atts if a.check_out_at is None),
            "absent": max(0, staff_total - len(atts)),
        },
        "runs": {
            "total": len(runs),
            "planned": sum(1 for r in runs if r.status == "planned"),
            "in_progress": sum(1 for r in runs if r.status == "in_progress"),
            "completed": sum(1 for r in runs if r.status == "completed"),
            "stops_total": len(stops),
            "stops_done": sum(1 for s in stops if s.status == "done"),
            "stops_skipped": sum(1 for s in stops if s.status == "skipped"),
        },
        "deliveries": {
            "total": len(deliveries),
            "done": sum(1 for t in deliveries if t.status == "done"),
            "orders_sent": sum(t.orders_count or 0 for t in deliveries),
            "boxes_planned": sum(t.boxes_planned or 0 for t in deliveries),
            "boxes_delivered": sum(t.boxes_delivered or 0 for t in deliveries if t.status == "done"),
        },
        "tasks": {
            "total": len(day_tasks),
            "done": sum(1 for t in day_tasks if t.status == "done"),
            "on_time": sum(1 for t in day_tasks if t.status == "done" and t.on_time),
            "overdue": sum(1 for t in day_tasks if t.status == "pending" and t.due_at and t.due_at < now),
        },
        "open_requests": open_requests,
        "leaderboard": leaderboard,
        "runs_list": [run_out(r, with_stops=False) for r in runs],
        "recent_activity": [activity_out(a, names) for a in recent],
    }


def activity_out(a: FieldActivity, names: dict) -> dict:
    return {
        "id": a.id,
        "at": iso_utc(a.created_at),
        "actor": "Owner" if a.actor.startswith("owner:") else names.get(a.staff_id, "Staff"),
        "action": a.action,
        "summary": a.summary,
        "location": {"lat": a.lat, "lng": a.lng} if a.lat is not None else None,
    }


@router.get("/activity")
def activity(limit: int = Query(50, ge=1, le=300), staff_id: Optional[int] = None,
             p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    q = db.query(FieldActivity).filter(FieldActivity.business_id == p.business_id)
    if staff_id is not None:
        q = q.filter(FieldActivity.staff_id == staff_id)
    names = {s.id: s.name for s in db.query(FieldStaff).filter(FieldStaff.business_id == p.business_id).all()}
    return [activity_out(a, names) for a in q.order_by(FieldActivity.id.desc()).limit(limit).all()]


def _scorecard(db: Session, bid: int, d_from: str, d_to: str, staff_ids: Optional[list[int]] = None) -> list[dict]:
    staff_q = db.query(FieldStaff).filter(FieldStaff.business_id == bid)
    if staff_ids is not None:
        staff_q = staff_q.filter(FieldStaff.id.in_(staff_ids))
    staff = staff_q.order_by(FieldStaff.name).all()
    start, _ = day_bounds_utc(d_from)
    _, end = day_bounds_utc(d_to)
    out = []
    for s in staff:
        pts = db.query(func.coalesce(func.sum(FieldPointsEntry.points), 0)).filter(
            FieldPointsEntry.business_id == bid, FieldPointsEntry.staff_id == s.id,
            FieldPointsEntry.work_date >= d_from, FieldPointsEntry.work_date <= d_to).scalar() or 0
        done = db.query(FieldTask).filter(
            FieldTask.business_id == bid, FieldTask.staff_id == s.id, FieldTask.status == "done",
            FieldTask.completed_at >= start, FieldTask.completed_at < end).all()
        missed = db.query(func.count(FieldTask.id)).filter(
            FieldTask.business_id == bid, FieldTask.staff_id == s.id, FieldTask.status == "pending",
            FieldTask.due_at >= start, FieldTask.due_at < min(end, utc_now())).scalar() or 0
        atts = db.query(FieldAttendance).filter(
            FieldAttendance.business_id == bid, FieldAttendance.staff_id == s.id,
            FieldAttendance.work_date >= d_from, FieldAttendance.work_date <= d_to).all()
        on_time = sum(1 for t in done if t.on_time)
        out.append({
            "staff_id": s.id,
            "name": s.name,
            "role": s.role,
            "points": int(pts),
            "tasks_done": len(done),
            "tasks_on_time": on_time,
            "tasks_late": len(done) - on_time,
            "tasks_missed": int(missed),
            "on_time_pct": round(100.0 * on_time / len(done), 1) if done else None,
            "deliveries_done": sum(1 for t in done if t.task_type == "delivery"),
            "boxes_delivered": sum(t.boxes_delivered or 0 for t in done if t.task_type == "delivery"),
            "amount_collected": round(sum(t.amount_collected or 0 for t in done), 2),
            "days_present": len(atts),
            "days_late": sum(1 for a in atts if a.status == "late"),
        })
    return sorted(out, key=lambda r: -r["points"])


def _range(d_from: Optional[str], d_to: Optional[str]) -> tuple[str, str]:
    today = _date.fromisoformat(biz_today())
    d_to = _check_day(d_to or today.isoformat())
    d_from = _check_day(d_from or today.replace(day=1).isoformat())
    if d_from > d_to:
        raise HTTPException(status_code=422, detail="'from' is after 'to'")
    if (_date.fromisoformat(d_to) - _date.fromisoformat(d_from)) > timedelta(days=366):
        raise HTTPException(status_code=422, detail="Range is limited to one year")
    return d_from, d_to


@router.get("/scorecard")
def scorecard(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
              p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    d_from, d_to = _range(date_from, date_to)
    return {"from": d_from, "to": d_to, "staff": _scorecard(db, p.business_id, d_from, d_to)}


@router.get("/my/scorecard")
def my_scorecard(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                 p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    d_from, d_to = _range(date_from, date_to)
    rows = _scorecard(db, p.business_id, d_from, d_to, staff_ids=[p.staff.id])
    return {"from": d_from, "to": d_to, **(rows[0] if rows else {})}


@router.get("/my/today")
def my_today(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    """Everything the agent needs at a glance: duty status, today's route(s) with
    shops, phone numbers and tasks, other open tasks, and today's points."""
    today = biz_today()
    staff = p.staff
    settings = get_settings(db, p.business_id)
    att = todays_attendance(db, staff)
    runs = (db.query(FieldRun)
            .filter(FieldRun.business_id == p.business_id, FieldRun.staff_id == staff.id,
                    FieldRun.run_date == today, FieldRun.status != "cancelled")
            .order_by(FieldRun.id).all())
    other = (db.query(FieldTask)
             .filter(FieldTask.business_id == p.business_id, FieldTask.staff_id == staff.id,
                     FieldTask.status == "pending", FieldTask.run_id.is_(None))
             .order_by(FieldTask.due_at.is_(None), FieldTask.due_at.asc()).limit(100).all())
    pts_today = db.query(func.coalesce(func.sum(FieldPointsEntry.points), 0)).filter(
        FieldPointsEntry.staff_id == staff.id, FieldPointsEntry.work_date == today).scalar() or 0
    pts_total = db.query(func.coalesce(func.sum(FieldPointsEntry.points), 0)).filter(
        FieldPointsEntry.staff_id == staff.id).scalar() or 0
    db.commit()
    return {
        "today": today,
        "server_time": iso_utc(utc_now()),
        "staff": staff_out(staff),
        "settings": settings_out(settings),
        "attendance": attendance_out(att) if att else None,
        "runs": [run_out(r) for r in runs],
        "other_tasks": [task_out(t) for t in other],
        "points_today": int(pts_today),
        "points_total": int(pts_total),
    }
