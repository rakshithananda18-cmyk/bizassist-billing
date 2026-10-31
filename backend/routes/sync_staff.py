"""
routes/sync_staff.py
=====================
Cloud-side endpoint that receives staff (sub-account) records from a local
backend and upserts them into the cloud DB.

Why a dedicated route instead of going through /api/sync/push:
  - Staff users carry hashed passwords — the generic sync entity pipeline
    intentionally excludes `users` to avoid leaking identity data through
    the normal LWW change log.
  - Staff sync is triggered immediately on create / update / delete on the
    local backend (not on the 25-30s data-sync cycle) so that cashier logins
    are available on the cloud within seconds of being created.

Auth: same cloud-issued JWT that the sync worker already uses.
"""
from __future__ import annotations
import logging
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import User
from services.auth import (
    require_business_owner,
    resolve_business_id_in_db,
    bump_token_version,
    clear_token_version_cache,
)

logger = logging.getLogger("bizassist.sync.staff")
router = APIRouter(tags=["sync"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class StaffRecord(BaseModel):
    staff_login_name: str            # bare per-business name, e.g. "counter_1"
    internal_username: str           # globally-unique username stored in DB
    hashed_password: str             # bcrypt/argon2 hash — never plaintext
    # This endpoint replicates staff accounts; it can never provision an
    # owner-level role from a client-controlled payload.
    role: Literal["cashier", "supply adder"] = "cashier"
    counter_prefix: Optional[str] = None
    deleted: bool = False            # True → remove this staff from cloud


from services.control_outbox import ControlEnvelope


class StaffPushRequest(ControlEnvelope):
    staff: List[StaffRecord]


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/api/sync/staff-push")
def sync_staff_push(
    req: StaffPushRequest,
    current_user: dict = Depends(require_business_owner),
    db: Session = Depends(get_db),
):
    """
    Upsert / delete staff records for this business on the cloud DB.
    Called by the local backend immediately after staff CRUD operations.

    The caller is the local backend acting as the business owner — JWT `id`
    claim resolves to the owner business_id on cloud (same as /api/sync/push).
    """
    public_id = str(current_user.get("public_id") or "").strip()
    if not public_id:
        raise HTTPException(status_code=403, detail="Public business ID (public_id) required for staff sync")

    # Resolve owner_id with strict public_id enforcement (fail-closed if missing/mismatched)
    owner_id = resolve_business_id_in_db(current_user, db, require_public_id=True)
    from services.control_outbox import receive_control_event
    if not receive_control_event(db, owner_id, req):
        return {"status": "ok", "replayed": True, "upserted": 0, "deleted": 0}

    # Sanity: owner must exist on cloud and match public_id
    owner = db.query(User).filter(
        User.id == owner_id,
        User.public_id == public_id,
        User.parent_business_id.is_(None),
    ).first()
    if not owner:
        raise HTTPException(status_code=403, detail="Owner business not found on cloud")

    upserted = 0
    deleted  = 0

    for rec in req.staff:
        bare = (rec.staff_login_name or "").strip().lower()
        if not bare:
            continue

        existing = db.query(User).filter(
            User.parent_business_id == owner_id,
            func.lower(User.staff_login_name) == bare,
        ).first()

        if rec.deleted:
            if existing:
                clear_token_version_cache(existing.id)
                db.delete(existing)
                deleted += 1
                logger.info("[STAFF-SYNC] Deleted staff '%s' for business %s", bare, owner_id)
            continue

        if existing:
            # Update — overwrite password hash, role, counter_prefix
            # TS-04 fix: If password or role materially changed, invalidate existing cloud sessions
            material_change = (existing.password != rec.hashed_password) or (existing.role != rec.role)
            existing.password        = rec.hashed_password
            existing.role            = rec.role
            existing.counter_prefix  = rec.counter_prefix
            if material_change:
                bump_token_version(db, existing)
            # Ensure internal username stays consistent
            if existing.username != rec.internal_username:
                existing.username = rec.internal_username
            upserted += 1
            logger.info("[STAFF-SYNC] Updated staff '%s' for business %s (material_change=%s)",
                        bare, owner_id, material_change)
        else:
            # Insert — resolve global username collision on cloud side
            internal = _resolve_username(db, rec.internal_username)
            staff = User(
                username=internal,
                staff_login_name=rec.staff_login_name,
                password=rec.hashed_password,
                business_name=owner.business_name,
                role=rec.role,
                parent_business_id=owner_id,
                counter_prefix=rec.counter_prefix,
            )
            db.add(staff)
            upserted += 1
            logger.info("[STAFF-SYNC] Created staff '%s' (internal=%s) for business %s",
                        bare, internal, owner_id)

    db.commit()
    return {"status": "ok", "upserted": upserted, "deleted": deleted}


def _resolve_username(db: Session, preferred: str) -> str:
    """Return `preferred` if globally free on cloud, else append a suffix."""
    if db.query(User.id).filter(User.username == preferred).first() is None:
        return preferred
    n = 2
    while True:
        candidate = f"{preferred}_c{n}"
        if db.query(User.id).filter(User.username == candidate).first() is None:
            return candidate
        n += 1
