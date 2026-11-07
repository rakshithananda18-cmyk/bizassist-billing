from __future__ import annotations
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
# HS256 requires >= 32 bytes (TS-09). Reject short keys to prevent silent key permutation.
if len(_raw_secret.encode()) < 32:
    raise ValueError(
        "[AUTH] JWT_SECRET must be at least 32 bytes long for secure HS256 signing. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )
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
    uid = to_encode.get("user_id") or to_encode.get("id")
    if uid is not None and "tv" not in to_encode:
        try:
            cur_tv = _current_token_version(int(uid))
            to_encode["tv"] = cur_tv if cur_tv is not None else 0
        except (TypeError, ValueError, HTTPException):
            # ``create_access_token`` is also used by tests and offline tooling.
            # Issuing a synthetic token is not authorization: get_active_user
            # will still reject a missing/revoked subject on first use.
            to_encode["tv"] = 0
    if expires_delta:
        expire = utc_now() + expires_delta
    else:
        expire = utc_now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt

SESSION_REJECTION_HEADERS = {"WWW-Authenticate": 'Bearer error="invalid_token"'}


def session_rejected(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers=SESSION_REJECTION_HEADERS)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        # Routine: a client's token aged out and it should re-authenticate. This
        # is expected operation, not a fault — log at INFO so it doesn't read as
        # a server error in the console.
        logger.info("[AUTH] 401 expired token — client should re-authenticate")
        raise session_rejected("Signature has expired")
    except jwt.InvalidTokenError:
        # Usually a stale client token after a backend restart / JWT_SECRET change
        # (e.g. a browser tab left open). Not a backend fault — INFO, not WARN.
        logger.info("[AUTH] 401 invalid/stale token — client should re-authenticate")
        raise session_rejected("Invalid token")

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


def bump_token_version(db, user) -> int:
    """Increment user's token_version and clear in-process cache to invalidate outstanding JWTs."""
    user.token_version = (user.token_version or 0) + 1
    clear_token_version_cache(user.id)
    return user.token_version


def _current_token_version(user_id: int) -> int:
    """Return a user's current token version, failing closed on uncertainty.

    JWTs are bearer credentials, so a missing subject must never be treated as
    an authenticated account. In particular, deleting a staff row must revoke
    its already-issued tokens immediately. A database outage also cannot become
    an authorization bypass; callers receive a retryable 503 instead.
    """
    now = _time.time()
    # A warm version cache must never keep a retired/deleted identity alive.
    # Read the narrow live-subject boundary on every authentication.
    try:
        from database.db import SessionLocal
        from database.models import User as _User
        db = SessionLocal()
        try:
            # This lookup opens its own session outside a request dependency.
            # ``users`` is FORCE RLS on Postgres, so explicitly scope that
            # session to the signed JWT subject before reading its row. Without
            # this, Postgres hides the row and a fail-closed check would reject
            # every valid cloud token.
            from database.security import subject_version
            row = subject_version(db, user_id)
        finally:
            db.close()
        if row is None:
            logger.info("[AUTH] 401 token subject no longer exists user_id=%s", user_id)
            raise session_rejected("Session revoked — please log in again")
        tv = row[0] if row[0] is not None else 0
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.warning("[AUTH] token_version lookup failed; rejecting request: %s", e)
        raise HTTPException(status_code=503, detail="Session validation is temporarily unavailable")
    _tv_cache[user_id] = (tv, now + _TV_CACHE_TTL)
    return tv


def _validate_token_version(payload: dict) -> None:
    """Fail closed unless the token names a live, matching account subject."""
    uid = payload.get("user_id") or payload.get("id")
    if uid is None:
        logger.info("[AUTH] 401 token missing account subject")
        raise session_rejected("Invalid session subject")
    try:
        current = _current_token_version(int(uid))
    except (TypeError, ValueError):
        logger.info("[AUTH] 401 token has invalid account subject user_id=%r", uid)
        raise session_rejected("Invalid session subject")
    try:
        presented_version = int(payload.get("tv", 0) or 0)
    except (ValueError, TypeError):
        raise session_rejected("Invalid session subject")
    if presented_version != current:
        logger.info("[AUTH] 401 revoked token (tv mismatch) user_id=%s", uid)
        raise session_rejected("Session revoked — please log in again")


def get_active_user(authorization: str = Header(None), token: str = Query(None)) -> dict:
    jwt_token = None
    if authorization and isinstance(authorization, str) and authorization.startswith("Bearer "):
        jwt_token = authorization.split(" ")[1]
    elif token and isinstance(token, str) and ALLOW_QUERY_TOKEN_AUTH:
        jwt_token = token

    if not jwt_token:
        logger.info("[AUTH] Request rejected — missing or malformed Authorization header")
        raise session_rejected("Bearer authorization token missing")
    # NOTE: the request-scoped BizID for [BizId=…] logging is set in the HTTP
    # middleware (main_groq.py), NOT here. A sync dependency runs in a threadpool
    # context that is discarded before the route handler, so setting the
    # contextvar here would never reach the handler's log lines.
    payload = decode_access_token(jwt_token)
    _validate_token_version(payload)
    _validate_parent_session(payload)
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


def require_business_owner(current_user: dict = Depends(get_active_user)) -> dict:
    """Require the token to belong to the business-owner identity itself.

    Business routes intentionally use ``id`` as the tenant scope, so staff JWTs
    carry their owner's id there. That is correct for floor work, but not for
    control-plane operations such as sync, imports, staff replication, or cloud
    token provisioning. Those actions require the authenticated person
    (``user_id``) to be the owner of that business as well.

    Fail closed for legacy tokens without a person identity. Re-authentication
    is safer than silently granting a staff session owner-level authority.
    """
    role = (current_user.get("role") or "").lower()
    if role in ("cashier", "supply adder"):
        raise HTTPException(status_code=403, detail="Permission denied: owner authentication required")

    business_id = current_user.get("id")
    user_id = current_user.get("user_id")
    try:
        if business_id is None or user_id is None or int(business_id) != int(user_id):
            raise HTTPException(status_code=403, detail="Permission denied: owner authentication required")
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail="Permission denied: owner authentication required")
    return current_user


