"""
app/security.py — passwords, tokens, and who-is-calling.
========================================================
Two kinds of caller, two token types, ONE signing key that billing cannot use:

    owner  — a billing owner account (`users` row, parent_business_id IS NULL).
             Logs in with the SAME username/password as BizAssist Billing.
    staff  — a field worker (`ft_staff` row), created by the owner, who sets
             the password. Device policy enforced on every request.

Signing key = HMAC-SHA256(JWT_SECRET, "bizassist-task:v1"). Billing verifies
tokens with JWT_SECRET itself and without an audience, so a task token fails
there twice over (wrong key AND an `aud` claim PyJWT rejects when no audience is
expected). That matters: billing's role guard is a deny-list, so a field token
that billing accepted would be treated as an owner. Verified in
tests/test_auth.py::test_task_token_is_rejected_by_billing_style_decode.

The reverse direction is deliberate: a BILLING owner session can be exchanged
for a task owner token (`POST /auth/exchange`) — single sign-on from billing,
either as billing's 30-second hand-off ticket (what billing's sidebar link
sends) or as a billing owner token.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app import config
from app.billing_models import BillingUser
from app.db import get_db, set_rls_business, utc_now
from app.models import FieldSettings, FieldStaff

logger = logging.getLogger("bizassist.task.auth")

AUDIENCE = "bizassist-task"
ALGORITHM = "HS256"
_TASK_KEY = hmac.new(config.JWT_SECRET.encode(), b"bizassist-task:v1", hashlib.sha256).hexdigest()

# Billing roles that are NOT business owners. `admin` is the platform
# organiser's console account, not a business.
NON_OWNER_ROLES = {"cashier", "supply adder", "admin"}


# ── Passwords (bcrypt — identical to billing's services/auth.py) ─────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# A real hash to burn the same time when the account does not exist, so login
# timing does not reveal which staff names exist.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(12))


def burn_password_check(plain: str) -> None:
    verify_password(plain, _DUMMY_HASH)


def validate_password_policy(pw: str) -> None:
    """Billing's policy (routes/auth.py signup + core/api/staff.py)."""
    if (len(pw) < 8 or not any(c.isupper() for c in pw)
            or not any(c.islower() for c in pw) or not any(c.isdigit() for c in pw)):
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters with an upper-case letter, a lower-case letter and a number.",
        )


# ── Tokens ────────────────────────────────────────────────────────────────────

def _encode(claims: dict) -> str:
    now = utc_now()
    payload = {
        **claims,
        "aud": AUDIENCE,
        "iat": int(time.time()),
        "exp": now + timedelta(minutes=config.ACCESS_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, _TASK_KEY, algorithm=ALGORITHM)


def owner_token(user: BillingUser) -> str:
    return _encode({
        "typ": "owner",
        "bid": int(user.id),
        "uid": int(user.id),
        "public_id": user.public_id,
        "tv": int(user.token_version or 0),
    })


def staff_token(staff: FieldStaff, public_id: Optional[str]) -> str:
    return _encode({
        "typ": "staff",
        "bid": int(staff.business_id),
        "public_id": public_id,  # the business's BizID — for [BizId=…] log lines only
        "sid": int(staff.id),
        "ses": staff.active_session_id,
        "dev": staff.active_device_id,
        "tv": int(staff.token_version or 0),
    })


def bizid_from_authorization(header: Optional[str]) -> Optional[str]:
    """The caller's BizID for log lines. Not an auth check: no database, no
    session/device checks, never raises — routes still authenticate."""
    if not header or not header.startswith("Bearer "):
        return None
    try:
        claims = jwt.decode(header[7:], _TASK_KEY, algorithms=[ALGORITHM], audience=AUDIENCE)
    except jwt.InvalidTokenError:
        return None
    return claims.get("public_id")


def decode_task_token(token: str) -> dict:
    try:
        return jwt.decode(token, _TASK_KEY, algorithms=[ALGORITHM], audience=AUDIENCE)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired — please sign in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session — please sign in again")


def decode_billing_token(token: str) -> dict:
    """Verify a token minted by the billing backend (same JWT_SECRET, no aud)."""
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Billing session expired — sign in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Not a valid BizAssist session")


# ── Billing hand-off tickets (the "Field Team" link in billing's sidebar) ────
# Billing's POST /handoff-ticket mints `<exp>.<b64url json>.<hex sig>` with
# sig = HMAC-SHA256(JWT_SECRET, "sse|<b64>|<exp>"), valid 30 s, payload = the
# owner's session claims (billing services/auth.py create_sse_ticket). It is
# the same ticket billing's AI dashboard redeems. The secret is shared, so it is
# verified here — no call to the billing Space, which may be asleep. Single use
# is enforced in-process (this service runs ONE worker).

_TICKET_MAX_LIFETIME_S = 60
_USED_TICKETS: dict[str, int] = {}


def redeem_billing_ticket(ticket: str) -> dict:
    """Verify a billing hand-off ticket, spend it, and return its claims."""
    refused = HTTPException(status_code=401, detail="Sign-in link expired — open Field Team from BizAssist Billing again")
    try:
        exp_s, b64, sig = ticket.split(".", 2)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        raise refused
    now = int(time.time())
    # Billing mints for 30 s; a ticket valid far longer did not come from
    # /handoff-ticket.
    if now > exp or exp - now > _TICKET_MAX_LIFETIME_S:
        raise refused
    expected = hmac.new(config.JWT_SECRET.encode(), f"sse|{b64}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise refused
    for spent, spent_exp in list(_USED_TICKETS.items()):
        if spent_exp < now:
            del _USED_TICKETS[spent]
    if ticket in _USED_TICKETS:
        raise refused
    try:
        claims = json.loads(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)))
    except (ValueError, binascii.Error):
        raise refused
    if not isinstance(claims, dict):
        raise refused
    _USED_TICKETS[ticket] = exp
    return claims


