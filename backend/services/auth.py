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
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24 hours

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
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("[AUTH] Token rejected — signature expired")
        raise HTTPException(status_code=401, detail="Signature has expired")
    except jwt.InvalidTokenError:
        logger.warning("[AUTH] Token rejected — invalid token")
        raise HTTPException(status_code=401, detail="Invalid token")

def get_active_user(authorization: str = Header(None), token: str = Query(None)) -> dict:
    jwt_token = None
    if authorization and isinstance(authorization, str) and authorization.startswith("Bearer "):
        jwt_token = authorization.split(" ")[1]
    elif token and isinstance(token, str):
        jwt_token = token
        
    if not jwt_token:
        logger.info("[AUTH] Request rejected — missing or malformed Authorization header or query token")
        raise HTTPException(status_code=401, detail="Bearer authorization token or query token missing")
    return decode_access_token(jwt_token)


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
_sse_tickets = {}

def create_sse_ticket(user_payload: dict, expires_in_seconds: int = 30) -> str:
    """Generate a single-use random ticket token and save it with a short TTL."""
    now = datetime.utcnow()
    # Periodic in-line cleanup of expired tickets
    for tk, val in list(_sse_tickets.items()):
        if now > val["expires"]:
            _sse_tickets.pop(tk, None)
            
    ticket = _secrets.token_urlsafe(32)
    _sse_tickets[ticket] = {
        "user": user_payload,
        "expires": now + timedelta(seconds=expires_in_seconds)
    }
    return ticket

def get_active_user_or_ticket(
    authorization: str = Header(None),
    token: str = Query(None),
    ticket: str = Query(None)
) -> dict:
    """Authenticate via header JWT, query JWT, or short-lived SSE ticket."""
    if ticket:
        now = datetime.utcnow()
        ticket_data = _sse_tickets.get(ticket)
        if not ticket_data:
            logger.warning("[AUTH] Ticket not found or already used")
            raise HTTPException(status_code=401, detail="Invalid or expired ticket")
        if now > ticket_data["expires"]:
            _sse_tickets.pop(ticket, None)
            logger.warning("[AUTH] Ticket expired")
            raise HTTPException(status_code=401, detail="Invalid or expired ticket")
        
        # Pop to enforce single-use
        _sse_tickets.pop(ticket, None)
        logger.info("[AUTH] Ticket verified successfully for user %s", ticket_data["user"].get("username"))
        return ticket_data["user"]
    
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


def require_plan(min_plan: str = "pro"):
    """FastAPI dependency factory: 402 when the business's effective plan is
    below `min_plan` (staff inherit the owner's plan). No-op unless
    SUBSCRIPTION_ENFORCED=1."""
    def _dep(current_user: dict = Depends(get_active_user)) -> dict:
        if not subscription_enforced():
            return current_user
        if (current_user.get("role") or "").lower() == "admin":
            return current_user
        from database.db import SessionLocal
        from database.models import User as _User
        from services.admin_service import effective_plan
        db = SessionLocal()
        try:
            row = db.query(_User).filter(_User.username == current_user.get("username")).first()
            holder = row
            if row and row.parent_business_id:
                holder = db.query(_User).filter(_User.id == row.parent_business_id).first() or row
            plan = effective_plan(holder) if holder else "free"
        finally:
            db.close()
        if min_plan == "pro" and plan != "pro":
            logger.info("[AUTH] plan gate: user=%s plan=%s needs=%s",
                        current_user.get("username"), plan, min_plan)
            raise HTTPException(
                status_code=402,
                detail="This feature requires the Pro plan. Contact your provider to upgrade.",
            )
        return current_user
    return _dep