def resolve_business_id_in_db(current_user: dict, db, require_public_id: bool = False) -> int:
    """Resolve a token's business to this database's *local* owner id.

    ``users.id`` is deliberately database-local: the same business can be id
    122 in the desktop database and id 7 in the cloud database. ``public_id``
    (BizID) is the stable identity shared by both. Never use a token's numeric
    ``id`` across a local/cloud boundary when a BizID is present.

    """
    is_cloud = getattr(getattr(db, "bind", None), "dialect", None) and db.bind.dialect.name == "postgresql"
    if is_cloud:
        require_public_id = True

    from database.models import User

    public_id = str(current_user.get("public_id") or "").strip()
    username = str(current_user.get("username") or current_user.get("sub") or "").strip()

    if public_id:
        owner = db.query(User).filter(
            User.public_id == public_id,
            User.parent_business_id.is_(None),
        ).first()
        if owner:
            return int(owner.id)
        logger.warning(
            "[AUTH] refusing business resolution for unknown BizID=%s user=%s",
            public_id, username or "-",
        )
        raise HTTPException(
            status_code=403,
            detail="BizID is not linked to a business on this server. Re-link this device before continuing.",
        )

    if require_public_id:
        logger.warning(
            "[AUTH] refusing business resolution without public_id user=%s",
            username or "-",
        )
        raise HTTPException(
            status_code=403,
            detail="Public business ID (public_id) is required for this operation. Re-authenticate before continuing.",
        )

    # Legacy-token compatibility is intentionally limited to records verified
    # in the current database. New tokens always carry public_id.
    if username:
        account = db.query(User).filter(User.username == username).first()
        if account:
            return int(account.parent_business_id or account.id)

    claimed_id = current_user.get("parent_business_id") or current_user.get("id")
    try:
        account = db.query(User).filter(User.id == int(claimed_id)).first()
    except (TypeError, ValueError):
        account = None
    if account:
        return int(account.parent_business_id or account.id)

    raise HTTPException(status_code=403, detail="Business identity could not be resolved on this server.")


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


from dataclasses import dataclass
from sqlalchemy.exc import IntegrityError


@dataclass(frozen=True)
class TicketCheck:
    claims: dict | None
    reason: str


