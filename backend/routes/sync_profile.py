"""
routes/sync_profile.py
=======================
Cloud-side endpoint that receives the owner's business profile fields from the
local backend and updates them on the cloud `users` row.

Why separate from /api/sync/push:
  - The `users` table is intentionally excluded from the generic sync pipeline
    (PK / UNIQUE public_id collisions make row-level sync unsafe).
  - Profile fields (business_name, gstin, address, logo, etc.) sit on the
    `users` row and need a targeted, field-level update instead.
  - Called immediately after the owner saves their billing profile on local,
    so invoices printed via the cloud URL always show current details.

Auth: same cloud-issued JWT the sync worker already uses.
"""
from __future__ import annotations
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import User
from services.auth import get_active_user

logger = logging.getLogger("bizassist.sync.profile")
router = APIRouter(tags=["sync"])


# ── Schema ────────────────────────────────────────────────────────────────────

class ProfilePushRequest(BaseModel):
    business_name: Optional[str] = None
    gstin:         Optional[str] = None
    phone:         Optional[str] = None
    email:         Optional[str] = None
    address:       Optional[str] = None
    state_code:    Optional[str] = None
    pan:           Optional[str] = None
    logo:          Optional[str] = None   # base64 data-URL or cloud path
    upi_vpa:       Optional[str] = None


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/api/sync/profile-push")
def sync_profile_push(
    req: ProfilePushRequest,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """
    Update the owner's profile fields on the cloud DB.
    Called immediately after the owner saves their billing profile on local.

    Only fields explicitly included in the request are updated (PATCH semantics):
    a None value means "not provided — leave unchanged".
    """
    owner_id: int = current_user["id"]

    owner = db.query(User).filter(
        User.id == owner_id,
        User.parent_business_id.is_(None),
    ).first()
    if not owner:
        raise HTTPException(status_code=403, detail="Owner not found on cloud")

    updated: list[str] = []

    if req.business_name is not None:
        owner.business_name = req.business_name
        updated.append("business_name")
    if req.gstin is not None:
        owner.gstin = req.gstin
        updated.append("gstin")
    if req.phone is not None:
        owner.phone = req.phone
        updated.append("phone")
    if req.email is not None:
        owner.email = req.email
        updated.append("email")
    if req.address is not None:
        owner.address = req.address
        updated.append("address")
    if req.state_code is not None:
        owner.state_code = req.state_code
        updated.append("state_code")
    if req.pan is not None:
        owner.pan = req.pan
        updated.append("pan")
    if req.logo is not None:
        owner.logo = req.logo
        updated.append("logo")
    if req.upi_vpa is not None:
        owner.upi_vpa = req.upi_vpa
        updated.append("upi_vpa")

    db.commit()
    logger.info("[PROFILE-SYNC] Updated fields %s for business %s", updated, owner_id)
    return {"status": "ok", "updated_fields": updated}
