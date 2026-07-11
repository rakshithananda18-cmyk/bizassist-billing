"""
routes/campaigns.py
===================
Promotions & offers (Admin Console growth half, REVIEW_1 §4.3) + sync doctor.

Two surfaces, one file:
  /admin/campaigns*, /admin/offers*, /admin/sync-doctor
      — behind svc.require_admin (which enforces the fail-closed
        ADMIN_API_ENABLED gate). Mutations pass `action` for the audit log.
  /announcements*, /offers/redeem
      — merchant-facing, owner-gated (cashiers never see promos), no admin
        gate: these must work on customer installs pointing at the cloud.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from services.auth import get_active_user, require_owner
import services.admin_service as svc
import services.campaign_service as camp

router = APIRouter()
logger = logging.getLogger("bizassist.routes.campaigns")


# ── Schemas ───────────────────────────────────────────────────────────────────

class CampaignCreateRequest(BaseModel):
    title:      str
    body_md:    str
    channel:    str = "in_app"           # in_app | email | whatsapp
    audience:   Optional[dict] = None    # {"plans": [...], "business_types": [...], "bizids": [...]}
    offer_code: Optional[str] = None
    status:     str = "draft"            # draft | active
    starts_at:  Optional[str] = None     # ISO datetime
    ends_at:    Optional[str] = None


class CampaignStatusRequest(BaseModel):
    status: str                          # draft | active | paused | done


class AudiencePreviewRequest(BaseModel):
    audience: Optional[dict] = None


class OfferCreateRequest(BaseModel):
    code:            str
    description:     Optional[str] = None
    effect:          dict                # {"plan": "pro", "days": 30}
    max_redemptions: Optional[int] = None
    redeem_by:       Optional[str] = None


class OfferActiveRequest(BaseModel):
    active: bool


class AckRequest(BaseModel):
    event: str                           # seen | clicked | dismissed


class RedeemRequest(BaseModel):
    code: str


# ── Admin: campaigns ─────────────────────────────────────────────────────────

@router.get("/admin/campaigns")
def admin_list_campaigns(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return camp.list_campaigns(db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/campaigns GET: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/campaigns")
def admin_create_campaign(body: CampaignCreateRequest,
                          current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        admin = svc.require_admin(current_user["id"], db, action="create_campaign",
                                  details={"title": body.title, "channel": body.channel,
                                           "status": body.status})
        return camp.create_campaign(body, admin, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/campaigns POST: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/campaigns/{campaign_id}/status")
def admin_set_campaign_status(campaign_id: int, body: CampaignStatusRequest,
                              current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db, action="set_campaign_status",
                          details={"campaign_id": campaign_id, "status": body.status})
        return camp.set_campaign_status(campaign_id, body.status, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/campaigns/%s/status: %s", campaign_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/campaigns/preview-audience")
def admin_preview_audience(body: AudiencePreviewRequest,
                           current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Dry run: how many businesses match this filter right now?"""
    try:
        svc.require_admin(current_user["id"], db)
        return camp.preview_audience(body.audience or {}, db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/campaigns/preview-audience: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Admin: offers ────────────────────────────────────────────────────────────

@router.get("/admin/offers")
def admin_list_offers(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db)
        return camp.list_offers(db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/offers GET: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/offers")
def admin_create_offer(body: OfferCreateRequest,
                       current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        admin = svc.require_admin(current_user["id"], db, action="create_offer",
                                  details={"code": body.code, "effect": body.effect,
                                           "max_redemptions": body.max_redemptions})
        return camp.create_offer(body, admin, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/offers POST: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/admin/offers/{offer_id}/active")
def admin_set_offer_active(offer_id: int, body: OfferActiveRequest,
                           current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    try:
        svc.require_admin(current_user["id"], db, action="set_offer_active",
                          details={"offer_id": offer_id, "active": body.active})
        return camp.set_offer_active(offer_id, body.active, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("admin/offers/%s/active: %s", offer_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Admin: sync doctor ───────────────────────────────────────────────────────

@router.get("/admin/sync-doctor")
def admin_sync_doctor(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Red/amber/green sync health per business, worst first."""
    try:
        svc.require_admin(current_user["id"], db)
        return svc.sync_doctor(db)
    except HTTPException: raise
    except Exception as e:
        logger.error("admin/sync-doctor: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Merchant: announcements + offer redemption ───────────────────────────────

@router.get("/announcements")
def get_announcements(current_user: dict = Depends(require_owner), db: Session = Depends(get_db)):
    """Live in-app announcements for this business (owner-level logins only)."""
    try:
        return {"announcements": camp.announcements_for(current_user["id"], db)}
    except Exception as e:
        logger.error("announcements GET: %s", e, exc_info=True)
        # Never break the app shell over a promo — return empty on any error.
        return {"announcements": []}


@router.post("/announcements/{campaign_id}/ack")
def ack_announcement(campaign_id: int, body: AckRequest,
                     current_user: dict = Depends(require_owner), db: Session = Depends(get_db)):
    try:
        return camp.ack_announcement(current_user["id"], campaign_id, body.event, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("announcements/%s/ack: %s", campaign_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/offers/redeem")
def redeem_offer(body: RedeemRequest,
                 current_user: dict = Depends(require_owner), db: Session = Depends(get_db)):
    """Owner redeems an offer code — applies the plan grant immediately."""
    try:
        return camp.redeem_offer(current_user["id"], body.code, db)
    except HTTPException: db.rollback(); raise
    except Exception as e:
        db.rollback(); logger.error("offers/redeem: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
