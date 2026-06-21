"""
core/api/staff.py — staff (sub-account) management for one business.
====================================================================
An owner creates cashier logins that SHARE the owner's business data: the staff
User row carries `parent_business_id` = the owner's id, and at login their JWT
`id` claim (the data scope used by every route) is set to that parent id. So a
cashier transparently sees and bills against the owner's shop.

All routes here are owner-only (`restrict_cashier`) and scoped to the caller's
business — owner A can never see or touch owner B's staff.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import User
from services.auth import restrict_cashier, hash_password

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.staff")

# Roles an owner may grant to a staff sub-account today.
ALLOWED_STAFF_ROLES = {"cashier"}


class CreateStaff(BaseModel):
    username: str
    password: str
    role: str = "cashier"


class UpdateStaff(BaseModel):
    role: Optional[str] = None
    password: Optional[str] = None


def _staff_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "business_id": u.parent_business_id,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _validate_password(pw: str) -> None:
    if (len(pw) < 8 or not any(c.isupper() for c in pw)
            or not any(c.islower() for c in pw) or not any(c.isdigit() for c in pw)):
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters with an upper-case letter, a lower-case letter and a number.",
        )


def _validate_role(role: str) -> str:
    r = (role or "cashier").lower()
    if r not in ALLOWED_STAFF_ROLES:
        raise HTTPException(status_code=422, detail=f"Role must be one of {sorted(ALLOWED_STAFF_ROLES)}")
    return r


@router.get("/staff")
def list_staff(current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """List the staff sub-accounts of the caller's business."""
    bid = current_user["id"]
    staff = (
        db.query(User)
        .filter(User.parent_business_id == bid)
        .order_by(User.username.asc())
        .all()
    )
    return [_staff_out(u) for u in staff]


@router.post("/staff", status_code=201)
def create_staff(req: CreateStaff, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Owner creates a staff login (cashier) that shares this business's data."""
    bid = current_user["id"]
    role = _validate_role(req.role)
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    _validate_password(req.password)

    staff = User(
        username=req.username,
        password=hash_password(req.password),
        business_name=current_user.get("business_name"),
        role=role,
        parent_business_id=bid,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    logger.info("[STAFF] created '%s' (role=%s) under business %s", staff.username, role, bid)
    return _staff_out(staff)


@router.patch("/staff/{staff_id}")
def update_staff(staff_id: int, req: UpdateStaff,
                 current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Change a staff member's role or reset their password (this business only)."""
    bid = current_user["id"]
    staff = db.query(User).filter(User.id == staff_id, User.parent_business_id == bid).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")
    if req.role is not None:
        staff.role = _validate_role(req.role)
    if req.password is not None:
        _validate_password(req.password)
        staff.password = hash_password(req.password)
    db.commit()
    db.refresh(staff)
    logger.info("[STAFF] updated %s under business %s", staff_id, bid)
    return _staff_out(staff)


@router.delete("/staff/{staff_id}")
def delete_staff(staff_id: int, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Remove a staff login (this business only)."""
    bid = current_user["id"]
    staff = db.query(User).filter(User.id == staff_id, User.parent_business_id == bid).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")
    db.delete(staff)
    db.commit()
    logger.info("[STAFF] deleted %s under business %s", staff_id, bid)
    return {"deleted": staff_id}
