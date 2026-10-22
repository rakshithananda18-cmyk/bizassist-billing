"""
routers/attendance.py — check-in / check-out with server time + location.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db, utc_now
from app.geo import GeoFix, validate_fix
from app.models import FieldAttendance, FieldStaff
from app.security import Principal, get_settings, require_owner, require_staff
from app.services import attendance_out, award_checkin_points, log_activity, record_fix, staff_out
from app.timeutil import biz_now, biz_today, parse_client_time, parse_hhmm

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


class GeoBody(BaseModel):
    geo: GeoFix


def todays_attendance(db: Session, staff: FieldStaff) -> Optional[FieldAttendance]:
    return db.query(FieldAttendance).filter(
        FieldAttendance.staff_id == staff.id, FieldAttendance.work_date == biz_today(),
    ).first()


def require_checked_in(db: Session, staff: FieldStaff) -> FieldAttendance:
    """Field work only counts while on duty: checked in today, not checked out."""
    att = todays_attendance(db, staff)
    if att is None:
        raise HTTPException(status_code=409, detail="Check in first — attendance is required before field work.")
    if att.check_out_at is not None:
        raise HTTPException(status_code=409, detail="You have checked out for today.")
    return att


@router.post("/check-in", status_code=201)
def check_in(body: GeoBody, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    settings = get_settings(db, p.business_id)
    fix = validate_fix(body.geo, settings.max_accuracy_m)
    staff = p.staff
    if todays_attendance(db, staff) is not None:
        raise HTTPException(status_code=409, detail="Already checked in today.")

    now = utc_now()
    local = biz_now(now)
    start = parse_hhmm(settings.workday_start)
    minutes_after_start = (local.hour * 60 + local.minute) - (start.hour * 60 + start.minute)
    minutes_late = max(0, minutes_after_start)
    status = "late" if minutes_late > int(settings.late_grace_min or 0) else "present"

    att = FieldAttendance(
        business_id=p.business_id,
        staff_id=staff.id,
        work_date=local.date().isoformat(),
        status=status,
        minutes_late=minutes_late if status == "late" else 0,
        device_id=staff.active_device_id,
        check_in_at=now,
        check_in_lat=fix.lat,
        check_in_lng=fix.lng,
        check_in_accuracy_m=fix.accuracy,
        check_in_client_at=parse_client_time(fix.client_time),
    )
    db.add(att)
    db.flush()
    pts = award_checkin_points(db, att, settings)
    record_fix(db, staff, fix, event="check_in")
    log_activity(db, p, "attendance.check_in", entity="attendance", entity_id=att.id,
                 summary=f"{status}{f' by {minutes_late} min' if status == 'late' else ''}", fix=fix)
    db.commit()
    return {**attendance_out(att), "points_awarded": pts}


@router.post("/check-out")
def check_out(body: GeoBody, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    settings = get_settings(db, p.business_id)
    fix = validate_fix(body.geo, settings.max_accuracy_m)
    att = require_checked_in(db, p.staff)
    att.check_out_at = utc_now()
    att.check_out_lat = fix.lat
    att.check_out_lng = fix.lng
    att.check_out_accuracy_m = fix.accuracy
    att.check_out_client_at = parse_client_time(fix.client_time)
    record_fix(db, p.staff, fix, event="check_out")
    log_activity(db, p, "attendance.check_out", entity="attendance", entity_id=att.id, fix=fix)
    db.commit()
    return attendance_out(att)


@router.get("/me")
def my_attendance(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    att = todays_attendance(db, p.staff)
    return {"today": biz_today(), "attendance": attendance_out(att) if att else None}


@router.get("")
def attendance_register(
    day: Optional[str] = Query(None, description="YYYY-MM-DD (business date); default today"),
    p: Principal = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """One day's register: who checked in (when, where, late?) and who is absent."""
    day = day or biz_today()
    try:
        _date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=422, detail="day must be YYYY-MM-DD")
    rows = (db.query(FieldAttendance)
            .filter(FieldAttendance.business_id == p.business_id, FieldAttendance.work_date == day)
            .order_by(FieldAttendance.check_in_at.asc()).all())
    present_ids = {r.staff_id for r in rows}
    absent_q = db.query(FieldStaff).filter(
        FieldStaff.business_id == p.business_id, FieldStaff.is_active.is_(True),
    )
    if present_ids:
        absent_q = absent_q.filter(~FieldStaff.id.in_(present_ids))
    absent = absent_q.order_by(FieldStaff.name.asc()).all()
    return {
        "day": day,
        "present": [attendance_out(r) for r in rows],
        "absent": [staff_out(s) for s in absent],
    }
