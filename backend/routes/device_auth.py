"""Cloud-authenticated owner sessions on a local/LAN installation.

The remote numeric user ID is never used as local identity. Cloud remains the
authority for Google discovery and store creation; this route only mirrors an
already verified owner BizID and refuses to adopt unrelated local accounts.
"""
import json
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import User
from services.auth import create_access_token, get_active_user, hash_password
from services.rate_limiter import check_ip_rate_limit

router = APIRouter()


class CloudSessionRequest(BaseModel):
    token: str
    credential: Optional[str] = None
    password: Optional[str] = None  # Owner-authorized local offline password; never persisted in plaintext.
    local_only: bool = False  # Explicit registration choice, not an inferred plan fallback.


class GoogleDiscoveryRequest(BaseModel):
    credential: str


def _local_only(db):
    if db.get_bind().dialect.name != "sqlite":
        raise HTTPException(404, "Device authentication is available on local installations only.")


def _rate_limit(request):
    result = check_ip_rate_limit(request.client.host if request.client else "unknown")
    if not result["allowed"]:
        raise HTTPException(429, result["reason"])


@router.post("/api/auth/device/google-discovery")
def google_discovery(body: GoogleDiscoveryRequest, request: Request, db: Session = Depends(get_db)):
    _local_only(db)
    _rate_limit(request)
    from routes.auth import _google_owner, _verify_google_credential
    identity = _verify_google_credential(body.credential)
    # Discovery must not link, create, grant trials, or alter a local account.
    owner = _google_owner(db, identity, allow_email=True)
    return {"local_owner_exists": owner is not None}


@router.post("/api/auth/device/cloud-session")
def cloud_session(body: CloudSessionRequest, request: Request,
                  authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    _local_only(db)
    _rate_limit(request)
    from routes.auth import _session_claims
    from routes.sync import _read_verified_cloud_document
    from services.sync_worker import store_cloud_token

    profile = _read_verified_cloud_document("/profile", body.token)
    bizid = (profile.get("public_id") or "").strip()
    username = (profile.get("username") or "").strip()
    if not bizid or not username or (profile.get("role") or "").lower() not in {"owner", "enterprise"}:
        raise HTTPException(403, "A verified cloud business owner is required to set up this device.")
    if authorization:
        current = get_active_user(authorization=authorization, token=None)
        if current.get("public_id") != bizid or (current.get("role") or "").lower() not in {"owner", "enterprise"}:
            raise HTTPException(409, "Sign out before setting up a different business on this device.")

    email = (profile.get("email") or "").strip().lower()
    google_sub = None
    if body.credential:
        from routes.auth import _verify_google_credential
        identity = _verify_google_credential(body.credential)
        # Used only for collision detection. The cloud profile's contact email
        # may have been edited since Google linking, so email equality is not a
        # proof of the Google link. Never write/link this subject locally.
        google_sub = identity["sub"]

    owner = db.query(User).filter(User.public_id == bizid).first()
    collision_terms = [func.lower(User.username) == username.lower()]
    if email:
        collision_terms.append(func.lower(User.email) == email)
    if google_sub:
        collision_terms.append(User.google_id == google_sub)
    collisions = db.query(User).filter(or_(*collision_terms)).all()
    if any(row is not owner for row in collisions):
        raise HTTPException(409, "An existing local account has a different business identity. Nothing was replaced. Sign in to that account to review its cloud connection.")
    if owner and (owner.parent_business_id is not None or (owner.role or "").lower() not in {"owner", "enterprise"}):
        raise HTTPException(409, "The local business identity is not an owner account. Nothing was changed.")
    if owner and google_sub and owner.google_id and owner.google_id != google_sub:
        raise HTTPException(409, "This local owner is linked to a different Google identity. Nothing was changed.")

    if owner is None:
        cloud_settings = _read_verified_cloud_document("/settings", body.token)
        subscription = cloud_settings.get("subscription")
        if not isinstance(subscription, dict):
            raise HTTPException(503, "Cloud subscription verification is incomplete. Try device setup again.")
        state = _read_verified_cloud_document("/api/sync/bootstrap-state", body.token)
        if type(state.get("has_business_data")) is not bool:
            raise HTTPException(503, "Cloud restore readiness verification is incomplete. Retry device setup.")
        from copy import deepcopy
        local_settings = {key: deepcopy(cloud_settings[key]) for key in (
            "general", "transactions", "inventory", "print", "labels") if isinstance(cloud_settings.get(key), dict)}
        general = local_settings.setdefault("general", {})
        for key in ("sync_mode_revision", "device_invoice_namespace", "device_installation_id",
                    "sync_local_only_explicit", "diagnostic_upload_enabled"):
            general.pop(key, None)  # Installation identity and consent never travel with the account.
        general.update(hosting_mode="local", sync_bootstrap_pending=state["has_business_data"])
        if body.local_only:
            general["sync_local_only_explicit"] = True
        local_settings["subscription"] = subscription
        from database.security import allocate_owner_id
        owner = User(id=allocate_owner_id(db), public_id=bizid, username=username,
                     business_name=profile.get("business_name") or username,
                     role="enterprise", password=hash_password(body.password or uuid4().hex),
                     email=email or None, phone=profile.get("phone"),
                     gstin=profile.get("gstin"), address=profile.get("address"), state_code=profile.get("state_code"),
                     pan=profile.get("pan"), logo=profile.get("logo"), counter_prefix=profile.get("counter_prefix"),
                     upi_vpa=profile.get("upi_vpa"), settings=json.dumps(local_settings))
        db.add(owner)
        try:
            db.commit()
            db.refresh(owner)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Local business identity changed during setup. Retry sign-in; no existing business was replaced.") from None
    # No cloud profile fields overwrite an existing local business. Google login
    # is repeated against cloud on every sign-in, so no local subject mutation is
    # necessary to trust this session.
    try:
        store_cloud_token(owner.id, body.token)
    except OSError:
        raise HTTPException(503, "This device could not save its cloud credential. Check device storage and retry sign-in.") from None
    local_token = create_access_token(_session_claims(owner, sid=uuid4().hex))
    return {"status": "ok", "action": "login", "token": local_token,
            "id": owner.id, "user_id": owner.id, "public_id": owner.public_id,
            "username": owner.username, "business_name": owner.business_name,
            "role": owner.role, "counter_prefix": owner.counter_prefix, "db_mode": "local"}
