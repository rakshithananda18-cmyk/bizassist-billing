import logging
import time
from typing import Optional, Literal
from uuid import uuid4
import os
from fastapi import APIRouter, HTTPException, Request, Depends, Query, Body
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from database.db import get_db, DATABASE_URL
from database.models import User
from services.auth import hash_password, verify_password, create_access_token, get_active_user, create_sse_ticket, require_owner, require_business_owner, get_active_user_or_ticket, redeem_sse_ticket, verify_ticket, _validate_token_version, session_rejected, SESSION_REJECTION_HEADERS
from services.rate_limiter import check_ip_rate_limit
from services.registration_policy import TRIAL_DAYS, normalize_phone, phone_key

router = APIRouter()
logger = logging.getLogger("bizassist.auth")

# Auto-detect which type of DB this backend is running on.
# The frontend stores this as the user's "home mode" so API requests
# always route back to the correct backend after a mode switch.
_DB_MODE = "cloud" if ("postgresql" in DATABASE_URL or "postgres" in DATABASE_URL) else "local"

# Per-business cooldown for cloud subscription sync (seconds).
# Prevents hammering the cloud on every GET /settings — each hit previously
# triggered a live httpx call which showed as 4-5 "Automatically synced"
# log lines per session. After the activation-code plan is in place this
# whole function can be removed; until then cap it at once per 30 min.
_SUB_SYNC_COOLDOWN_SECS = 1800  # 30 min — after a check the cloud actually answered
_SUB_SYNC_RETRY_SECS = 60       # after one that never happened; see below

# …but only once the answer is "Pro". A FREE business is the one case where the
# answer is expected to change, and to change because a human just paid for it.
# Making them wait up to 30 minutes to see what they bought — with no signal
# that anything is coming — is the worst place in the whole flow to be thrifty.
# A free account also has nothing to sync, so this check is the only cloud call
# it ever makes; asking once a minute costs a request the account is otherwise
# not making at all. Pro keeps the long window: its answer rarely changes and
# there are real sync calls to leave room for.
_SUB_SYNC_FREE_COOLDOWN_SECS = 60
_sub_sync_next: dict[int, float] = {}  # business_id → earliest next cloud check


def _session_claims(user_row: User, *, sid: str, psid=None, owner=None) -> dict:
    holder = owner or user_row
    claims = {
        "id": user_row.parent_business_id or user_row.id,
        "user_id": user_row.id,
        "username": user_row.username,
        "public_id": holder.public_id,
        "business_name": holder.business_name,
        "role": user_row.role,
        "tv": user_row.token_version or 0,
        "sid": sid,
    }
    if psid:
        claims["psid"] = psid
    return claims


class LoginRequest(BaseModel):
    username: str
    password: str
    otp: Optional[str] = None   # TOTP code — required only for admins with 2FA enabled (§4.1)


class ReconcilePasswordRequest(BaseModel):
    username: str
    password: str        # the new password that just succeeded on the cloud
    public_id: str       # cloud's BizID — MUST match the local account's


def _require_loopback_local(request: Request) -> None:
    """Keep device-recovery mutations off cloud and LAN interfaces."""
    if _DB_MODE == "cloud":
        raise HTTPException(status_code=404, detail="This recovery operation is unavailable on cloud servers.")
    host = (request.client.host if request.client else "").lower()
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="This recovery operation is available only from this device.")


def _confirm_with_cloud(username: str, password: str) -> dict:
    """Sign in to the cloud with these credentials FROM THIS BACKEND and return
    the cloud's answer (its `public_id` is the account's BizID).

    The recovery routes below change a local owner's password (and reclaim also
    wipes the business's local data) on the claim that the cloud just accepted
    these credentials. Loopback-only is not enough to trust that claim: a shop
    computer is shared, and every cashier knows the owner's username (staff sign
    in with it) and can read the BizID off the screen. So the claim is checked
    here, never taken from the request."""
    import httpx
    from services.sync_worker import CLOUD_URL
    try:
        r = httpx.post(f"{CLOUD_URL}/login", json={"username": username, "password": password}, timeout=15.0)
    except Exception as e:
        logger.warning("[AUTH] cloud confirmation unreachable for local recovery: %s", e)
        raise HTTPException(status_code=503, detail="Could not reach BizAssist Cloud to confirm this password. "
                                                    "Check the internet connection and try again. Nothing was changed.")
    if r.status_code != 200:
        logger.warning("[AUTH] cloud refused the credentials offered for local recovery (HTTP %s)", r.status_code)
        raise HTTPException(status_code=401, detail="BizAssist Cloud did not accept this password. Nothing was changed.")
    try:
        return r.json() or {}
    except ValueError:
        raise HTTPException(status_code=502, detail="BizAssist Cloud gave an unreadable answer. Nothing was changed.")


@router.post("/api/auth/reconcile_password")
def reconcile_password(req: ReconcilePasswordRequest, request: Request, db: Session = Depends(get_db)):
    """
    Re-sync a LOCAL owner account's password after the SAME credentials
    succeeded on the cloud (password drift → offline login was blocked).

    Identity-safe: the update happens ONLY when the local account's BizID
    (public_id) matches the cloud's. A username that maps to a DIFFERENT
    business on this device is reported as a mismatch and never overwritten —
    so we can't silently log someone into the wrong local business. The cloud
    sign-in is repeated here (_confirm_with_cloud), and the BizID compared is
    the cloud's own, not the request's.
    """
    _require_loopback_local(request)
    uname = (req.username or "").strip()
    user = (db.query(User)
              .filter(User.username == uname, User.parent_business_id.is_(None))
              .first())
    if not user:
        raise HTTPException(status_code=404, detail="No such local owner account")
    cloud_bizid = _confirm_with_cloud(uname, req.password).get("public_id")
    if not cloud_bizid or user.public_id != cloud_bizid:
        raise HTTPException(
            status_code=409,
            detail=(f"Identity mismatch: on this device '{uname}' is the business "
                    f"'{user.business_name}', which is different from the cloud account. "
                    f"Nothing was changed."),
        )
    user.password = hash_password(req.password)
    db.commit()
    logger.info(f"[AUTH] Reconciled local password for '{uname}' (BizID {user.public_id}) from cloud.")
    return {"status": "ok", "business_name": user.business_name, "public_id": user.public_id}


class ReclaimLocalRequest(BaseModel):
    username: str
    password: str                       # new password, already registered on the cloud
    public_id: str                      # freshly-minted cloud BizID to adopt
    business_name: Optional[str] = None


@router.post("/api/auth/reclaim_local")
def reclaim_local(req: ReclaimLocalRequest, request: Request, db: Session = Depends(get_db)):
    """
    LOCAL-ONLY: re-key an ORPHANED local owner account onto a freshly-minted cloud
    identity, then log in. This handles re-registering a username whose CLOUD
    account was deleted — the username is free on the cloud (so cloud signup just
    succeeded and minted a new BizID), but a stale LOCAL mirror still holds it,
    which otherwise makes the local /signup return 400 "Username already exists".

    Safe because: (1) it runs only on the LOCAL backend (localhost trust model,
    single device owner); (2) it is reached ONLY after the cloud accepted a NEW
    signup for this username, proving the old cloud identity is gone; (3) it
    re-keys identity (BizID) + password and does NOT create or merge across
    businesses. When the BizID changes it purges the business's stale local data.

    Point (2) is checked, not assumed: this backend signs in to the cloud with
    the same credentials (_confirm_with_cloud) and requires the cloud to name
    the BizID being adopted. Without that, anyone at this computer who knew the
    owner's username could wipe the business and take over the owner account.
    """
    _require_loopback_local(request)
    if not (req.public_id or "").strip():
        raise HTTPException(status_code=400, detail="public_id (new cloud BizID) is required.")

    uname = (req.username or "").strip()
    user = (db.query(User)
              .filter(User.username == uname, User.parent_business_id.is_(None))
              .first())
    if not user:
        raise HTTPException(status_code=404, detail="No local account to reclaim.")

    cloud = _confirm_with_cloud(uname, req.password)
    if cloud.get("public_id") != req.public_id:
        logger.warning(f"[AUTH] Refused reclaim of '{uname}': the cloud account's BizID is "
                       f"{cloud.get('public_id')!r}, not the requested {req.public_id!r}.")
        raise HTTPException(status_code=409, detail="This BizID is not the cloud account's for these credentials. Nothing was changed.")

    old_bizid = user.public_id
    business_name = cloud.get("business_name") or req.business_name or user.business_name
    if old_bizid and old_bizid != req.public_id:
        from services.admin_service import purge_business_data, record_business_tombstone
        old_name = user.business_name
        result = purge_business_data(user.id, db, delete_owner=False, delete_staff=True, retire_account=True)
        record_business_tombstone(db, public_id=old_bizid, username=uname,
            business_name=old_name, reason="reclaim_rekey")
        if result.get("identity_retained"):
            db.flush()
            user = User(username=uname, role="enterprise")
            db.add(user)
    user.public_id = req.public_id
    user.password = hash_password(req.password)
    user.business_name = business_name
    from services.auth import bump_token_version
    bump_token_version(db, user)

    db.commit()
    db.refresh(user)
    logger.warning(
        f"[AUTH] Reclaimed orphaned local account '{uname}': "
        f"BizID {old_bizid} → {user.public_id} (cloud account was re-registered)."
    )

    token = create_access_token({
        "id": user.id,
        "user_id": user.id,
        "username": user.username,
        "public_id": user.public_id,
        "business_name": user.business_name,
        "role": user.role,
        "tv": user.token_version or 0,
        "sid": uuid4().hex,
    })
    return {
        "token": token,
        "id": user.id,
        "user_id": user.id,
        "username": user.username,
        "public_id": user.public_id,
        "business_name": user.business_name,
        "role": user.role,
        "db_mode": _DB_MODE,
    }


