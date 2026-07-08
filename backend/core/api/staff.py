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
import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
import os

from database.db import get_db
from database.models import User
from services.auth import restrict_cashier, hash_password

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.staff")

# Roles an owner may grant to a staff sub-account today.
ALLOWED_STAFF_ROLES = {"cashier", "supply adder"}


class CreateStaff(BaseModel):
    username: str
    password: str
    role: str = "cashier"
    counter_prefix: Optional[str] = None   # POS counter series for this login (§9.3a)


class UpdateStaff(BaseModel):
    role: Optional[str] = None
    password: Optional[str] = None
    counter_prefix: Optional[str] = None   # set/change this login's POS counter series


def _norm_prefix(p: Optional[str]) -> Optional[str]:
    """Normalise a counter prefix to a short alnum token (no trailing '-').
    Empty/None → None (falls back to the default 'INV' series at billing time)."""
    if p is None:
        return None
    import re
    token = re.sub(r"[^A-Za-z0-9_]", "", p.strip()).rstrip("-")[:8]
    return token or None


def _push_staff_to_cloud(business_id: int, staff_records: list) -> None:
    """
    Fire-and-forget: push staff records to cloud immediately after a CRUD op.
    Runs in a background thread so the local API response is never blocked.
    Only active on the local (SQLite) backend.
    """
    # Only run on local backends (SQLite DB). Cloud instances push to themselves.
    _db_url = os.environ.get("DATABASE_URL", "sqlite")
    if not _db_url.startswith("sqlite"):
        return

    def _run():
        try:
            import httpx
            from services.sync_worker import _get_cloud_token, CLOUD_URL
            token = _get_cloud_token(business_id)
            if not token:
                logger.warning("[STAFF-SYNC] No cloud token available for business %s — staff push skipped", business_id)
                return
            resp = httpx.post(
                f"{CLOUD_URL}/api/sync/staff-push",
                json={"staff": staff_records},
                headers={"Authorization": f"Bearer {token}"},
                timeout=8.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                logger.info("[STAFF-SYNC] Pushed %d staff record(s) to cloud (upserted=%s deleted=%s)",
                            len(staff_records), data.get("upserted"), data.get("deleted"))
            else:
                logger.warning("[STAFF-SYNC] Cloud returned %s: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("[STAFF-SYNC] Push failed (non-critical): %s", e)

    threading.Thread(target=_run, daemon=True).start()


def _staff_out(u: User) -> dict:
    return {
        "id": u.id,
        # Display the per-business bare name ("counter_1"), not the internal
        # global-unique username. Falls back to username for legacy/owner rows.
        "username": getattr(u, "staff_login_name", None) or u.username,
        "role": u.role,
        "business_id": u.parent_business_id,
        "counter_prefix": getattr(u, "counter_prefix", None),
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _internal_staff_username(db: Session, bid: int, bare_name: str) -> str:
    """Derive a GLOBALLY-unique internal `username` for a staff row (§9.5). Prefer
    the bare name when it's globally free (keeps simple cases clean + backward
    compatible); only on a cross-business collision (e.g. a 2nd business adding
    'counter_1') namespace it as '<bare>__<owner_id>'. Staff log in owner → counter,
    not by this value."""
    if db.query(User.id).filter(User.username == bare_name).first() is None:
        return bare_name
    base = f"{bare_name}__{bid}"
    cand = base
    n = 1
    while db.query(User.id).filter(User.username == cand).first() is not None:
        n += 1
        cand = f"{base}_{n}"
    return cand


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
    """Owner creates a staff login that shares this business's data. The name is
    per-BUSINESS (§9.5): two businesses can both have 'counter_1'. The bare name is
    stored as `staff_login_name`; the global-unique `username` is auto-derived."""
    bid = current_user["id"]
    role = _validate_role(req.role)
    bare_name = (req.username or "").strip()
    if not bare_name:
        raise HTTPException(status_code=422, detail="Staff name is required")
    # Uniqueness is PER-BUSINESS now (not global) — only clash within this owner.
    dup = (
        db.query(User.id)
        .filter(User.parent_business_id == bid,
                func.lower(User.staff_login_name) == bare_name.lower())
        .first()
    )
    if dup:
        raise HTTPException(status_code=400, detail="A staff member with this name already exists in your business")
    _validate_password(req.password)

    staff = User(
        username=_internal_staff_username(db, bid, bare_name),
        staff_login_name=bare_name,
        password=hash_password(req.password),
        business_name=current_user.get("business_name"),
        role=role,
        parent_business_id=bid,
        counter_prefix=_norm_prefix(req.counter_prefix),
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    logger.info("[STAFF] created '%s' (internal=%s, role=%s) under business %s",
                bare_name, staff.username, role, bid)
    # Immediately sync to cloud so the cashier can log in from any device
    _push_staff_to_cloud(bid, [{
        "staff_login_name": staff.staff_login_name,
        "internal_username": staff.username,
        "hashed_password": staff.password,
        "role": staff.role,
        "counter_prefix": staff.counter_prefix,
        "deleted": False,
    }])
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
    if req.counter_prefix is not None:
        staff.counter_prefix = _norm_prefix(req.counter_prefix)
    db.commit()
    db.refresh(staff)
    logger.info("[STAFF] updated %s under business %s", staff_id, bid)
    # Re-sync to cloud so password/role/counter changes are immediately available
    _push_staff_to_cloud(bid, [{
        "staff_login_name": staff.staff_login_name,
        "internal_username": staff.username,
        "hashed_password": staff.password,
        "role": staff.role,
        "counter_prefix": staff.counter_prefix,
        "deleted": False,
    }])
    return _staff_out(staff)


@router.delete("/staff/{staff_id}")
def delete_staff(staff_id: int, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Remove a staff login (this business only)."""
    bid = current_user["id"]
    staff = db.query(User).filter(User.id == staff_id, User.parent_business_id == bid).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")
    bare = staff.staff_login_name or staff.username
    db.delete(staff)
    db.commit()
    logger.info("[STAFF] deleted %s under business %s", staff_id, bid)
    # Immediately remove from cloud so deleted cashiers can no longer log in
    _push_staff_to_cloud(bid, [{
        "staff_login_name": bare,
        "internal_username": "",
        "hashed_password": "",
        "role": "",
        "counter_prefix": None,
        "deleted": True,
    }])
    return {"deleted": staff_id}
