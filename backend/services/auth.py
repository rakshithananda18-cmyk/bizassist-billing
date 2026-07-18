import os
import bcrypt
import jwt
import logging
from datetime import datetime, timedelta
from fastapi import Header, HTTPException, Depends, Query

import secrets as _secrets

logger = logging.getLogger("bizassist.auth")

_raw_secret = os.environ.get("JWT_SECRET", "")
if not _raw_secret:
    raise RuntimeError(
        "JWT_SECRET environment variable is not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )
# HS256 requires >= 32 bytes. Pad short secrets rather than crash — but log a warning.
if len(_raw_secret.encode()) < 32:
    logger.warning(
        "[AUTH] JWT_SECRET is shorter than 32 bytes — pad it or use a longer key in production."
    )
    _raw_secret = _raw_secret + _secrets.token_hex(16)   # pad to safe length
JWT_SECRET = _raw_secret
JWT_ALGORITHM = "HS256"
# Env-tunable (REVIEW_1 GAP-1). Default stays 24h for backward compatibility;
# lower it (e.g. 60) once clients call POST /auth/refresh to slide sessions.
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_TTL_MINUTES", "1440"))

# Generic `?token=` query auth leaks JWTs into server logs / proxies / history.
# No frontend uses it (SSE uses single-use tickets) — fail closed by default;
# set ALLOW_QUERY_TOKEN_AUTH=1 only if an old integration still needs it.
ALLOW_QUERY_TOKEN_AUTH = os.environ.get("ALLOW_QUERY_TOKEN_AUTH", "0") == "1"

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = utc_now() + expires_delta
    else:
        expire = utc_now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        # Routine: a client's token aged out and it should re-authenticate. This
        # is expected operation, not a fault — log at INFO so it doesn't read as
        # a server error in the console.
        logger.info("[AUTH] 401 expired token — client should re-authenticate")
        raise HTTPException(status_code=401, detail="Signature has expired")
    except jwt.InvalidTokenError:
        # Usually a stale client token after a backend restart / JWT_SECRET change
        # (e.g. a browser tab left open). Not a backend fault — INFO, not WARN.
        logger.info("[AUTH] 401 invalid/stale token — client should re-authenticate")
        raise HTTPException(status_code=401, detail="Invalid token")

# ── Token revocation (REVIEW_1 GAP-1) ────────────────────────────────────────
# Every JWT carries a `tv` (token_version) claim; users.token_version is the
# source of truth. Bumping the row invalidates all outstanding tokens for that
# account within _TV_CACHE_TTL seconds. Legacy tokens without a `tv` claim are
# treated as tv=0, so nothing breaks on deploy — a bump revokes those too.
import time as _time
from services.dates import utc_now

_tv_cache: dict = {}          # user_id -> (token_version, expires_epoch)
_TV_CACHE_TTL = 30            # seconds; the max delay before a revoke takes effect


def clear_token_version_cache(user_id: int = None) -> None:
    """Drop the cached token_version so a bump is seen immediately in-process."""
    if user_id is None:
        _tv_cache.clear()
    else:
        _tv_cache.pop(user_id, None)


def _current_token_version(user_id: int):
    """DB-backed token_version with a short in-process cache. Returns None when
    it cannot be determined (row missing / DB error) — caller skips the check
    rather than 401-ing every request during a transient DB hiccup."""
    now = _time.time()
    hit = _tv_cache.get(user_id)
    if hit and hit[1] > now:
        return hit[0]
    try:
        from database.db import SessionLocal
        from database.models import User as _User
        db = SessionLocal()
        try:
            row = db.query(_User.token_version).filter(_User.id == user_id).first()
        finally:
            db.close()
        if row is None:
            return None
        tv = row[0] if row[0] is not None else 0
    except Exception as e:
        logger.debug("[AUTH] token_version lookup failed (skipping check): %s", e)
        return None
    _tv_cache[user_id] = (tv, now + _TV_CACHE_TTL)
    return tv


def _validate_token_version(payload: dict) -> None:
    """401 when the token's `tv` claim no longer matches the account row."""
    uid = payload.get("user_id") or payload.get("id")
    if uid is None:
        return
    try:
        current = _current_token_version(int(uid))
    except (TypeError, ValueError):
        return
    if current is None:
        return
    if int(payload.get("tv", 0) or 0) != current:
        logger.info("[AUTH] 401 revoked token (tv mismatch) user_id=%s", uid)
        raise HTTPException(status_code=401, detail="Session revoked — please log in again")


def get_active_user(authorization: str = Header(None), token: str = Query(None)) -> dict:
    jwt_token = None
    if authorization and isinstance(authorization, str) and authorization.startswith("Bearer "):
        jwt_token = authorization.split(" ")[1]
    elif token and isinstance(token, str) and ALLOW_QUERY_TOKEN_AUTH:
        jwt_token = token

    if not jwt_token:
        logger.info("[AUTH] Request rejected — missing or malformed Authorization header")
        raise HTTPException(status_code=401, detail="Bearer authorization token missing")
    # NOTE: the request-scoped BizID for [BizId=…] logging is set in the HTTP
    # middleware (main_groq.py), NOT here. A sync dependency runs in a threadpool
    # context that is discarded before the route handler, so setting the
    # contextvar here would never reach the handler's log lines.
    payload = decode_access_token(jwt_token)
    _validate_token_version(payload)
    return payload


# ── Role-based access control (single source of truth) ───────────────────────
# Staff roles today:
#   • owner-level — anything NOT "cashier" (e.g. "enterprise"/"admin"/"owner"):
#                   full access.
#   • "cashier"   — billing-floor staff: ring up sales + take payments, but NOT
#                   reports/margins, returns/credit notes, imports, or settings.
# Guards raise 403 so a forbidden role never reaches the route body.

def restrict_cashier(current_user: dict = Depends(get_active_user)) -> dict:
    """Block cashiers and supply adders from owner-only (admin / financial) actions."""
    role_lower = (current_user.get("role") or "").lower()
    if role_lower in ("cashier", "supply adder"):
        logger.info("[AUTH] staff blocked from owner-only action (user=%s, role=%s)",
                    current_user.get("username"), role_lower)
        raise HTTPException(status_code=403, detail="Permission denied: staff restricted")
    return current_user

def restrict_cashier_only(current_user: dict = Depends(get_active_user)) -> dict:
    """Block cashiers but allow supply adders and owners."""
    role_lower = (current_user.get("role") or "").lower()
    if role_lower == "cashier":
        logger.info("[AUTH] cashier blocked from action (user=%s)",
                    current_user.get("username"))
        raise HTTPException(status_code=403, detail="Permission denied: cashier restricted")
    return current_user

# Readable alias for owner-only routes.
require_owner = restrict_cashier


# ── SSE Ticket Authentication ────────────────────────────────────────────────
# Stateless HMAC-signed tickets (BUG-4 / MASTER_REVIEW §2.3 #9).
# The previous in-memory dict dropped every outstanding ticket on a server
# restart ("live counter randomly disconnects" on the HF tier) and could never
# work with >1 worker. Tickets are now self-contained —
#   "<exp_unix>.<payload_b64url>.<hmac_sha256_hex>"  keyed on JWT_SECRET —
# so any worker, before or after a restart, can verify them (same pattern as
# services/action_rails.py confirm tokens). Single-use is enforced via a
# best-effort in-memory used-set: with a ≤30s TTL the replay window after a
# restart is negligible, and the HMAC + expiry still gate everything.
import hmac as _hmac
import json as _json
import base64 as _base64
import hashlib as _hashlib

_used_tickets: dict = {}   # ticket -> exp_unix (for cleanup)


def _ticket_sig(b64_payload: str, exp: int) -> str:
    msg = f"sse|{b64_payload}|{exp}".encode()
    return _hmac.new(JWT_SECRET.encode(), msg, _hashlib.sha256).hexdigest()


def create_sse_ticket(user_payload: dict, expires_in_seconds: int = 30) -> str:
    """Mint a short-lived, single-use, stateless (restart-proof) ticket."""
    exp = int(_time.time()) + int(expires_in_seconds)
    raw = _json.dumps(user_payload, sort_keys=True, separators=(",", ":"), default=str)
    b64 = _base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    return f"{exp}.{b64}.{_ticket_sig(b64, exp)}"


def redeem_sse_ticket(ticket: str) -> dict | None:
    """Verify signature + expiry, enforce single-use; return user payload or None."""
    try:
        exp_s, b64, sig = ticket.split(".", 2)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return None
    now = int(_time.time())
    if now > exp:
        return None
    if not _hmac.compare_digest(sig, _ticket_sig(b64, exp)):
        return None
    if ticket in _used_tickets:   # single-use (best-effort across restarts)
        return None
    for tk, e in list(_used_tickets.items()):   # opportunistic cleanup
        if e < now:
            _used_tickets.pop(tk, None)
    _used_tickets[ticket] = exp
    try:
        pad = "=" * (-len(b64) % 4)
        return _json.loads(_base64.urlsafe_b64decode(b64 + pad).decode())
    except Exception:
        return None


def get_active_user_or_ticket(
    authorization: str = Header(None),
    token: str = Query(None),
    ticket: str = Query(None)
) -> dict:
    """Authenticate via header JWT, query JWT, or short-lived SSE ticket."""
    if ticket:
        user = redeem_sse_ticket(ticket)
        if user is None:
            logger.warning("[AUTH] Ticket invalid, expired, or already used")
            raise HTTPException(status_code=401, detail="Invalid or expired ticket")
        logger.info("[AUTH] Ticket verified successfully for user %s", user.get("username"))
        return user

    return get_active_user(authorization=authorization, token=token)

def restrict_cashier_or_ticket(current_user: dict = Depends(get_active_user_or_ticket)) -> dict:
    """Block cashiers from accessing routes, supporting ticket authentication."""
    if (current_user.get("role") or "").lower() == "cashier":
        logger.info("[AUTH] cashier blocked from owner-only action (user=%s)",
                    current_user.get("username"))
        raise HTTPException(status_code=403, detail="Permission denied: cashier restricted")
    return current_user


# ── Subscription gating (Admin Console plan, Phase B.5) ──────────────────────
# require_plan("pro") is a dependency factory for plan-gated routes (/ask*,
# hybrid sync activation). Enforcement is behind SUBSCRIPTION_ENFORCED
# (default "0") so the hooks can ship — and the console can grant plans —
# before the paywall actually flips on. Admins always pass.

def subscription_enforced() -> bool:
    import os
    return os.getenv("SUBSCRIPTION_ENFORCED", "0") == "1"


def require_plan(min_plan: str = "pro", force_enforcement: bool = False):
    """FastAPI dependency factory: 402 when the business's effective plan is
    below `min_plan` (staff inherit the owner's plan). No-op unless
    SUBSCRIPTION_ENFORCED=1 or force_enforcement=True."""
    def _dep(current_user: dict = Depends(get_active_user)) -> dict:
        uname = current_user.get("username")
        is_admin = (current_user.get("role") or "").lower() == "admin"
 
        # Resolve the effective plan (admins are always "pro"). Staff inherit the
        # owner's plan. We compute it even when enforcement is OFF so the tier is
        # always logged — this is the pro/free segregation signal.
        if is_admin:
            plan = "pro"
        else:
            from database.db import SessionLocal
            from database.models import User as _User
            from services.admin_service import effective_plan
            db = SessionLocal()
            try:
                row = db.query(_User).filter(_User.username == uname).first()
                holder = row
                if row and row.parent_business_id:
                    holder = db.query(_User).filter(_User.id == row.parent_business_id).first() or row
                plan = effective_plan(holder) if holder else "free"
            finally:
                db.close()
 
        enforced = subscription_enforced() or force_enforcement
        allowed = is_admin or (not enforced) or (min_plan != "pro") or (plan == "pro")
        tier = "admin" if is_admin else plan
        # Block → INFO (actionable). Allow → DEBUG (available for audit, no noise).
        (logger.info if not allowed else logger.debug)(
            "[PLAN] tier=%s user=%s needs=%s enforced=%s decision=%s",
            tier, uname, min_plan, enforced, "block" if not allowed else "allow",
        )
        if not allowed:
            raise HTTPException(
                status_code=402,
                detail="This feature requires the Pro plan. Contact your provider to upgrade.",
            )
        return current_user
    return _dep
# (end of auth service)

