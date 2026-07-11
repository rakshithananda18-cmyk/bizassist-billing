"""
services/campaign_service.py
============================
Business logic for the Admin Console growth half (REVIEW_1 §4.3):
campaigns / in-app announcements / redeemable offer codes.

Design notes
------------
* Cloud-only feature: routes are behind the same ADMIN_API_ENABLED +
  require_admin wall as the rest of /admin/*. Merchant-facing reads
  (/announcements, /offers/redeem) are plain authenticated routes.
* Audience filters are resolved at READ time (a campaign matches whoever
  qualifies *now*), delivery rows are written lazily on first fetch — so
  "delivered" in the funnel means "the app actually pulled it".
* Offer redemption reuses the users.settings.subscription machinery
  (services/admin_service.set_subscription's shape) — an offer is a
  pre-authorized subscription mutation with an expiry and a redemption cap.
"""
import json
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import (
    User, Campaign, CampaignDelivery, Offer, OfferRedemption,
)
from services.context_cache import invalidate_user_cache

logger = logging.getLogger("bizassist.campaigns")

VALID_CHANNELS = ("in_app", "email", "whatsapp")
VALID_STATUSES = ("draft", "active", "paused", "done")


# ── helpers ──────────────────────────────────────────────────────────────────

def _audience_dict(campaign: Campaign) -> dict:
    try:
        return json.loads(campaign.audience) if campaign.audience else {}
    except Exception:
        return {}


def _effective_plan(user: User) -> str:
    from services.admin_service import effective_plan
    return effective_plan(user)


def _business_types(business_id: int, db: Session) -> list:
    """Resolved vertical list for a business (BusinessSettings.business_types,
    falling back to [template_key]). Empty list when unset."""
    try:
        from core.models import BusinessSettings
        row = db.query(BusinessSettings).filter(BusinessSettings.business_id == business_id).first()
        if not row:
            return []
        if row.business_types:
            try:
                types = json.loads(row.business_types)
                if isinstance(types, list):
                    return [str(t) for t in types]
            except Exception:
                pass
        return [row.template_key] if row.template_key else []
    except Exception:
        return []


def matches_audience(campaign: Campaign, owner: User, db: Session) -> bool:
    """True when `owner` (a business owner row) qualifies for the campaign.
    Empty/missing filter keys match everyone — filters only narrow."""
    aud = _audience_dict(campaign)
    if not aud:
        return True

    bizids = aud.get("bizids") or []
    if bizids and (owner.public_id or "") not in bizids:
        return False

    plans = aud.get("plans") or []
    if plans and _effective_plan(owner) not in [p.lower() for p in plans]:
        return False

    types = aud.get("business_types") or []
    if types:
        mine = set(_business_types(owner.id, db))
        if not mine.intersection(set(types)):
            return False

    return True


def _is_live(campaign: Campaign, now: datetime = None) -> bool:
    now = now or datetime.utcnow()
    if campaign.status != "active":
        return False
    if campaign.starts_at and campaign.starts_at > now:
        return False
    if campaign.ends_at and campaign.ends_at < now:
        return False
    return True


def _owner_row(business_id: int, db: Session) -> User:
    """Resolve the OWNER row for a token's business id (staff tokens carry the
    owner's id as `id`, so this is normally a direct hit)."""
    owner = db.query(User).filter(User.id == business_id).first()
    if owner is not None and owner.parent_business_id:
        owner = db.query(User).filter(User.id == owner.parent_business_id).first() or owner
    return owner


# ── admin: campaign CRUD ─────────────────────────────────────────────────────