class SignupRequest(BaseModel):
    username: str
    password: str
    business_name: str
    email: Optional[str] = None
    phone: Optional[str] = None  # required for fresh signup; legacy local mirrors may omit it
    # Optional cloud-issued BizID. When the downloaded app registers, it creates
    # the account on the cloud first (the single authority), then mirrors it
    # locally passing the cloud's public_id here so both sides share one BizID.
    # When omitted (web signup / standalone), a new BizID is minted.
    public_id: Optional[str] = None


@router.post("/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    # The typed username is logged only once it is known to be an account's: a
    # password typed into the username box is almost never a real username,
    # and log files travel (support uploads, screenshots).
    shown = "an unknown username"
    logger.info("[AUTH] Login attempt...")
    try:
        # Check IP-based rate limiting
        ip = request.client.host if request.client else "unknown"
        rl = check_ip_rate_limit(ip)
        if not rl["allowed"]:
            raise HTTPException(status_code=429, detail=rl["reason"])

        from database.security import authenticate_identity, username_exists
        user = authenticate_identity(db, req.username, req.password)
        if user or username_exists(db, req.username):
            shown = f"username '{req.username}'"
        if not user:
            logger.warning(f"[AUTH] Failed login for {shown}: invalid credentials")
            raise HTTPException(status_code=401, detail="Invalid credentials")

        # ── Admin 2FA gate (§4.1) ─────────────────────────────────────────────
        # Enforced ONLY when this admin has confirmed a TOTP secret. The
        # distinct "2FA code required" detail tells the console to show the
        # OTP field and re-submit — a wrong code reads differently on purpose.
        if (user.role or "").lower() == "admin":
            try:
                _totp_cfg = (json.loads(user.settings) if user.settings else {}).get("totp") or {}
            except Exception:
                _totp_cfg = {}
            if _totp_cfg.get("enabled") and _totp_cfg.get("secret"):
                from services.totp import verify_code as _verify_totp
                if not req.otp:
                    logger.info(f"[AUTH] Admin '{req.username}' password OK — awaiting 2FA code")
                    raise HTTPException(status_code=401, detail="2FA code required")
                if not _verify_totp(_totp_cfg["secret"], req.otp):
                    logger.warning(f"[AUTH] Admin '{req.username}' failed 2FA verification")
                    raise HTTPException(status_code=401, detail="Invalid 2FA code")

        # (§9.5) Staff are not OFFERED a direct login in the UI — the login screen
        # is owner-gated (owner username → Owner / Staff buttons → /login/staff),
        # and a staff name that collides cross-business gets an internal username
        # they don't know. We keep /login working here for backward compat (API +
        # existing flows); the UI never exposes a direct staff-username login.
        # (A strict server-side block is a clean follow-up, paired with migrating
        #  the test suite + any internal callers to /login/staff.)

        # Staff sub-accounts scope to their owner's business: the JWT `id` (the
        # data scope every route reads) becomes the parent business id, while
        # `user_id` keeps the staff member's own identity.
        business_id = user.parent_business_id or user.id
        business_name = user.business_name
        owner_public_id = user.public_id
        if user.parent_business_id:
            owner = db.query(User).filter(User.id == user.parent_business_id).first()
            if owner:
                business_name = owner.business_name
                owner_public_id = owner.public_id

        token = create_access_token(_session_claims(user, sid=uuid4().hex, psid=None, owner=owner if user.parent_business_id else None))

        # Stamp the account as used. This is what lets the owner tell a real
        # counter from one created during testing and forgotten — a NULL
        # `last_login` means the account has NEVER been logged into, which no
        # other field can express. Best-effort: a failure here must never cost
        # someone their login.
        try:
            from services.dates import utc_now as _utc_now
            user.last_login = _utc_now()
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning("[AUTH] could not stamp last_login for '%s': %s", req.username, e)

        logger.info(f"[AUTH] User '{req.username}' authenticated (role={user.role}, business={business_id}).")
        # Pro/free segregation signal — logged once per login (not per request).
        try:
            from services.auth import subscription_enforced as _enf
            _tier = _subscription_view(user, db).get("plan", "free")
            logger.info("[PLAN] login tier=%s user=%s business=%s enforced=%s",
                        _tier, req.username, business_id, _enf())
        except Exception:
            pass
        return {
            "token": token,
            "id": business_id,
            "user_id": user.id,
            "username": user.username,
            "public_id": owner_public_id,   # BizID — lets the client confirm/unify identity
            "business_name": business_name,
            "role": user.role,
            "counter_prefix": user.counter_prefix,   # POS counter series for this login (§9.3a)
            "db_mode": _DB_MODE,   # 'local' | 'cloud' — tells frontend which backend this account lives on
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Error during login for {shown}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server login error")


class StaffLoginRequest(BaseModel):
    owner_username: str
    staff_login_name: str
    password: str


@router.post("/login/staff")
def staff_login(req: StaffLoginRequest, request: Request, db: Session = Depends(get_db)):
    """(§9.5) Staff login scoped to the owner's business — staff never use a global
    username. Resolve owner → staff by per-business `staff_login_name` → verify
    password → issue the same business-scoped JWT as /login. The JWT carries the
    internal global-unique username (routes resolve by it); the response returns
    the bare name for display."""
    try:
        ip = request.client.host if request.client else "unknown"
        rl = check_ip_rate_limit(ip)
        if not rl["allowed"]:
            raise HTTPException(status_code=429, detail=rl["reason"])

        from database.security import authenticate_identity
        staff = authenticate_identity(db, req.staff_login_name, req.password, req.owner_username)
        if staff is None or staff.parent_business_id is None:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        owner = db.get(User, staff.parent_business_id)
        if owner is None or owner.role == "deleted":
            raise HTTPException(status_code=401, detail="Invalid credentials")

        business_id = owner.id
        token = create_access_token(_session_claims(staff, sid=uuid4().hex, psid=None, owner=owner))
        logger.info(f"[AUTH] Staff '{staff.staff_login_name}' logged into business {business_id} (owner {owner.username}).")
        return {
            "token": token,
            "id": business_id,
            "user_id": staff.id,
            "username": staff.staff_login_name or staff.username,   # bare name for display
            "public_id": owner.public_id,
            "business_name": owner.business_name,
            "role": staff.role,
            "counter_prefix": staff.counter_prefix,
            "db_mode": _DB_MODE,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Staff login error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server login error")


# ---------------------------------------------------------------------------
# PRO TRIAL FOR NEW BUSINESSES
# ---------------------------------------------------------------------------
# Every eligible first-time business registered on the CLOUD starts on Pro for
# 14 days, so a new owner can work on the web straight away, then install
# the desktop app and bring their data down while sync is still Pro. The grant
# is the ordinary `settings.subscription` shape with status "trial", so
# effective_plan() — and every gate built on it, Field Team included — turns it
# on now and off at the end date with no extra plumbing.
#
# Cloud only, and never on the local mirror backend: the cloud is the plan
# authority, and the desktop copies the plan
# down through _sync_subscription_from_cloud like any admin grant.

def _trial_days() -> int:
    return TRIAL_DAYS


def _phone_key(phone: Optional[str]) -> Optional[str]:
    """Canonical, country-aware fingerprint; equivalent formatting matches."""
    return phone_key(phone)


@router.get("/trial-offer")
def trial_offer():
    """Public: whether a business registered now starts on a Pro trial, and for
    how long. The desktop app's Register screen asks the CLOUD before sign-up to
    preselect "Local + Cloud". Only the cloud grants trials, so a local backend
    answers 0. The final word is the signup response: one trial per phone."""
    return {"days": _trial_days() if _DB_MODE == "cloud" else 0}


def _start_trial(user: User, phone: Optional[str], db: Session) -> Optional[dict]:
    """Put a brand-new business on the Pro trial. Returns the subscription it
    wrote, or None when no trial was given."""
    import json
    from datetime import timedelta
    from services.dates import utc_now

    days = _trial_days()
    if days <= 0:
        return None
    key = _phone_key(phone)
    if not key:
        raise ValueError("A valid phone number is required for the first-time trial.")
    if key:
        from database.models import TrialPhoneClaim
        from sqlalchemy.exc import IntegrityError
        if db.get(TrialPhoneClaim, key) is not None:
            return None
        others = db.query(User.phone).filter(
            User.id != user.id,
            User.parent_business_id.is_(None),
            User.phone.isnot(None),
        ).all()
        if any(_phone_key(p) == key for (p,) in others):
            logger.info(f"[TRIAL] No trial for '{user.username}': phone already registered to another business.")
            return None
        # The unique key serialises simultaneous registrations with one phone.
        # The caller owns the outer account+trial transaction.
        try:
            with db.begin_nested():
                db.add(TrialPhoneClaim(phone_hash=key))
                db.flush()
        except IntegrityError:
            if db.get(TrialPhoneClaim, key) is not None:
                return None
            raise

    now = utc_now()
    sub = {
        "plan":       "pro",
        "status":     "trial",
        # A date means access THROUGH that day (expiry_moment), so this is the
        # rest of today plus `days` full days.
        "expires_at": (now.date() + timedelta(days=days)).isoformat(),
        "granted_by": "trial",
        "granted_at": now.isoformat(),
        "note":       f"{days}-day Pro trial at signup",
    }
    s = json.loads(user.settings) if user.settings else {}
    s["subscription"] = sub
    user.settings = json.dumps(s)
    db.flush()
    logger.info(f"[TRIAL] '{user.username}' (BizID {user.public_id}) started a {days}-day Pro trial, ends {sub['expires_at']}.")
    return sub


@router.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    logger.info(f"[AUTH] Signup attempt for username '{req.username}'...")
    try:
        # Legacy local mirrors may have no phone on their older cloud account.
        # Fresh registrations on either platform always require a valid contact.
        phone = None
        if req.phone or _DB_MODE == "cloud" or not (req.public_id or "").strip():
            try:
                phone = normalize_phone(req.phone)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from None
        # Enforce password strength policy
        password = req.password
        if len(password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")
        if not any(c.isupper() for c in password):
            raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter.")
        if not any(c.islower() for c in password):
            raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter.")
        if not any(c.isdigit() for c in password):
            raise HTTPException(status_code=400, detail="Password must contain at least one number.")

        from database.security import username_exists
        if username_exists(db, req.username):
            logger.warning(f"[AUTH] Failed signup: username '{req.username}' already exists.")
            raise HTTPException(status_code=400, detail="Username already exists")

        email = None
        if req.email and req.email.strip():
            clean_email = req.email.strip().lower()
            existing_email = db.query(User).filter(func.lower(User.email) == clean_email).first()
            if existing_email:
                raise HTTPException(status_code=400, detail="An account with this email already exists.")
            email = clean_email
        
        # Test User Policy (leakage prevention):
        # 1. Test usernames (legacy fixture prefixes + 'biz_test_') are ONLY allowed
        #    on a test database, OR when ALLOW_TEST_USERS is explicitly set.
        # 2. Otherwise blocked on production/development DBs to prevent pollution.
        # The ALLOW_TEST_USERS escape hatch exists so a CI/staging run — or a real
        # user whose name happens to start with one of these prefixes — isn't hard-
        # blocked: the operator opts in deliberately rather than relying solely on
        # the fragile "'test' in the DB URL" substring check.
        import os
        db_url = os.environ.get("DATABASE_URL", "")
        allow_test_users = os.environ.get("ALLOW_TEST_USERS", "").lower() in ("1", "true", "yes")
        is_test_db = "test" in db_url
        test_prefixes = ("own_", "test_", "idem_", "pull_", "u_", "o_", "biz_test_", "rec_")
        is_test_username = req.username.startswith(test_prefixes)

        if is_test_username and not (is_test_db or allow_test_users):
            logger.critical(f"[AUTH] Blocked test username '{req.username}' registration attempt on non-test database.")
            raise HTTPException(
                status_code=400,
                detail="Test user registration is not allowed on this database."
            )

        from core.connection.utils import generate_bizid
        # Adopt a cloud-issued BizID when provided (local mirror of a cloud
        # account); otherwise mint a fresh one (web signup / standalone).
        bizid = (req.public_id or "").strip() or generate_bizid(db)
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy import text

        from database.security import allocate_owner_id
        owner_pk = allocate_owner_id(db)
        user = User(
            id=owner_pk,
            username=req.username,
            email=email,
            password=hash_password(req.password),
            business_name=req.business_name,
            role="enterprise",
            public_id=bizid,
            phone=phone,
        )
        db.add(user)
        try:
            db.flush()
        except IntegrityError as e:
            err_str = str(e)
            if "pk_users" in err_str or "users_id_seq" in err_str or "Key (id)=" in err_str:
                db.rollback()
                if db.bind.dialect.name == "postgresql":
                    logger.warning(f"[AUTH] Resyncing Postgres users_id_seq after explicit ID collision for '{req.username}'.")
                    db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 0) + 1, false);"))
                    user = User(
                        username=req.username,
                        email=email,
                        password=hash_password(req.password),
                        business_name=req.business_name,
                        role="enterprise",
                        public_id=bizid,
                        phone=phone,
                    )
                    db.add(user)
                    db.flush()
                else:
                    raise
            else:
                raise
        db.refresh(user)

        # Account, phone claim and trial grant commit together. A grant failure
        # must not leave an eligible new owner stranded on a free account.
        trial = None
        if _DB_MODE == "cloud":
            trial = _start_trial(user, phone, db)
        db.commit()

        if email:
            try:
                from services.brevo_service import brevo_service
                brevo_service.send_welcome_email(email, user.business_name or user.username, user.username)
                brevo_service.sync_contact_to_brevo(
                    email=email,
                    name=user.business_name or user.username,
                    phone=user.phone,
                    attributes={"STORE_NAME": user.business_name or "", "CATEGORY": "general"}
                )
            except Exception as be:
                logger.warning(f"[AUTH] Brevo welcome sync skipped on signup: {be}")

        token = create_access_token(_session_claims(user, sid=uuid4().hex, psid=None, owner=None))

        logger.info(f"[AUTH] User '{req.username}' registered and authenticated.")
        return {
            "token": token,
            "id": user.id,
            "user_id": user.id,
            "username": user.username,
            "public_id": user.public_id,   # BizID — client mirrors this to the local account
            "business_name": user.business_name,
            "role": user.role,
            "counter_prefix": user.counter_prefix,   # POS counter series for this login (§9.3a)
            "db_mode": _DB_MODE,   # 'local' | 'cloud' — tells frontend which backend this account lives on
            # The Pro trial this signup started, or None (none given). The desktop
            # app sets up "Local + Cloud" only when it got one (Register.jsx).
            "trial": ({"days": _trial_days(), "expires_at": trial["expires_at"]} if trial else None),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"[AUTH] Error during signup for username '{req.username}': {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server signup error")


# ---------------------------------------------------------------------------
# SSO & HANDOFF TICKETS
# ---------------------------------------------------------------------------

class HandoffRequest(BaseModel):
    purpose: Literal["field_team", "ai_dashboard", "admin_console"]


@router.post("/handoff-ticket")
def handoff_ticket(body: Optional[HandoffRequest] = Body(None), current_user: dict = Depends(require_owner)):
    purpose = body.purpose if body else None
    ttl = 30 if purpose is None else 60
    if purpose == "field_team":
        try:
            ttl = max(1, min(120, int(os.getenv("HANDOFF_TTL_FIELD_TEAM", "90"))))
        except ValueError:
            ttl = 90
    claims = dict(current_user)
    if purpose == "ai_dashboard" and current_user.get("sid"):
        claims["psid"] = current_user["sid"]
    return {"ticket": create_sse_ticket(claims, expires_in_seconds=ttl, aud=purpose), "expires_in": ttl}


class RedeemTicketRequest(BaseModel):
    ticket: str


@router.post("/redeem-ticket")
def redeem_ticket(req: RedeemTicketRequest, request: Request, db: Session = Depends(get_db)):
    """
    (Phase C) Exchange a valid SSO ticket for a full, fresh JWT session.
    """
    logger.info("[AUTH] Attempting to redeem SSO handoff ticket...")
    try:
        ip = request.client.host if request.client else "unknown"
        rl = check_ip_rate_limit(ip)
        if not rl["allowed"]:
            raise HTTPException(status_code=429, detail=rl["reason"])

        # Direct redeem — bypasses FastAPI DI which would be a no-op here.
        # get_active_user_or_ticket uses Query(None) params; calling it directly
        # passes ticket=None, falls through to JWT auth, always raises 401.
        # Stateless verify (BUG-4): survives server restarts and >1 worker.
        check = verify_ticket(req.ticket, audiences={None, "ai_dashboard", "admin_console"})
        current_user = check.claims
        if current_user is None:
            details = {"expired": "Ticket expired. Open the app again from Billing.", "already_used": "Ticket already used. Open the app again from Billing.", "bad_signature": "Ticket signing configuration does not match.", "wrong_audience": "Ticket is intended for another app."}
            raise HTTPException(status_code=401, detail=details.get(check.reason, "Invalid or expired ticket"))
        _validate_token_version(current_user)
        logger.info("[AUTH] SSO ticket verified for user '%s'", current_user.get("username"))

        
        user_row = db.query(User).filter(User.username == current_user.get("username")).first()
        if not user_row:
            raise HTTPException(status_code=401, detail="User no longer exists")

        business_id = user_row.parent_business_id or user_row.id
        business_name = user_row.business_name
        owner_public_id = user_row.public_id
        if user_row.parent_business_id:
            owner = db.query(User).filter(User.id == user_row.parent_business_id).first()
            if owner:
                business_name = owner.business_name
                owner_public_id = owner.public_id

        token = create_access_token(_session_claims(user_row, sid=uuid4().hex, psid=current_user.get("psid"), owner=owner if user_row.parent_business_id else None))

        logger.info(f"[AUTH] Ticket redeemed successfully for user '{user_row.username}'. Issued new session.")
        return {
            "token": token,
            "id": business_id,
            "user_id": user_row.id,
            "username": user_row.username,
            "public_id": owner_public_id,
            "business_name": business_name,
            "role": user_row.role,
            "counter_prefix": user_row.counter_prefix,
            "db_mode": _DB_MODE,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Error redeeming ticket: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/auth/refresh")
def refresh_session(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Sliding-session refresh (REVIEW_1 GAP-1): exchange a valid, unexpired
    token for a fresh one. Claims are RE-READ from the DB — a role change,
    plan change, or token_version bump since login is reflected (a revoked
    token never reaches this handler; get_active_user rejects it first).
    This is what lets ACCESS_TOKEN_TTL_MINUTES drop below 24h without
    logging users out mid-shift."""
    try:
        uid = current_user.get("user_id") or current_user.get("id")
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            raise session_rejected("Account no longer exists")

        business_id = user.parent_business_id or user.id
        business_name = user.business_name
        owner_public_id = user.public_id
        if user.parent_business_id:
            owner = db.query(User).filter(User.id == user.parent_business_id).first()
            if owner:
                business_name = owner.business_name
                owner_public_id = owner.public_id

        token = create_access_token(_session_claims(user, sid=current_user.get("sid") or uuid4().hex, psid=current_user.get("psid"), owner=owner if user.parent_business_id else None))
        logger.info(f"[AUTH] Session refreshed for '{user.username}' (business={business_id}).")
        return {
            "token": token,
            "id": business_id,
            "user_id": user.id,
            "username": user.username,
            "public_id": owner_public_id,
            "business_name": business_name,
            "role": user.role,
            "counter_prefix": user.counter_prefix,
            "db_mode": _DB_MODE,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[AUTH] Error refreshing session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/auth/logout")
def logout_session(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Revoke dashboard descendants without ending the owner's other devices."""
    from database.models import RevokedSession
    from datetime import datetime, timedelta
    sid = current_user.get("sid")
    if sid and db.get(RevokedSession, sid) is None:
        # Descendant refreshes can outlive the original JWT; retain the parent
        # tombstone for the maximum session age beyond logout.
        from services.auth import ACCESS_TOKEN_EXPIRE_MINUTES
        expires = datetime.utcfromtimestamp(current_user.get("exp", time.time())) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        db.add(RevokedSession(sid=sid, expires_at=expires))
        try:
            db.commit()
        except IntegrityError:
            # Two tabs can sign out the same parent concurrently.
            db.rollback()
            if db.get(RevokedSession, sid) is None:
                raise HTTPException(status_code=503, detail="Sign-out could not be confirmed. Please retry.")
        except Exception:
            db.rollback()
            raise HTTPException(status_code=503, detail="Sign-out could not be confirmed. Please retry.")
    return {"status": "ok"}


class ProfileUpdateRequest(BaseModel):
    business_name: Optional[str] = None
    gstin: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    state_code: Optional[str] = None
    pan: Optional[str] = None
    logo: Optional[str] = None
    counter_prefix: Optional[str] = None   # owner sets their OWN POS counter series (§9.3a)
    upi_vpa: Optional[str] = None          # editable UPI handle for POS QR + invoices


@router.get("/profile")
def get_profile(current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == current_user.get("username")).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found", headers=SESSION_REJECTION_HEADERS)
    return {
        "id": user.id,
        "username": user.username,
        "business_name": user.business_name,
        "role": user.role,
        "public_id": user.public_id,
        "gstin": user.gstin,
        "phone": user.phone,
        "email": user.email,
        "address": user.address,
        "state_code": user.state_code,
        "pan": user.pan,
        "logo": user.logo,
        "counter_prefix": user.counter_prefix,
        # Premium = active paid plan (admin grant) OR the legacy override column.
        # Staff inherit the owner's plan via _subscription_view's holder resolve.
        "is_premium": _is_premium(user, db),
        "upi_vpa": getattr(user, "upi_vpa", None),
    }


@router.put("/profile")
def update_profile(req: ProfileUpdateRequest, current_user: dict = Depends(require_business_owner), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == current_user.get("username")).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found", headers=SESSION_REJECTION_HEADERS)
    
    if req.business_name is not None:
        user.business_name = req.business_name
    if req.gstin is not None:
        user.gstin = req.gstin
    if req.phone is not None:
        user.phone = req.phone
    if req.email is not None:
        user.email = req.email
    if req.address is not None:
        user.address = req.address
    if req.state_code is not None:
        user.state_code = req.state_code
    if req.pan is not None:
        user.pan = req.pan
    if req.logo is not None:
        user.logo = req.logo
    if req.counter_prefix is not None:
        import re
        token = re.sub(r"[^A-Za-z0-9_]", "", req.counter_prefix.strip()).rstrip("-")[:8]
        user.counter_prefix = token or None
    if req.upi_vpa is not None:
        user.upi_vpa = (req.upi_vpa.strip() or None)

    db.flush()

    # Immediately push profile changes to the cloud
    from services.immediate_sync import push_profile_to_cloud
    push_profile_to_cloud(user.id, {
        "business_name": req.business_name,
        "gstin": req.gstin,
        "phone": req.phone,
        "email": req.email,
        "address": req.address,
        "state_code": req.state_code,
        "pan": req.pan,
        "logo": req.logo,
        "upi_vpa": req.upi_vpa,
    }, db=db)
    db.commit()
    db.refresh(user)
    from services.control_outbox import trigger_control_flush
    trigger_control_flush(user.id)
    
    return {
        "id": user.id,
        "username": user.username,
        "business_name": user.business_name,
        "role": user.role,
        "public_id": user.public_id,
        "gstin": user.gstin,
        "phone": user.phone,
        "email": user.email,
        "address": user.address,
        "state_code": user.state_code,
        "pan": user.pan,
        "logo": user.logo,
        "counter_prefix": user.counter_prefix,
        # Premium = active paid plan (admin grant) OR the legacy override column.
        # Staff inherit the owner's plan via _subscription_view's holder resolve.
        "is_premium": _is_premium(user, db),
        "upi_vpa": getattr(user, "upi_vpa", None),
    }


# ---------------------------------------------------------------------------
# APP SETTINGS — stored as JSON on the User record (own naming schema)
# ---------------------------------------------------------------------------

import json

# Canonical default settings — own naming, no competitor prefixes
_DEFAULT_SETTINGS = {
    # ── General ──────────────────────────────────────────────────────────────
    "general": {
        "passcode_lock": False,
        "lock_timeout_minutes": 60,      # 0=never, 30, 60, 120
        "privacy_mode": False,           # hides dashboard revenue figures
        "auto_backup": False,
        "backup_reminder_days": 7,
        "date_format": "DD/MM/YYYY",     # 0=DD/MM/YYYY, 1=MM/DD/YYYY, 2=YYYY-MM-DD
        "quantity_decimal_places": 2,
        "amount_decimal_places": 2,
        "app_zoom": 100,                 # UI scale percentage: 80-130
        # Offer "Ask AI" in the search palette (Pro only; the server gate on
        # /ask/stream is what actually enforces that). Defaults ON so nothing
        # changes for anyone who never opens Settings, but it is switchable
        # because the row's usefulness depends on how the owner searches: the
        # local matchers only handle prefix-style typing, so a natural-language
        # query finds nothing locally and falls through to the assistant.
        "ai_search_enabled": True,
        "hosting_mode": "cloud" if "postgres" in DATABASE_URL or "postgresql" in DATABASE_URL else "local",         # local | hybrid | cloud
        "realtime_sync_global": True,
        "realtime_sync_sales": True,
        "realtime_sync_stock": True,
        "realtime_sync_parties": True,
        "realtime_sync_purchases": True,
    },
    # ── Transactions ─────────────────────────────────────────────────────────
    "transactions": {
        "tax_invoice_enabled": False,
        "discount_enabled": True,
        "discount_in_amount": False,       # False = %, True = ₹
        "payment_reminder_enabled": True,
        "payment_reminder_days": 1,
        "estimate_enabled": True,          # Quotes / Estimates
        "proforma_invoice_enabled": True,
        "delivery_challan_enabled": True,
        "sale_order_enabled": True,
        "purchase_order_enabled": True,
        "prevent_negative_stock": False,
        "round_off_enabled": True,
        "round_off_type": "nearest",       # nearest | ceil | floor
        "payment_terms_enabled": False,
        "eway_bill_enabled": False,
        "composite_scheme": False,
        "pos_show_sku": True,
        "pos_show_unit": True,
        "pos_show_discount": True,
        "pos_show_tax": True,
        "pos_show_hsn": False,
        "pos_show_mrp": False,
        "pos_show_batch": True,
        "pos_show_serial": False,
    },
    # ── Items / Inventory ─────────────────────────────────────────────────────
    "inventory": {
        "stock_tracking": True,
        "item_units_enabled": True,
        "item_categories_enabled": True,
        "batch_tracking": False,
        "expiry_date_tracking": False,
        "manufacturing_date_tracking": False,
        "serial_tracking": False,
        "mrp_enabled": True,
        "wholesale_price": False,
        "barcode_scanning": True,
        "auto_update_sale_price": False,
    },
    # ── Print / PDF ───────────────────────────────────────────────────────────
    "print": {
        "theme_color": "#C2714F",          # terracotta default
        "page_size": "A4",                 # A4 | A5 | Letter
        "print_orientation": "portrait",   # portrait | landscape
        "invoice_theme": "classic",        # classic | modern | minimal
        "print_logo": True,
        "print_company_name": True,
        "print_company_address": True,
        "print_company_phone": True,
        "print_company_email": True,
        "print_gstin": True,
        "print_terms_conditions": True,
        "terms_conditions_text": "Thank you for your business!",
        "print_signature": True,
        "signature_label": "Authorised Signatory",
        "customer_signature": True,
        "customer_signature_label": "Customer Signature",
        "print_tax_breakdown": True,
        "print_item_sno": True,
        "print_item_hsn": True,
        "print_item_discount": True,
        "print_item_tax": True,
        "print_amount_in_words": False,
        "extra_space_enabled": False,
        "text_size": "medium",             # small | medium | large
        "copy_count": 1,
        "thermal_printer_mode": False,
        "thermal_page_size": "3inch",      # 3inch (80mm) | 2inch (58mm)
        "thermal_theme": "theme_standard", # theme_standard | theme_compact
        # Invoice-template system (plan Phase 1): the business's default template
        # for the invoice viewer. classic | modern | thermal. Per-user last-used
        # lives client-side; this is the business default.
        "invoice_template": "classic",
    },
    # ── Transaction Names (custom labels) ────────────────────────────────────
    "labels": {
        "sale": "Sales Invoice",
        "purchase": "Purchase Bill",
        "estimate": "Estimate",
        "proforma": "Proforma Invoice",
        "delivery_challan": "Delivery Challan",
        "sale_return": "Credit Note",
        "purchase_return": "Debit Note",
        "payment_in": "Payment Receipt",
        "payment_out": "Payment Out",
        "expense": "Expense",
        "income": "Other Income",
        "sale_order": "Sale Order",
        "purchase_order": "Purchase Order",
    }
}


class SettingsUpdateRequest(BaseModel):
    general: Optional[dict] = None
    transactions: Optional[dict] = None
    inventory: Optional[dict] = None
    print: Optional[dict] = None
    labels: Optional[dict] = None


def _get_user_settings(user: User, db: Session = None) -> dict:
    """Return merged settings: defaults overridden by what's saved on the user."""
    import copy
    logger.debug(f"[SETTINGS] Merging settings for user '{user.username}' (ID {user.id})")
    base = copy.deepcopy(_DEFAULT_SETTINGS)

    # 1. Start with the owner settings if this is a staff user
    if user.parent_business_id and db:
        owner = db.query(User).filter(User.id == user.parent_business_id).first()
        if owner and owner.settings:
            try:
                owner_saved = json.loads(owner.settings)
                for section, values in owner_saved.items():
                    if section in base and isinstance(values, dict):
                        base[section].update(values)
                logger.debug(f"[SETTINGS] Merged settings from owner '{owner.username}' as base config")
            except Exception as e:
                logger.warning(f"[SETTINGS] Failed to parse owner settings: {str(e)}")

    # 2. Merge user's own settings on top (covers cashier-specific preferences)
    if user.settings:
        try:
            saved = json.loads(user.settings)
            for section, values in saved.items():
                if section in base and isinstance(values, dict):
                    base[section].update(values)
            logger.debug(f"[SETTINGS] Settings successfully merged for user '{user.username}'")
        except Exception as e:
            logger.warning(f"[SETTINGS] Failed to parse settings for user '{user.username}': {user.settings}, error: {str(e)}", exc_info=True)
    else:
        logger.debug(f"[SETTINGS] User '{user.username}' has no custom settings, using base/defaults")
    return base


def _is_premium(user: User, db: Session = None) -> bool:
    """Single source of truth for the premium flag exposed on /profile.

    True when EITHER (a) the account has an active paid plan — the admin-managed
    subscription, staff inheriting the owner's plan — OR (b) the legacy
    `is_premium` override column is set (a direct manual/admin flip). The OR keeps
    both paths working: the subscription system drives it in production, while the
    column remains a valid escape hatch and preserves backward compatibility.
    """
    try:
        if _subscription_view(user, db).get("plan") != "free":
            return True
    except Exception:
        pass
    return bool(getattr(user, "is_premium", False))


def _sync_subscription_from_cloud(user: User, db: Session, force: bool = False):
    if _DB_MODE != "local" or not db:
        return

    # NOTE (bugfix 2026-07-16): this used to bail unless the LOCAL record's
    # `general.hosting_mode == "hybrid"`. But a fresh-device mirror created by
    # the login fallback keeps the default 'local' (only the signup path PUTs
    # 'hybrid'), so the Pro plan never propagated to the desktop even though a
    # cloud sync token was provisioned at login. A stored cloud token is the
    # real "this business is cloud-linked" signal — pure-local accounts have no
    # token and return below without any network call.

    # ── Cooldown guard: skip cloud call if checked recently ──────────────────
    business_id = user.parent_business_id or user.id
    now = time.time()
    if not force and now < _sub_sync_next.get(business_id, 0):
        logger.debug(f"[SETTINGS] Subscription cloud sync skipped (cooldown) for business {business_id}")
        return
    # ─────────────────────────────────────────────────────────────────────────
    from services.sync_worker import CLOUD_URL, _get_cloud_token
    import httpx

    token = _get_cloud_token(business_id)
    if not token:
        # No cloud identity yet — nothing was asked and nothing was spent, so
        # do NOT arm the cooldown. The cooldown used to be armed above this
        # line, before the token lookup and before the request, which made a
        # check that never happened buy 30 minutes of silence. At app start
        # this path routinely wins the race against the login's cloud-token
        # provisioning, so an admin's Pro grant stayed invisible on the desktop
        # for half an hour, with no way to ask again.
        return

    # A request is about to leave: arm the SHORT window so parallel callers
    # don't stampede the cloud, and extend it only once the cloud answers. A
    # timeout or a 5xx must not buy the full cooldown either.
    _sub_sync_next[business_id] = now + _SUB_SYNC_RETRY_SECS

    try:
        # Fetch latest settings/subscription from the cloud
        resp = httpx.get(
            f"{CLOUD_URL}/settings",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0
        )
        if resp.status_code == 200:
            cloud_settings = resp.json()
            cloud_sub = cloud_settings.get("subscription")
            # The cloud answered, so a cooldown is earned — but its length
            # depends on the ANSWER, not on the fact that we asked. Free keeps
            # checking; Pro settles down. Armed from the cloud's reply rather
            # than the stored plan so an upgrade takes effect on this very call.
            _sub_sync_next[business_id] = time.time() + (
                _SUB_SYNC_COOLDOWN_SECS
                if (cloud_sub or {}).get("plan") == "pro"
                else _SUB_SYNC_FREE_COOLDOWN_SECS
            )
            if cloud_sub:
                # Update local DB settings with the cloud subscription info
                plan_holder = user
                if user.parent_business_id:
                    owner = db.query(User).filter(User.id == user.parent_business_id).first()
                    if owner:
                        plan_holder = owner
 
                local_settings = json.loads(plan_holder.settings) if plan_holder.settings else {}
                local_settings["subscription"] = cloud_sub
                plan_holder.settings = json.dumps(local_settings)
                db.add(plan_holder)
                db.commit()
                logger.info(f"[SETTINGS] Automatically synced subscription from cloud for business {business_id}: {cloud_sub}")
    except Exception as e:
        logger.debug(f"[SETTINGS] Background cloud subscription check skipped/failed: {e}")


def _subscription_view(user: User, db: Session = None, force: bool = False) -> dict:
    """Read-only subscription info for the client (Phase B.5). Staff inherit the
    owner's plan. Admin-managed only — PUT /settings can never modify this."""
    if db:
        try:
            _sync_subscription_from_cloud(user, db, force=force)
        except Exception:
            pass
    from services.admin_service import effective_plan, expiry_moment, _settings_dict
    from services.auth import subscription_enforced
    from services.dates import utc_now
    plan_holder = user
    if user.parent_business_id and db:
        owner = db.query(User).filter(User.id == user.parent_business_id).first()
        if owner:
            plan_holder = owner
    sub = _settings_dict(plan_holder).get("subscription") or {}
    status = sub.get("status", "none")
    gated = (user.role or "").lower() != "admin" and effective_plan(plan_holder) != "pro"
    ends = expiry_moment(sub.get("expires_at"))
    return {
        "plan":       effective_plan(plan_holder),
        "status":     status,
        "expires_at": sub.get("expires_at"),
        # The exact moment access ends (a date runs to the end of that day) and
        # the whole days left before it, so every screen counts down alike.
        # 0 = it ends within the next 24 hours, or already has.
        "ends_at":    (ends.isoformat() + "Z") if ends else None,
        "days_remaining": max(0, int((ends - utc_now()).total_seconds() // 86400)) if ends else None,
        # Still true after the trial lapses (plan "free"), so the client can say
        # "your trial ended" rather than treat it like any free account.
        "trial":      status == "trial",
        # Whether the backend actually gates Pro features right now — the client
        # shows PRO badges / blocks only when this is true.
        "enforced":   subscription_enforced(),
        "gates": {"ai": gated, "field_team": gated, "hybrid_sync": gated and subscription_enforced(), "web_preview": gated},
    }


@router.get("/settings")
def get_settings(force: bool = False, current_user: dict = Depends(get_active_user), db: Session = Depends(get_db)):
    """Return current user's app settings (merged with defaults) + read-only
    subscription info (frontend flips AI/PRO gating off the real plan)."""
    logger.info(f"[SETTINGS] GET /settings requested by user '{current_user.get('username')}' (ID {current_user.get('id')}) force={force}")
    user = db.query(User).filter(User.username == current_user.get("username")).first()
    if not user:
        logger.warning(f"[SETTINGS] User with ID {current_user.get('id')} not found")
        raise HTTPException(status_code=404, detail="User not found", headers=SESSION_REJECTION_HEADERS)
    merged = _get_user_settings(user, db)
    merged["subscription"] = _subscription_view(user, db, force=force)
    return merged


@router.put("/settings")
def update_settings(
    req: SettingsUpdateRequest,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    """Merge-update the user's app settings and persist."""
    logger.info(f"[SETTINGS] PUT /settings requested by user '{current_user.get('username')}' (ID {current_user.get('id')})")

    user = db.query(User).filter(User.username == current_user.get("username")).first()
    if not user:
        logger.warning(f"[SETTINGS] User with ID {current_user.get('id')} not found during update")
        raise HTTPException(status_code=404, detail="User not found", headers=SESSION_REJECTION_HEADERS)

    current = _get_user_settings(user, db)

    # Restrict cashiers from modifying non-general settings
    is_cashier = (current_user.get("role") or "").lower() == "cashier"
    if is_cashier:
        # Ignore sections if they are identical to what's already saved
        if req.transactions and req.transactions == current.get("transactions", {}): req.transactions = None
        if req.inventory and req.inventory == current.get("inventory", {}): req.inventory = None
        if req.print and req.print == current.get("print", {}): req.print = None
        if req.labels and req.labels == current.get("labels", {}): req.labels = None

        if req.transactions is not None or req.inventory is not None or req.print is not None or req.labels is not None:
            logger.warning(f"[SETTINGS] Cashier '{current_user.get('username')}' blocked from modifying global settings")
            raise HTTPException(status_code=403, detail="Permission denied: cashier restricted from modifying global settings")
        if req.general is not None:
            blocked_keys = ("realtime_sync_global", "hosting_mode")
            if any(k in req.general and req.general[k] != current.get("general", {}).get(k) for k in blocked_keys):
                logger.warning(f"[SETTINGS] Cashier '{current_user.get('username')}' blocked from modifying global general configurations")
                raise HTTPException(status_code=403, detail="Permission denied: cashier restricted from modifying global configurations")

    # Pro-gate hybrid sync activation (Phase B.5) — no-op unless SUBSCRIPTION_ENFORCED=1.
    from services.auth import subscription_enforced
    if (subscription_enforced()
            and req.general
            and req.general.get("hosting_mode") == "hybrid"
            and current.get("general", {}).get("hosting_mode") != "hybrid"
            and (current_user.get("role") or "").lower() != "admin"):
        if _subscription_view(user, db).get("plan") != "pro":
            logger.info(f"[SETTINGS] plan gate: '{user.username}' blocked from enabling hybrid sync (free plan)")
            raise HTTPException(status_code=402, detail="Hybrid sync requires the Pro plan. Contact your provider to upgrade.")

    # ── The cloud is a REPLICA of hosting_mode, never its author ──────────────
    #
    # `general.hosting_mode` describes how the OWNER'S LOCAL INSTALL is hosted.
    # A cloud (Postgres) instance cannot observe that — it only ever sees a
    # browser tab, which by definition has no local backend and therefore always
    # derives 'cloud' for itself.
    #
    # `users` is in `_SYNC_TABLES`, so this field is LWW-synced to every device.
    # That made the following a real, silent outage:
    #
    #   owner opens the web dashboard
    #     -> web session derives 'cloud' (true of that tab)
    #     -> PUT /settings writes 'cloud' onto the cloud users row (now newest)
    #     -> desktop pulls, its 'hybrid' is overwritten
    #     -> sync_worker.run_hybrid_sync: `if hosting_mode != "hybrid": continue`
    #     -> the desktop stops syncing and stops queueing rows to the outbox,
    #        with no error raised anywhere
    #     -> the desktop's next Settings load re-derives 'hybrid' and writes it
    #        back, so the two devices flip the field on every page load
    #
    # The client-side guard in `shouldPersistMode` stops a compliant frontend
    # from sending this. THIS is the guard that holds when the client is an old
    # build, a different frontend, or a direct API call — which is exactly the
    # population that will still be running the version that caused it.
    #
    # UPGRADES to 'hybrid' are still accepted: `_provisionCloudSyncToken` PUTs
    # 'hybrid' to the cloud on purpose, from a local install that knows it is
    # hybrid, so the Admin Console reports the truth. Only the DOWNGRADE
    # direction — the one that switches a sync worker off — is refused.
    if req.general is not None and "hosting_mode" in req.general:
        _is_cloud_instance = (_DB_MODE == "cloud")
        _stored_mode = (current.get("general") or {}).get("hosting_mode")
        _incoming_mode = req.general.get("hosting_mode")
        if (_is_cloud_instance
                and _stored_mode == "hybrid"
                and _incoming_mode != "hybrid"):
            logger.warning(
                "[SETTINGS] REFUSED hosting_mode downgrade 'hybrid' -> %r for '%s' on the "
                "cloud instance. hosting_mode is authored by the local install; accepting "
                "this would sync down and stop that install's sync worker. Keeping 'hybrid'.",
                _incoming_mode, user.username,
            )
            req.general = {k: v for k, v in req.general.items() if k != "hosting_mode"}

    # Merge each provided section
    for section in ("general", "transactions", "inventory", "print", "labels"):
        patch = getattr(req, section)
        if patch is not None:
            logger.debug(f"[SETTINGS] Patching section '{section}' for user '{user.username}': {patch}")
            current[section].update(patch)

    # Preserve the server-authoritative reserved keys across saves and strip any
    # client-supplied values (Phase B.5 guard + §4.1 2FA: `subscription` and
    # `totp` are server-managed; the SettingsUpdateRequest schema already
    # rejects unknown sections and the merged view never includes them, so
    # re-attach from what's on disk).
    current.pop("subscription", None)
    current.pop("totp", None)
    try:
        prev = json.loads(user.settings) if user.settings else {}
        if isinstance(prev, dict):
            if "subscription" in prev:
                current["subscription"] = prev["subscription"]
            if "totp" in prev:
                current["totp"] = prev["totp"]
    except Exception:
        pass

    user.settings = json.dumps(current)
    db.commit()
    logger.info(f"[SETTINGS] Settings successfully updated and committed for user '{user.username}'")
    logger.debug(f"[SETTINGS] New settings structure: {current}")
    resp = dict(current)
    # Never echo the TOTP secret back to any client — it lives server-side only.
    resp.pop("totp", None)
    resp["subscription"] = _subscription_view(user, db)
    return resp


# ── Username Availability ───────────────────────────────────────────────────

@router.get("/api/auth/check-username")
def check_username(username: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    """Real-time availability check for merchant's desired store username."""
    from database.security import username_exists
    uname = (username or "").strip()
    if len(uname) < 3:
        return {"available": False, "username": uname, "reason": "too_short"}
    taken = username_exists(db, uname)
    return {"available": not taken, "username": uname}


# ── Password Reset via OTP (Brevo Mail) ─────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    identifier: str  # username, phone, or email


class VerifyAndResetPasswordRequest(BaseModel):
    identifier: str
    otp: str
    new_password: str


@router.post("/api/auth/forgot-password/request-otp")
def forgot_password_request_otp(req: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Initiates an OTP-based password reset. Generates a secure 6-digit code,
    persists its hash, and dispatches via Brevo email (and server log for SMS)."""
    ip = request.client.host if request.client else "unknown"
    rl = check_ip_rate_limit(ip)
    if not rl["allowed"]:
        raise HTTPException(status_code=429, detail=rl["reason"])

    ident = (req.identifier or "").strip()
    if not ident:
        raise HTTPException(status_code=400, detail="Identifier (username, email, or phone) is required.")

    from database.security import find_user_by_identifier
    from database.models import PasswordResetOTP
    from services.auth import hash_password
    from services.brevo_service import send_otp_email
    import secrets
    from datetime import datetime, timezone, timedelta

    user = find_user_by_identifier(db, ident)
    if not user or (user.role or "").lower() in {"deleted", "retired"}:
        # Return generic success to prevent account enumeration
        return {
            "status": "ok",
            "message": "If an account matches, a 6-digit verification code has been sent.",
            "destination": "registered email/phone",
        }

    otp_code = f"{secrets.randbelow(900000) + 100000:06d}"
    otp_hash = hash_password(otp_code)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=10)

    # Invalidate existing unused OTPs for this user
    db.query(PasswordResetOTP).filter(
        PasswordResetOTP.user_id == user.id,
        PasswordResetOTP.used.is_(False)
    ).update({"used": True})

    otp_row = PasswordResetOTP(
        user_id=user.id,
        identifier=ident,
        otp_hash=otp_hash,
        purpose="password_reset",
        expires_at=expires,
        attempts=0,
        used=False,
    )
    db.add(otp_row)
    db.commit()

    masked_email = ""
    if user.email and "@" in user.email:
        parts = user.email.split("@")
        masked_email = f"{parts[0][:2]}***@{parts[1]}"

    masked_phone = ""
    if user.phone and len(user.phone) >= 6:
        masked_phone = f"***{user.phone[-4:]}"

    destination_hint = masked_email or masked_phone or "your registered account"

    if user.email:
        send_otp_email(user.email, user.business_name or user.username, otp_code, user.username)
    else:
        logger.info("[AUTH] User '%s' has no email; OTP %s logged for phone %s", user.username, otp_code, user.phone)

    logger.info("[AUTH] Generated password reset OTP for '%s' (User ID %s)", user.username, user.id)
    return {
        "status": "ok",
        "message": f"Verification code sent to {destination_hint}.",
        "destination": destination_hint,
        "has_email": bool(user.email),
        "username_hint": user.username[:2] + "***" if len(user.username) > 2 else "***",
    }


@router.post("/api/auth/forgot-password/verify-and-reset")
def forgot_password_verify_and_reset(req: VerifyAndResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    """Verifies the 6-digit OTP, updates the password, bumps token_version to revoke
    all stale device sessions, and returns an authenticated JWT session."""
    ip = request.client.host if request.client else "unknown"
    rl = check_ip_rate_limit(ip)
    if not rl["allowed"]:
        raise HTTPException(status_code=429, detail=rl["reason"])

    ident = (req.identifier or "").strip()
    from database.security import find_user_by_identifier
    from database.models import PasswordResetOTP
    from services.auth import verify_password, hash_password, create_access_token, bump_token_version
    from datetime import datetime, timezone

    user = find_user_by_identifier(db, ident)
    if not user or (user.role or "").lower() in {"deleted", "retired"}:
        raise HTTPException(status_code=400, detail="Invalid verification request.")

    now = datetime.now(timezone.utc)
    otp_record = (
        db.query(PasswordResetOTP)
        .filter(PasswordResetOTP.user_id == user.id, PasswordResetOTP.used.is_(False))
        .order_by(PasswordResetOTP.id.desc())
        .first()
    )

    if not otp_record or otp_record.expires_at.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")

    if otp_record.attempts >= 3:
        otp_record.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="Too many invalid attempts. Please request a new code.")

    if not verify_password(req.otp.strip(), otp_record.otp_hash):
        otp_record.attempts += 1
        db.commit()
        remaining = 3 - otp_record.attempts
        raise HTTPException(status_code=400, detail=f"Invalid verification code. {remaining} attempt(s) remaining.")

    # Validate password rules
    password = req.new_password
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")
    if not any(c.isupper() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter.")
    if not any(c.islower() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter.")
    if not any(c.isdigit() for c in password):
        raise HTTPException(status_code=400, detail="Password must contain at least one number.")

    user.password = hash_password(password)
    bump_token_version(db, user)
    otp_record.used = True
    db.commit()
    db.refresh(user)

    logger.info("[AUTH] Password reset succeeded for '%s' (User ID %s)", user.username, user.id)

    business_id = user.parent_business_id or user.id
    token = create_access_token(_session_claims(user, sid=uuid4().hex))
    return {
        "status": "ok",
        "message": "Password updated successfully.",
        "token": token,
        "id": business_id,
        "user_id": user.id,
        "username": user.username,
        "public_id": user.public_id,
        "business_name": user.business_name,
        "role": user.role,
        "counter_prefix": user.counter_prefix,
        "db_mode": _DB_MODE,
    }


# ── Google Sign-In & Onboarding ──────────────────────────────────────────────

def _verify_google_credential(credential: str) -> dict:
    """Verifies a Google OAuth ID token with Google's public tokeninfo endpoint."""
    if not credential:
        raise HTTPException(status_code=400, detail="Missing Google credential token.")
    import httpx
    try:
        r = httpx.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": credential}, timeout=10.0)
    except Exception as exc:
        logger.error("[GOOGLE_AUTH] Token verification network error: %s", exc)
        raise HTTPException(status_code=503, detail="Unable to verify Google credentials. Please try again.")

    if r.status_code != 200:
        logger.warning("[GOOGLE_AUTH] Invalid Google token (HTTP %s): %s", r.status_code, r.text)
        raise HTTPException(status_code=401, detail="Invalid Google authentication token.")

    data = r.json()
    email_verified = data.get("email_verified")
    if email_verified not in (True, "true", "True", 1, "1"):
        raise HTTPException(status_code=400, detail="Your Google email is not verified.")

    return {
        "sub": data.get("sub"),
        "email": data.get("email", "").lower().strip(),
        "name": data.get("name", "").strip(),
        "picture": data.get("picture", ""),
    }


class GoogleVerifyRequest(BaseModel):
    credential: str


class GoogleRegisterRequest(BaseModel):
    credential: str
    username: str
    business_name: str
    category: Optional[str] = "general"
    phone: str


@router.post("/api/auth/google/verify")
def google_verify(req: GoogleVerifyRequest, request: Request, db: Session = Depends(get_db)):
    """Verifies a Google ID token. If user exists, signs them in immediately;
    if brand new, returns prefilled onboarding data for store setup."""
    ip = request.client.host if request.client else "unknown"
    rl = check_ip_rate_limit(ip)
    if not rl["allowed"]:
        raise HTTPException(status_code=429, detail=rl["reason"])

    import re
    from sqlalchemy import or_, func

    google_data = _verify_google_credential(req.credential)
    sub = google_data["sub"]
    email = google_data["email"]

    # Check if this Google user or verified email is already registered as an owner
    user = (
        db.query(User)
        .filter(
            or_(User.google_id == sub, func.lower(User.email) == email),
            User.parent_business_id.is_(None),
        )
        .first()
    )

    if user and (user.role or "").lower() not in {"deleted", "retired"}:
        if not user.google_id:
            user.google_id = sub
            db.commit()

        business_id = user.parent_business_id or user.id
        token = create_access_token(_session_claims(user, sid=uuid4().hex))
        logger.info("[GOOGLE_AUTH] Existing user '%s' logged in via Google.", user.username)
        return {
            "status": "ok",
            "action": "login",
            "token": token,
            "id": business_id,
            "user_id": user.id,
            "username": user.username,
            "public_id": user.public_id,
            "business_name": user.business_name,
            "role": user.role,
            "counter_prefix": user.counter_prefix,
            "db_mode": _DB_MODE,
        }

    # Brand new user: return onboarding metadata so they can choose their username
    raw_name = google_data["name"] or "Store"
    suggested_username = re.sub(r"[^a-zA-Z0-9_]", "", raw_name.lower().replace(" ", "_"))[:18]
    return {
        "status": "needs_onboarding",
        "email": email,
        "name": google_data["name"],
        "picture": google_data["picture"],
        "suggested_business_name": f"{raw_name}'s Store",
        "suggested_username": suggested_username,
    }


@router.post("/api/auth/google/register")
def google_register(req: GoogleRegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Registers a new store using Google credentials with the user's chosen username,
    mandatory phone, business name, and store category."""
    ip = request.client.host if request.client else "unknown"
    rl = check_ip_rate_limit(ip)
    if not rl["allowed"]:
        raise HTTPException(status_code=429, detail=rl["reason"])

    from database.security import username_exists, allocate_owner_id
    from core.connection.utils import generate_bizid
    from services.auth import hash_password, create_access_token
    from services.brevo_service import send_welcome_email, sync_contact_to_brevo

    google_data = _verify_google_credential(req.credential)
    sub = google_data["sub"]
    email = google_data["email"]

    # Validate user's chosen username
    uname = (req.username or "").strip()
    if len(uname) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters long.")
    if username_exists(db, uname):
        raise HTTPException(status_code=400, detail="This username is already taken. Please choose another.")

    # Validate mandatory phone
    try:
        phone = normalize_phone(req.phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    existing_phone = db.query(User).filter(User.phone == phone, User.parent_business_id.is_(None)).first()
    if existing_phone:
        raise HTTPException(status_code=400, detail="This mobile number is already registered to a business account.")

    # Allocate identity and mint BizID
    owner_pk = allocate_owner_id(db)
    bizid = generate_bizid(db)
    business_name = (req.business_name or "").strip() or f"{uname}'s Store"

    user = User(
        id=owner_pk,
        username=uname,
        password=hash_password(uuid4().hex),  # Random password; authenticates via Google
        business_name=business_name,
        role="enterprise",
        public_id=bizid,
        phone=phone,
        email=email,
        google_id=sub,
    )
    db.add(user)
    db.flush()

    # Provision 14-day Pro trial and default store settings
    _start_trial(user, phone, db)

    # Save selected store category in business_settings
    try:
        from database.models import BusinessSettings
        cat = (req.category or "general").strip()
        settings_row = db.query(BusinessSettings).filter(BusinessSettings.business_id == user.id).first()
        if not settings_row:
            settings_row = BusinessSettings(business_id=user.id, template_key=cat)
            db.add(settings_row)
        else:
            settings_row.template_key = cat
    except Exception as e:
        logger.warning("[GOOGLE_AUTH] Could not set business template category: %s", e)

    db.commit()
    db.refresh(user)

    logger.info("[GOOGLE_AUTH] New store registered via Google: '%s' (BizID %s, Phone %s)", uname, bizid, phone)

    # Asynchronously notify via Brevo
    try:
        send_welcome_email(email, business_name, uname, business_name)
        sync_contact_to_brevo(email, business_name, phone, plan="Trial")
    except Exception as exc:
        logger.warning("[BREVO] Failed to dispatch welcome/sync: %s", exc)

    token = create_access_token(_session_claims(user, sid=uuid4().hex))
    return {
        "status": "ok",
        "action": "registered",
        "token": token,
        "id": user.id,
        "user_id": user.id,
        "username": user.username,
        "public_id": user.public_id,
        "business_name": user.business_name,
        "role": user.role,
        "counter_prefix": user.counter_prefix,
        "db_mode": _DB_MODE,
    }