# ── Login throttling (in-process; this service runs ONE worker) ─────────────

_ATTEMPTS: dict[str, list[float]] = {}
_WINDOW_S = 15 * 60
_MAX_FAILURES = 10


def check_login_throttle(key: str) -> None:
    now = time.time()
    hits = [t for t in _ATTEMPTS.get(key, []) if now - t < _WINDOW_S]
    _ATTEMPTS[key] = hits
    if len(hits) >= _MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in 15 minutes.")


def record_login_failure(key: str) -> None:
    _ATTEMPTS.setdefault(key, []).append(time.time())


def clear_login_failures(key: str) -> None:
    _ATTEMPTS.pop(key, None)


# ── Settings helper (used by auth and every router) ──────────────────────────

def get_settings(db: Session, business_id: int) -> FieldSettings:
    row = db.query(FieldSettings).filter(FieldSettings.business_id == business_id).first()
    if row is None:
        row = FieldSettings(business_id=business_id)
        db.add(row)
        db.flush()
    return row


# ── Request principal ────────────────────────────────────────────────────────

@dataclass
class Principal:
    kind: str  # "owner" | "staff"
    business_id: int
    owner_user_id: Optional[int] = None
    staff: Optional[FieldStaff] = None
    public_id: Optional[str] = None

    @property
    def actor(self) -> str:
        return f"owner:{self.owner_user_id}" if self.kind == "owner" else f"staff:{self.staff.id}"


def _bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in required")
    return authorization.split(" ", 1)[1].strip()


def current_principal(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Principal:
    claims = decode_task_token(_bearer(authorization))
    kind = claims.get("typ")
    try:
        bid = int(claims["bid"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid session — please sign in again")

    if kind == "owner":
        user = db.query(BillingUser).filter(BillingUser.id == int(claims.get("uid", -1))).first()
        if (user is None or user.parent_business_id is not None or int(user.id) != bid
                or (user.role or "").lower() in NON_OWNER_ROLES):
            raise HTTPException(status_code=401, detail="Account not found — please sign in again")
        # Billing's "force logout" bumps users.token_version — honour it here too.
        if int(claims.get("tv", 0)) != int(user.token_version or 0):
            raise HTTPException(status_code=401, detail="Session revoked — please sign in again")
        set_rls_business(db, bid)
        return Principal(kind="owner", business_id=bid, owner_user_id=int(user.id), public_id=user.public_id)

    if kind == "staff":
        staff = db.query(FieldStaff).filter(
            FieldStaff.id == int(claims.get("sid", -1)), FieldStaff.business_id == bid,
        ).first()
        if staff is None or not staff.is_active:
            raise HTTPException(status_code=401, detail="Account disabled — contact the owner")
        if int(claims.get("tv", 0)) != int(staff.token_version or 0):
            raise HTTPException(status_code=401, detail="Session revoked — please sign in again")
        if not staff.active_session_id or claims.get("ses") != staff.active_session_id:
            raise HTTPException(status_code=401, detail="Signed in on another device — this device was signed out")
        set_rls_business(db, bid)
        settings = get_settings(db, bid)
        if settings.device_policy == "bound" and staff.bound_device_id and claims.get("dev") != staff.bound_device_id:
            raise HTTPException(status_code=401, detail="This account is locked to another device")
        return Principal(kind="staff", business_id=bid, staff=staff)

    raise HTTPException(status_code=401, detail="Invalid session — please sign in again")


def require_owner(p: Principal = Depends(current_principal)) -> Principal:
    if p.kind != "owner":
        raise HTTPException(status_code=403, detail="Owner access required")
    return p


def require_staff(p: Principal = Depends(current_principal)) -> Principal:
    if p.kind != "staff":
        raise HTTPException(status_code=403, detail="Field staff access required")
    return p


def new_session_id() -> str:
    return secrets.token_urlsafe(18)


CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_bizid(db: Session) -> str:
    """BizID in billing's exact format (BA- + 6 Crockford base32), collision-checked.
    Uses `secrets` (billing uses `random`; the format is what must match)."""
    while True:
        candidate = "BA-" + "".join(secrets.choice(CROCKFORD) for _ in range(6))
        if not db.query(BillingUser.id).filter(BillingUser.public_id == candidate).first():
            return candidate
