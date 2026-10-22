"""
routers/staff.py — owner manages field staff and the business's field settings.
Owner sets every password; staff cannot self-register.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import FieldPointsEntry, FieldStaff
from app.security import Principal, get_settings, hash_password, require_owner, validate_password_policy
from app.services import get_scoped, log_activity, settings_out, staff_out
from app.timeutil import parse_hhmm

router = APIRouter(prefix="/api", tags=["staff"])

_LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")


def _login_name(raw: str) -> str:
    name = (raw or "").strip().lower()
    if not _LOGIN_RE.match(name):
        raise HTTPException(
            status_code=422,
            detail="Login name: 2–32 characters, letters/numbers/._- only, starting with a letter or number.",
        )
    return name


class StaffCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    login_name: str
    password: str
    phone: Optional[str] = Field(None, max_length=20)
    role: Literal["delivery", "field", "supervisor"] = "delivery"


class StaffUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    phone: Optional[str] = Field(None, max_length=20)
    role: Optional[Literal["delivery", "field", "supervisor"]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


def _points_by_staff(db: Session, business_id: int) -> dict[int, int]:
    rows = (
        db.query(FieldPointsEntry.staff_id, func.coalesce(func.sum(FieldPointsEntry.points), 0))
        .filter(FieldPointsEntry.business_id == business_id)
        .group_by(FieldPointsEntry.staff_id)
        .all()
    )
    return {sid: int(total) for sid, total in rows}


@router.get("/staff")
def list_staff(p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    pts = _points_by_staff(db, p.business_id)
    rows = (db.query(FieldStaff).filter(FieldStaff.business_id == p.business_id)
            .order_by(FieldStaff.is_active.desc(), FieldStaff.name.asc()).all())
    return [staff_out(s, points=pts.get(s.id, 0)) for s in rows]


@router.post("/staff", status_code=201)
def create_staff(req: StaffCreate, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    login = _login_name(req.login_name)
    validate_password_policy(req.password)
    dup = db.query(FieldStaff.id).filter(
        FieldStaff.business_id == p.business_id, FieldStaff.login_name == login,
    ).first()
    if dup:
        raise HTTPException(status_code=400, detail="A staff member with this login name already exists")
    staff = FieldStaff(
        business_id=p.business_id,
        name=req.name.strip(),
        login_name=login,
        phone=(req.phone or "").strip() or None,
        role=req.role,
        password_hash=hash_password(req.password),
    )
    db.add(staff)
    db.flush()
    log_activity(db, p, "staff.create", entity="staff", entity_id=staff.id, summary=f"{staff.name} ({login})")
    db.commit()
    return staff_out(staff, points=0)


@router.patch("/staff/{staff_id}")
def update_staff(staff_id: int, req: StaffUpdate, p: Principal = Depends(require_owner),
                 db: Session = Depends(get_db)):
    staff = get_scoped(db, FieldStaff, p.business_id, staff_id, "Staff member")
    changes = []
    if req.name is not None:
        staff.name = req.name.strip()
        changes.append("name")
    if req.phone is not None:
        staff.phone = req.phone.strip() or None
        changes.append("phone")
    if req.role is not None:
        staff.role = req.role
        changes.append("role")
    if req.password is not None:
        validate_password_policy(req.password)
        staff.password_hash = hash_password(req.password)
        staff.token_version = (staff.token_version or 0) + 1  # sign out everywhere
        staff.active_session_id = None
        changes.append("password")
    if req.is_active is not None:
        staff.is_active = req.is_active
        if not req.is_active:
            staff.token_version = (staff.token_version or 0) + 1
            staff.active_session_id = None
        changes.append("active" if req.is_active else "disabled")
    log_activity(db, p, "staff.update", entity="staff", entity_id=staff.id, summary=", ".join(changes))
    db.commit()
    return staff_out(staff)


@router.post("/staff/{staff_id}/release-device")
def release_device(staff_id: int, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    """Free a bound account (lost / replaced phone). The next sign-in binds the
    new device. Also signs the old device out."""
    staff = get_scoped(db, FieldStaff, p.business_id, staff_id, "Staff member")
    old = staff.bound_device_label or staff.bound_device_id
    staff.bound_device_id = None
    staff.bound_device_label = None
    staff.bound_at = None
    staff.active_session_id = None
    staff.token_version = (staff.token_version or 0) + 1
    log_activity(db, p, "staff.release_device", entity="staff", entity_id=staff.id, summary=f"released {old or '-'}")
    db.commit()
    return staff_out(staff)


@router.post("/staff/{staff_id}/sign-out")
def force_sign_out(staff_id: int, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    staff = get_scoped(db, FieldStaff, p.business_id, staff_id, "Staff member")
    staff.active_session_id = None
    staff.token_version = (staff.token_version or 0) + 1
    log_activity(db, p, "staff.sign_out", entity="staff", entity_id=staff.id)
    db.commit()
    return staff_out(staff)


# ── Field settings ────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    device_policy: Optional[Literal["single_session", "bound"]] = None
    max_accuracy_m: Optional[int] = Field(None, ge=10, le=2000)
    geofence_radius_m: Optional[int] = Field(None, ge=20, le=5000)
    geofence_enforced: Optional[bool] = None
    ping_interval_s: Optional[int] = Field(None, ge=15, le=900)
    workday_start: Optional[str] = None
    late_grace_min: Optional[int] = Field(None, ge=0, le=240)
    default_task_points: Optional[int] = Field(None, ge=0, le=1000)
    late_points_pct: Optional[int] = Field(None, ge=0, le=100)
    on_time_checkin_points: Optional[int] = Field(None, ge=0, le=1000)


@router.get("/settings")
def read_settings(p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    s = get_settings(db, p.business_id)
    db.commit()
    return settings_out(s)


@router.patch("/settings")
def update_settings(req: SettingsUpdate, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    s = get_settings(db, p.business_id)
    data = req.model_dump(exclude_none=True)
    if "workday_start" in data:
        try:
            parse_hhmm(data["workday_start"])
        except (ValueError, AttributeError):
            raise HTTPException(status_code=422, detail="workday_start must be HH:MM")
    for k, v in data.items():
        setattr(s, k, v)
    log_activity(db, p, "settings.update", entity="settings", summary=", ".join(sorted(data)))
    db.commit()
    return settings_out(s)
