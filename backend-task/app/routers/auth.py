"""
routers/auth.py — owner sign-in (billing account), staff sign-in (device
policy), SSO exchange from billing, and owner signup.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.billing_models import BillingUser
from app.db import get_db, set_rls_business, utc_now
from app.models import FieldStaff
from app.security import (
    NON_OWNER_ROLES, Principal, burn_password_check, check_login_throttle,
    clear_login_failures, current_principal, decode_billing_token,
    generate_bizid, get_settings, hash_password, new_session_id, owner_token,
    record_login_failure, redeem_billing_ticket, staff_token,
    validate_password_policy, verify_password,
)
from app.services import settings_out, staff_out

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("bizassist.task.auth")

# Billing refuses these username prefixes on real databases (routes/auth.py
# signup) because its maintenance scripts treat them as test fixtures. A row
# created here with such a name would be at risk from those scripts.
_TEST_PREFIXES = ("own_", "test_", "idem_", "pull_", "u_", "o_", "biz_test_", "rec_")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _owner_payload(user: BillingUser) -> dict:
    return {
        "token": owner_token(user),
        "kind": "owner",
        "business_id": user.id,
        "public_id": user.public_id,
        "business_name": user.business_name,
        "name": user.username,
    }


def _resolve_owner(db: Session, business: str) -> Optional[BillingUser]:
    key = (business or "").strip()
    if not key:
        return None
    return db.query(BillingUser).filter(
        (BillingUser.public_id == key.upper()) | (BillingUser.username == key),
        BillingUser.parent_business_id.is_(None),
    ).first()


def _is_owner(user: Optional[BillingUser]) -> bool:
    return bool(user and user.parent_business_id is None
                and (user.role or "").lower() not in NON_OWNER_ROLES)


# ── Owner ─────────────────────────────────────────────────────────────────────

class OwnerLogin(BaseModel):
    username: str
    password: str


@router.post("/owner/login")
def owner_login(req: OwnerLogin, request: Request, db: Session = Depends(get_db)):
    """Same username + password as BizAssist Billing."""
    key = f"owner:{_ip(request)}:{req.username.strip().lower()}"
    check_login_throttle(key)
    user = db.query(BillingUser).filter(BillingUser.username == req.username.strip()).first()
    if not _is_owner(user):
        burn_password_check(req.password)
        record_login_failure(key)
        logger.info("[AUTH] owner login refused (not an owner account) user=%s", req.username)
        raise HTTPException(status_code=401, detail="Invalid owner credentials")
    if not verify_password(req.password, user.password):
        record_login_failure(key)
        raise HTTPException(status_code=401, detail="Invalid owner credentials")
    clear_login_failures(key)
    logger.info("[AUTH] owner login biz=%s BizID=%s", user.id, user.public_id)
    return _owner_payload(user)


class ExchangeRequest(BaseModel):
    # Exactly one: `ticket` is billing's 30-second hand-off ticket (what the
    # Field Team link in billing's sidebar sends as ?sso=); `billing_token` is a
    # billing owner session token.
    ticket: Optional[str] = None
    billing_token: Optional[str] = None


@router.post("/exchange")
def exchange_billing_token(req: ExchangeRequest, db: Session = Depends(get_db)):
    """Single sign-on: a BizAssist Billing OWNER session → a task owner session.
    Billing staff (cashier / supply adder) sessions are refused."""
    if req.ticket:
        claims = redeem_billing_ticket(req.ticket)
    elif req.billing_token:
        claims = decode_billing_token(req.billing_token)
    else:
        raise HTTPException(status_code=422, detail="ticket or billing_token is required")
    try:
        bid, uid = int(claims.get("id")), int(claims.get("user_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail="Owner session required")
    if bid != uid or (claims.get("role") or "").lower() in NON_OWNER_ROLES:
        raise HTTPException(status_code=403, detail="Owner session required")
    user = db.query(BillingUser).filter(BillingUser.id == uid).first()
    if not _is_owner(user):
        raise HTTPException(status_code=403, detail="Owner session required")
    # The BizID in the token must match — integer ids differ between local and
    # cloud databases, the BizID does not (billing core/identity.py).
    if claims.get("public_id") and claims["public_id"] != user.public_id:
        raise HTTPException(status_code=403, detail="Session belongs to a different database")
    if int(claims.get("tv", 0) or 0) != int(user.token_version or 0):
        raise HTTPException(status_code=401, detail="Billing session revoked — sign in again")
    return _owner_payload(user)


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=60)
    password: str
    business_name: str = Field(..., min_length=2, max_length=120)
    phone: Optional[str] = None


@router.post("/owner/signup", status_code=201)
def owner_signup(req: SignupRequest, db: Session = Depends(get_db)):
    """Create a BizAssist account (works in Billing too). Same row shape and
    password policy as billing's /signup."""
    if not config.ALLOW_SIGNUP:
        raise HTTPException(status_code=403, detail="Sign up in BizAssist Billing, then sign in here")
    username = req.username.strip()
    validate_password_policy(req.password)
    if username.lower().startswith(_TEST_PREFIXES) and "test" not in config.DATABASE_URL.lower():
        raise HTTPException(status_code=400, detail="This username is reserved. Choose another.")
    if db.query(BillingUser.id).filter(BillingUser.username == username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    def _make() -> BillingUser:
        return BillingUser(
            username=username,
            password=hash_password(req.password),
            business_name=req.business_name.strip(),
            role="enterprise",
            public_id=generate_bizid(db),
            phone=(req.phone or "").strip() or None,
            token_version=0,
        )

    user = _make()
    db.add(user)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        # Billing's documented failure: rows inserted with explicit ids leave the
        # Postgres sequence behind (routes/auth.py signup handles the same case).
        if db.bind.dialect.name == "postgresql" and ("pk_users" in str(e) or "Key (id)=" in str(e)):
            db.execute(text(
                "SELECT setval(pg_get_serial_sequence('users', 'id'), "
                "COALESCE((SELECT MAX(id) FROM users), 0) + 1, false)"
            ))
            user = _make()
            db.add(user)
            db.commit()
        else:
            raise HTTPException(status_code=400, detail="Username already exists")
    db.refresh(user)
    logger.info("[AUTH] owner signup biz=%s BizID=%s", user.id, user.public_id)
    return _owner_payload(user)


# ── Staff ─────────────────────────────────────────────────────────────────────

class StaffLogin(BaseModel):
    business: str = Field(..., description="Owner's BizID (BA-XXXXXX) or owner username")
    login_name: str
    password: str
    device_id: str = Field(..., min_length=8, max_length=128)
    device_label: Optional[str] = Field(None, max_length=160)


@router.post("/staff/login")
def staff_login(req: StaffLogin, request: Request, db: Session = Depends(get_db)):
    login = req.login_name.strip().lower()
    key = f"staff:{_ip(request)}:{req.business.strip().upper()}:{login}"
    check_login_throttle(key)

    owner = _resolve_owner(db, req.business)
    staff = None
    if _is_owner(owner):
        set_rls_business(db, owner.id)
        staff = db.query(FieldStaff).filter(
            FieldStaff.business_id == owner.id, FieldStaff.login_name == login,
        ).first()
    if staff is None:
        burn_password_check(req.password)
        record_login_failure(key)
        raise HTTPException(status_code=401, detail="Invalid business, name or password")
    if not verify_password(req.password, staff.password_hash):
        record_login_failure(key)
        raise HTTPException(status_code=401, detail="Invalid business, name or password")
    if not staff.is_active:
        raise HTTPException(status_code=403, detail="Your account is disabled. Contact the owner.")

    settings = get_settings(db, owner.id)
    label = (req.device_label or "").strip()[:160] or None
    now = utc_now()
    if settings.device_policy == "bound":
        if staff.bound_device_id and staff.bound_device_id != req.device_id:
            logger.info("[AUTH] staff=%s refused: bound to another device", staff.id)
            raise HTTPException(
                status_code=403,
                detail=(f"This account is locked to another device"
                        f"{' (' + staff.bound_device_label + ')' if staff.bound_device_label else ''}. "
                        "Ask the owner to release it."),
            )
        if not staff.bound_device_id:
            staff.bound_device_id = req.device_id
            staff.bound_device_label = label
            staff.bound_at = now

    previous_device = staff.active_device_id
    staff.active_session_id = new_session_id()  # older sessions now fail the `ses` check
    staff.active_device_id = req.device_id
    staff.active_device_label = label
    staff.last_login = now
    db.commit()
    clear_login_failures(key)
    logger.info("[AUTH] staff login biz=%s staff=%s device_changed=%s",
                owner.id, staff.id, bool(previous_device and previous_device != req.device_id))
    return {
        "token": staff_token(staff, owner.public_id),
        "kind": "staff",
        "business_id": owner.id,
        "public_id": owner.public_id,
        "business_name": owner.business_name,
        "name": staff.name,
        "staff": staff_out(staff),
        "settings": settings_out(settings),
        "signed_out_other_device": bool(previous_device and previous_device != req.device_id),
    }


# ── Common ────────────────────────────────────────────────────────────────────

@router.get("/me")
def me(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    settings = get_settings(db, p.business_id)
    db.commit()
    owner = db.query(BillingUser).filter(BillingUser.id == p.business_id).first()
    base = {
        "kind": p.kind,
        "business_id": p.business_id,
        "public_id": owner.public_id if owner else None,
        "business_name": owner.business_name if owner else None,
        "settings": settings_out(settings),
    }
    if p.kind == "staff":
        base["name"] = p.staff.name
        base["staff"] = staff_out(p.staff)
    else:
        base["name"] = owner.username if owner else None
    return base


@router.post("/logout")
def logout(p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    if p.kind == "staff":
        p.staff.active_session_id = None
        db.commit()
    return {"ok": True}
