"""
core/api/identity.py
====================
FastAPI routes for public BizIDs lookup and profile management.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.db import get_db
from database.models import User
from core.models import B2BConnection, BusinessSettings
from services.auth import restrict_cashier

router = APIRouter(tags=["biz_id"])
logger = logging.getLogger("bizassist.core.api.biz_id")


@router.get("/bizid")
def get_my_bizid(current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Get the logged-in user's own public BizID."""
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"public_id": user.public_id}


@router.get("/bizid/{code}")
def lookup_bizid(code: str, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """
    Public lookup for a BizID. Returns ONLY safe public profile data.
    Leaks NO transactional data or cost margins.
    """
    target = db.query(User).filter(User.public_id == code).first()
    if not target:
        raise HTTPException(status_code=404, detail="BizID not found")

    # Find business type
    settings = db.query(BusinessSettings).filter(BusinessSettings.business_id == target.id).first()
    biz_type = settings.template_key if settings else "general"

    # Privacy gate: contact details are revealed only once an accepted connection exists.
    me = current_user["id"]
    connected = me == target.id or (
        db.query(B2BConnection)
        .filter(
            B2BConnection.status == "accepted",
            ((B2BConnection.seller_business_id == target.id) & (B2BConnection.buyer_business_id == me))
            | ((B2BConnection.seller_business_id == me) & (B2BConnection.buyer_business_id == target.id)),
        )
        .first()
        is not None
    )

    # ── Network reachability ────────────────────────────────────────────────
    # B2B is cloud-mediated: a connection request is a row in the CLOUD database
    # that the counterparty's app has to read. A business running in pure LOCAL
    # mode never talks to the cloud, so a request addressed to it would sit
    # there unseen forever. Telling the sender that up front beats letting them
    # wait on a reply that can't arrive.
    #
    # `reachable` is deliberately coarse and non-identifying — it says whether
    # this business can receive network traffic, nothing about its data.
    hosting_mode = "local"
    try:
        import json as _json
        blob = _json.loads(target.settings) if target.settings else {}
        hosting_mode = (blob.get("general") or {}).get("hosting_mode") or "local"
    except Exception:
        pass
    reachable = hosting_mode in ("hybrid", "cloud")

    out = {
        "public_id": target.public_id,
        "business_name": target.business_name,
        "business_type": biz_type,
        "state_code": target.state_code,
        "accepts_orders": reachable,
        "connected": connected,
        "reachable": reachable,
        # 'cloud' | 'hybrid' | 'local' — coarse enough to be safe to expose, and
        # it is what the connect form needs to explain WHY a request would fail.
        "network_mode": hosting_mode,
    }
    if connected:
        out.update({"address": target.address, "phone": target.phone, "email": target.email})
    else:
        out.update({"address": None, "phone": None, "email": None})
    logger.info("[CONN] bizid lookup biz=%s target=%s connected=%s", me, target.id, connected)
    return out