def create_campaign(body, admin: User, db: Session) -> dict:
    channel = (body.channel or "in_app").lower()
    if channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail=f"Invalid channel. Valid: {', '.join(VALID_CHANNELS)}")
    if channel != "in_app":
        # Honest guard: email/whatsapp sends need the notifier integration —
        # accept the row (drafting is fine) but refuse to activate it.
        if (body.status or "draft") == "active":
            raise HTTPException(status_code=400,
                                detail="Only in_app campaigns can be activated today — "
                                       "email/whatsapp delivery isn't wired yet.")
    status = (body.status or "draft").lower()
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Valid: {', '.join(VALID_STATUSES)}")
    if body.offer_code:
        offer = db.query(Offer).filter(Offer.code == body.offer_code.strip().upper()).first()
        if not offer:
            raise HTTPException(status_code=400, detail=f"Offer code '{body.offer_code}' does not exist — create the offer first.")

    c = Campaign(
        title=body.title.strip(),
        body_md=body.body_md,
        channel=channel,
        audience=json.dumps(body.audience) if body.audience else None,
        offer_code=(body.offer_code or "").strip().upper() or None,
        status=status,
        starts_at=_parse_dt(body.starts_at),
        ends_at=_parse_dt(body.ends_at),
        created_by=getattr(admin, "username", None),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return campaign_view(c, db)


def _parse_dt(val):
    if not val:
        return None
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {val!r} (use ISO format)")


def set_campaign_status(campaign_id: int, status: str, db: Session) -> dict:
    status = (status or "").lower()
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Valid: {', '.join(VALID_STATUSES)}")
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if status == "active" and c.channel != "in_app":
        raise HTTPException(status_code=400,
                            detail="Only in_app campaigns can be activated today.")
    c.status = status
    db.commit()
    return campaign_view(c, db)


def list_campaigns(db: Session) -> list:
    rows = db.query(Campaign).order_by(Campaign.id.desc()).all()
    return [campaign_view(c, db) for c in rows]


def campaign_view(c: Campaign, db: Session) -> dict:
    delivered = db.query(func.count(CampaignDelivery.id)).filter(
        CampaignDelivery.campaign_id == c.id).scalar() or 0
    seen = db.query(func.count(CampaignDelivery.id)).filter(
        CampaignDelivery.campaign_id == c.id, CampaignDelivery.seen_at.isnot(None)).scalar() or 0
    clicked = db.query(func.count(CampaignDelivery.id)).filter(
        CampaignDelivery.campaign_id == c.id, CampaignDelivery.clicked_at.isnot(None)).scalar() or 0
    dismissed = db.query(func.count(CampaignDelivery.id)).filter(
        CampaignDelivery.campaign_id == c.id, CampaignDelivery.dismissed_at.isnot(None)).scalar() or 0
    return {
        "id": c.id, "title": c.title, "body_md": c.body_md, "channel": c.channel,
        "audience": _audience_dict(c), "offer_code": c.offer_code,
        "status": c.status, "live": _is_live(c),
        "starts_at": c.starts_at.isoformat() if c.starts_at else None,
        "ends_at": c.ends_at.isoformat() if c.ends_at else None,
        "created_by": c.created_by,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "stats": {"delivered": delivered, "seen": seen, "clicked": clicked, "dismissed": dismissed},
    }


def preview_audience(audience: dict, db: Session) -> dict:
    """Admin-side dry run: how many businesses would this filter reach?"""
    fake = Campaign(audience=json.dumps(audience or {}), status="active")
    owners = db.query(User).filter(
        User.parent_business_id.is_(None), User.role != "admin").all()
    matched = [o for o in owners if matches_audience(fake, o, db)]
    return {"total_businesses": len(owners), "matched": len(matched),
            "sample": [{"business_id": o.id, "business_name": o.business_name,
                        "bizid": o.public_id} for o in matched[:10]]}


# ── admin: offers ────────────────────────────────────────────────────────────

def create_offer(body, admin: User, db: Session) -> dict:
    code = (body.code or "").strip().upper()
    if not code or len(code) < 4:
        raise HTTPException(status_code=400, detail="Offer code must be at least 4 characters.")
    if db.query(Offer).filter(Offer.code == code).first():
        raise HTTPException(status_code=400, detail=f"Offer code '{code}' already exists.")
    effect = body.effect or {}
    plan = (effect.get("plan") or "").lower()
    days = effect.get("days")
    if plan != "pro" or not isinstance(days, int) or days < 1 or days > 3650:
        raise HTTPException(status_code=400,
                            detail='Offer effect must be {"plan": "pro", "days": 1..3650}.')
    o = Offer(
        code=code,
        description=body.description,
        effect=json.dumps({"plan": plan, "days": days}),
        max_redemptions=body.max_redemptions,
        redeem_by=_parse_dt(body.redeem_by),
        active=True,
        created_by=getattr(admin, "username", None),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return offer_view(o)


def list_offers(db: Session) -> list:
    return [offer_view(o) for o in db.query(Offer).order_by(Offer.id.desc()).all()]


def set_offer_active(offer_id: int, active: bool, db: Session) -> dict:
    o = db.query(Offer).filter(Offer.id == offer_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Offer not found")
    o.active = bool(active)
    db.commit()
    return offer_view(o)


def offer_view(o: Offer) -> dict:
    try:
        effect = json.loads(o.effect)
    except Exception:
        effect = {}
    return {
        "id": o.id, "code": o.code, "description": o.description, "effect": effect,
        "max_redemptions": o.max_redemptions, "redeemed_count": o.redeemed_count or 0,
        "redeem_by": o.redeem_by.isoformat() if o.redeem_by else None,
        "active": bool(o.active), "created_by": o.created_by,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


# ── merchant: announcements feed ─────────────────────────────────────────────

def announcements_for(business_id: int, db: Session) -> list:
    """Live in_app campaigns this business qualifies for, minus dismissed ones.
    Writes the delivery row on first fetch (that IS the 'delivered' event)."""
    owner = _owner_row(business_id, db)
    if owner is None:
        return []

    now = datetime.utcnow()
    campaigns = db.query(Campaign).filter(
        Campaign.status == "active", Campaign.channel == "in_app").all()

    out = []
    for c in campaigns:
        if not _is_live(c, now) or not matches_audience(c, owner, db):
            continue
        d = db.query(CampaignDelivery).filter(
            CampaignDelivery.campaign_id == c.id,
            CampaignDelivery.business_id == owner.id).first()
        if d is None:
            d = CampaignDelivery(campaign_id=c.id, business_id=owner.id, delivered_at=now)
            db.add(d)
            try:
                db.commit()
            except Exception:
                db.rollback()   # unique-constraint race from a second device — reread
                d = db.query(CampaignDelivery).filter(
                    CampaignDelivery.campaign_id == c.id,
                    CampaignDelivery.business_id == owner.id).first()
        if d is not None and d.dismissed_at is not None:
            continue
        out.append({
            "id": c.id, "title": c.title, "body_md": c.body_md,
            "offer_code": c.offer_code,
            "starts_at": c.starts_at.isoformat() if c.starts_at else None,
            "ends_at": c.ends_at.isoformat() if c.ends_at else None,
        })
    return out


def ack_announcement(business_id: int, campaign_id: int, event: str, db: Session) -> dict:
    """Record seen / clicked / dismissed for the funnel."""
    if event not in ("seen", "clicked", "dismissed"):
        raise HTTPException(status_code=400, detail="event must be seen|clicked|dismissed")
    owner = _owner_row(business_id, db)
    if owner is None:
        raise HTTPException(status_code=404, detail="Business not found")
    d = db.query(CampaignDelivery).filter(
        CampaignDelivery.campaign_id == campaign_id,
        CampaignDelivery.business_id == owner.id).first()
    if d is None:
        d = CampaignDelivery(campaign_id=campaign_id, business_id=owner.id)
        db.add(d)
    now = datetime.utcnow()
    if event == "seen" and d.seen_at is None:
        d.seen_at = now
    elif event == "clicked":
        d.clicked_at = d.clicked_at or now
        d.seen_at = d.seen_at or now
    elif event == "dismissed":
        d.dismissed_at = d.dismissed_at or now
        d.seen_at = d.seen_at or now
    db.commit()
    return {"status": "ok"}


# ── merchant: offer redemption ───────────────────────────────────────────────

def redeem_offer(business_id: int, code: str, db: Session) -> dict:
    """Validate + apply an offer code to the calling business. Owner-only
    (route enforces). Applies the plan grant through users.settings.subscription
    — identical shape to an admin grant, so require_plan/effective_plan and the
    console all see it natively."""
    code = (code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Enter an offer code.")

    owner = _owner_row(business_id, db)
    if owner is None:
        raise HTTPException(status_code=404, detail="Business not found")

    offer = db.query(Offer).filter(Offer.code == code).first()
    now = datetime.utcnow()
    if not offer or not offer.active:
        raise HTTPException(status_code=404, detail="Invalid or inactive offer code.")
    if offer.redeem_by and offer.redeem_by < now:
        raise HTTPException(status_code=410, detail="This offer has expired.")
    if offer.max_redemptions is not None and (offer.redeemed_count or 0) >= offer.max_redemptions:
        raise HTTPException(status_code=410, detail="This offer has reached its redemption limit.")
    already = db.query(OfferRedemption).filter(
        OfferRedemption.offer_id == offer.id,
        OfferRedemption.business_id == owner.id).first()
    if already:
        raise HTTPException(status_code=409, detail="You have already redeemed this offer.")

    effect = json.loads(offer.effect)
    days = int(effect.get("days", 30))

    # Extend from the current expiry when a live grant exists (stacking),
    # else from now.
    try:
        settings = json.loads(owner.settings) if owner.settings else {}
    except Exception:
        settings = {}
    base = now
    sub = settings.get("subscription") or {}
    if (sub.get("plan") == "pro") and sub.get("expires_at"):
        try:
            cur = datetime.fromisoformat(str(sub["expires_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
            if cur > now:
                base = cur
        except Exception:
            pass
    expires = base + timedelta(days=days)

    settings["subscription"] = {
        "plan": "pro",
        "status": "active",
        "expires_at": expires.isoformat(),
        "granted_by": f"offer:{offer.code}",
        "granted_at": now.isoformat(),
        "note": offer.description or f"Offer code {offer.code}",
    }
    owner.settings = json.dumps(settings)
    offer.redeemed_count = (offer.redeemed_count or 0) + 1
    db.add(OfferRedemption(offer_id=offer.id, business_id=owner.id, redeemed_at=now))
    db.commit()
    invalidate_user_cache(owner.id)
    logger.info("[OFFER] business=%s redeemed %s → pro until %s", owner.id, offer.code, expires.isoformat())
    return {"status": "success",
            "message": f"Offer applied — Pro plan active until {expires.strftime('%d %b %Y')}.",
            "plan": "pro", "expires_at": expires.isoformat()}