def create_sse_ticket(user_payload: dict, expires_in_seconds: int = 30, *, aud=None) -> str:
    """Mint a purpose-bound short-lived ticket in the legacy wire format."""
    now = int(_time.time())
    exp = now + min(120, int(expires_in_seconds))
    claims = dict(user_payload, iat=now, jti=_secrets.token_hex(12))
    if aud is not None:
        claims["aud"] = aud
    raw = _json.dumps(claims, sort_keys=True, separators=(",", ":"), default=str)
    b64 = _base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    return f"{exp}.{b64}.{_ticket_sig(b64, exp)}"


_spent_inserts = 0


def _spend_ticket(ticket: str, exp: int, leeway: int) -> bool:
    """Atomically claim the digest, including across restarts and processes."""
    global _spent_inserts
    from database.db import SessionLocal
    from database.models import SpentTicket
    db = SessionLocal()
    try:
        digest = _hashlib.sha256(ticket.encode()).hexdigest()
        db.add(SpentTicket(digest=digest, expires_at=datetime.utcfromtimestamp(exp + leeway)))
        db.commit()
        _spent_inserts += 1
        if _spent_inserts % 100 == 0:
            stale = db.query(SpentTicket.digest).filter(SpentTicket.expires_at < utc_now() - timedelta(hours=1)).limit(500).all()
            if stale:
                db.query(SpentTicket).filter(SpentTicket.digest.in_([row[0] for row in stale])).delete(synchronize_session=False)
                db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
    except Exception as exc:
        db.rollback()
        logger.warning("[AUTH] Durable ticket claim unavailable; using process replay protection: %s", type(exc).__name__)
        return ticket not in _used_tickets
    finally:
        db.close()


def verify_ticket(ticket: str, *, audiences, leeway: int = 15) -> TicketCheck:
    """Verify bounded signed claims before consuming a single-use credential."""
    reason, claims, exp = "malformed", None, 0
    try:
        exp_s, b64, sig = ticket.split(".", 2)
        exp = int(exp_s)
        now = int(_time.time())
        if not _hmac.compare_digest(sig, _ticket_sig(b64, exp)):
            reason = "bad_signature"
        elif now > exp + leeway:
            reason = "expired"
        else:
            claims = _json.loads(_base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode())
            if not isinstance(claims, dict):
                reason = "malformed"
            elif claims.get("aud") not in audiences:
                reason = "wrong_audience"
            elif "iat" in claims and (not isinstance(claims["iat"], (int, float)) or exp - claims["iat"] > 120 or exp <= claims["iat"] or claims["iat"] > now + leeway):
                reason = "invalid_lifetime"
            elif ticket in _used_tickets or not _spend_ticket(ticket, exp, leeway):
                reason = "already_used"
            else:
                for tk, expiry in list(_used_tickets.items()):
                    if expiry < now:
                        _used_tickets.pop(tk, None)
                _used_tickets[ticket] = exp + leeway
                if claims.get("aud") is None:
                    logger.info("[AUTH] hand-off ticket accepted reason=legacy_no_aud")
                return TicketCheck(claims, "ok")
    except (ValueError, TypeError, AttributeError, UnicodeError):
        reason = "malformed"
    logger.info("[AUTH] hand-off ticket refused reason=%s exp_delta=%s", reason, exp - int(_time.time()))
    return TicketCheck(None, reason)


def redeem_sse_ticket(ticket: str) -> dict | None:
    return verify_ticket(ticket, audiences={None, "sse"}).claims


def _validate_parent_session(payload: dict) -> None:
    """Dashboard tokens inherit revocation of their originating Billing session."""
    if not payload.get("psid"):
        return
    from database.db import SessionLocal
    from database.models import RevokedSession
    db = SessionLocal()
    try:
        revoked = db.query(RevokedSession.sid).filter(RevokedSession.sid.in_([payload["psid"], payload.get("sid")]), RevokedSession.expires_at > utc_now()).first()
        if revoked:
            raise session_rejected("Session revoked — please log in again")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Session validation is temporarily unavailable")
    finally:
        db.close()


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
            raise session_rejected("Invalid or expired ticket")
        _validate_token_version(user)
        _validate_parent_session(user)
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
                # Bind tenant identity to session info so PostgreSQL RLS policies can evaluate (TS-06)
                tenant_id = current_user.get("business_id") or current_user.get("parent_business_id") or current_user.get("id")
                if tenant_id:
                    db.info["business_id"] = int(tenant_id)
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

