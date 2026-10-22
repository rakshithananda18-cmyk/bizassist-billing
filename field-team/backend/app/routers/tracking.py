"""
routers/tracking.py — the GPS trail and the owner's live view.

The PWA sends a ping every `ping_interval_s` while it is OPEN on screen.
Browsers suspend GPS for a backgrounded / screen-locked web app, so the trail
has gaps when the phone is pocketed; every field action still carries its own
fix (docs/MASTER_PLAN.md §Location explains the native-wrapper path for true
background tracking).

Pings arrive one at a time or batched (the app buffers while offline). The
server keeps one ping per half-interval per person, which bounds storage no
matter how often a client sends.
"""
from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db, utc_now
from app.geo import GeoFix
from app.models import FieldAttendance, FieldLocationPing, FieldRun, FieldStaff
from app.security import Principal, get_settings, require_owner, require_staff
from app.services import get_scoped, record_fix
from app.timeutil import biz_today, day_bounds_utc, iso_utc, parse_client_time

router = APIRouter(prefix="/api/track", tags=["tracking"])

MAX_BATCH = 120


class PingBatch(BaseModel):
    pings: List[GeoFix] = Field(..., min_length=1, max_length=MAX_BATCH)


@router.post("/pings")
def post_pings(body: PingBatch, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    settings = get_settings(db, p.business_id)
    staff = p.staff
    # Off duty → no trail. Location is collected for work, not for a person's day.
    att = db.query(FieldAttendance).filter(
        FieldAttendance.staff_id == staff.id, FieldAttendance.work_date == biz_today()).first()
    if att is None or att.check_out_at is not None:
        return {"stored": 0, "ignored": len(body.pings), "reason": "off duty"}

    min_gap = timedelta(seconds=max(5, int(settings.ping_interval_s) // 2))
    accuracy_cap = int(settings.max_accuracy_m) * 2
    last = (db.query(func.max(FieldLocationPing.recorded_at))
            .filter(FieldLocationPing.staff_id == staff.id).scalar())
    last_client = None
    stored = ignored = 0
    now = utc_now()
    # Oldest first, so a buffered batch replays in order.
    fixes = sorted(body.pings, key=lambda f: parse_client_time(f.client_time) or now)
    for fix in fixes:
        if fix.accuracy is None or fix.accuracy > accuracy_cap or (abs(fix.lat) < 1e-6 and abs(fix.lng) < 1e-6):
            ignored += 1
            continue
        client_at = parse_client_time(fix.client_time)
        if len(fixes) > 1 and client_at is not None:
            # Buffered points: thin by the phone's own spacing.
            if last_client is not None and client_at - last_client < min_gap:
                ignored += 1
                continue
            last_client = client_at
        elif last is not None and now - last < min_gap:
            ignored += 1
            continue
        record_fix(db, staff, fix, source="watch")
        last = now
        stored += 1
    db.commit()
    return {"stored": stored, "ignored": ignored, "interval_s": settings.ping_interval_s}


@router.get("/live")
def live(p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    """Every active staff member: last fix, duty status and today's run progress."""
    today = biz_today()
    staff = (db.query(FieldStaff).filter(FieldStaff.business_id == p.business_id,
                                         FieldStaff.is_active.is_(True))
             .order_by(FieldStaff.name).all())
    atts = {a.staff_id: a for a in db.query(FieldAttendance).filter(
        FieldAttendance.business_id == p.business_id, FieldAttendance.work_date == today).all()}
    runs = db.query(FieldRun).filter(FieldRun.business_id == p.business_id, FieldRun.run_date == today,
                                     FieldRun.status != "cancelled").all()
    by_staff: dict[int, list] = {}
    for r in runs:
        by_staff.setdefault(r.staff_id, []).append(r)
    now = utc_now()
    out = []
    for s in staff:
        a = atts.get(s.id)
        duty = "off" if a is None else ("checked_out" if a.check_out_at else "on_duty")
        rs = by_staff.get(s.id, [])
        stops_total = sum(len(r.stops) for r in rs)
        stops_done = sum(1 for r in rs for st in r.stops if st.status in ("done", "skipped"))
        current = next((st for r in rs for st in r.stops if st.status == "arrived"), None)
        nxt = next((st for r in rs for st in r.stops if st.status == "pending"), None)
        out.append({
            "staff_id": s.id,
            "name": s.name,
            "role": s.role,
            "phone": s.phone,
            "duty": duty,
            "late": bool(a and a.status == "late"),
            "check_in_at": iso_utc(a.check_in_at) if a else None,
            "last_seen_at": iso_utc(s.last_seen_at),
            "minutes_since_seen": int((now - s.last_seen_at).total_seconds() // 60) if s.last_seen_at else None,
            "location": ({"lat": s.last_lat, "lng": s.last_lng, "accuracy": s.last_accuracy_m}
                         if s.last_lat is not None else None),
            "runs": [{"id": r.id, "name": r.name, "status": r.status} for r in rs],
            "stops_total": stops_total,
            "stops_done": stops_done,
            "at_shop": current.shop.name if current else None,
            "next_shop": nxt.shop.name if nxt else None,
        })
    return {"day": today, "staff": out}


@router.get("/trail")
def trail(staff_id: int, day: Optional[str] = Query(None), p: Principal = Depends(require_owner),
          db: Session = Depends(get_db)):
    get_scoped(db, FieldStaff, p.business_id, staff_id, "Staff member")
    day = day or biz_today()
    try:
        start, end = day_bounds_utc(day)
    except ValueError:
        raise HTTPException(status_code=422, detail="day must be YYYY-MM-DD")
    rows = (db.query(FieldLocationPing)
            .filter(FieldLocationPing.business_id == p.business_id, FieldLocationPing.staff_id == staff_id,
                    FieldLocationPing.recorded_at >= start, FieldLocationPing.recorded_at < end)
            .order_by(FieldLocationPing.recorded_at.asc(), FieldLocationPing.id.asc()).limit(5000).all())
    return {
        "day": day,
        "staff_id": staff_id,
        "points": [{
            # t = server receive time (authoritative); client_t = phone clock,
            # which differs for points the app buffered while offline.
            "t": iso_utc(r.recorded_at), "client_t": iso_utc(r.client_at), "lat": r.lat, "lng": r.lng, "accuracy": r.accuracy_m,
            "source": r.source, "event": r.event, "battery": r.battery_pct,
        } for r in rows],
    }


def purge_old_pings(db: Session, retention_days: int) -> int:
    """Delete raw pings older than the retention window. Event fixes live on
    their own rows (attendance, stops, tasks), so nothing evidential is lost."""
    cutoff = utc_now() - timedelta(days=retention_days)
    n = db.query(FieldLocationPing).filter(FieldLocationPing.recorded_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return int(n or 0)
