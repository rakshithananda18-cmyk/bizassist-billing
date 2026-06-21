import os
import bcrypt
import jwt
import logging
from datetime import datetime, timedelta
from fastapi import Header, HTTPException, Depends

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

def get_active_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        logger.info("[AUTH] Request rejected — missing or malformed Authorization header")
        raise HTTPException(status_code=401, detail="Bearer authorization token missing or malformed")
    token = authorization.split(" ")[1]
    return decode_access_token(token)


# ── Role-based access control (single source of truth) ───────────────────────
# Staff roles today:
#   • owner-level — anything NOT "cashier" (e.g. "enterprise"/"admin"/"owner"):
#                   full access.
#   • "cashier"   — billing-floor staff: ring up sales + take payments, but NOT
#                   reports/margins, returns/credit notes, imports, or settings.
# Guards raise 403 so a forbidden role never reaches the route body.

def restrict_cashier(current_user: dict = Depends(get_active_user)) -> dict:
    """Block cashiers from owner-only (admin / financial) actions."""
    if (current_user.get("role") or "").lower() == "cashier":
        logger.info("[AUTH] cashier blocked from owner-only action (user=%s)",
                    current_user.get("username"))
        raise HTTPException(status_code=403, detail="Permission denied: cashier restricted")
    return current_user

# Readable alias for owner-only routes.
require_owner = restrict_cashier
