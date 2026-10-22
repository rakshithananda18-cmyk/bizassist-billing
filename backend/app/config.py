"""
app/config.py — every environment knob in one place.
====================================================
BizAssist Task shares two things with BizAssist Billing and owns everything else:

  * the DATABASE (`DATABASE_URL`) — the same Supabase Postgres the billing cloud
    backend uses, so an owner's account, BizID and customers are one record;
  * the SECRET (`JWT_SECRET`) — so a billing owner token can be exchanged for a
    task token (single sign-on), and so field tokens can be signed with a key
    DERIVED from it that billing can never accept (see app/security.py).

Read once at import. Tests set env vars before importing the app.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _normalize_db_url(url: str) -> str:
    """Pin the psycopg2 driver. SQLAlchemy 2.1 resolves a bare `postgresql://`
    to psycopg (v3), which is not installed; Supabase hands out bare URLs, and
    some tools still emit the legacy `postgres://` scheme."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


DATABASE_URL = _normalize_db_url(os.environ.get("DATABASE_URL", "sqlite:///./bizassist_task.db"))
IS_SQLITE = DATABASE_URL.startswith("sqlite")

_raw_secret = os.environ.get("JWT_SECRET", "")
if not _raw_secret:
    raise RuntimeError(
        "JWT_SECRET is not set. Use the SAME value as the BizAssist billing backend "
        "so owners can sign in with one account. Generate one with: "
        "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )
if len(_raw_secret.encode()) < 32:
    # Billing pads short secrets with random bytes at boot, which makes its tokens
    # unverifiable by any other process. Refuse instead of silently diverging.
    raise RuntimeError("JWT_SECRET must be at least 32 bytes (same value as billing).")
JWT_SECRET = _raw_secret

# Task-app token lifetime. Field staff keep the app open all day; 14h covers a
# shift without forcing a mid-route re-login. Owners use the same TTL.
ACCESS_TOKEN_TTL_MINUTES = _int("TASK_TOKEN_TTL_MINUTES", 14 * 60)

# Business wall clock. Attendance dates, "today's route" and lateness are all
# computed in this zone from SERVER time — never from the phone's clock.
BIZ_TIMEZONE = os.environ.get("BIZ_TIMEZONE", "Asia/Kolkata")

# Run our own (ft_*) Alembic chain on startup. Additive, own version table, never
# touches billing tables. Set 0 to migrate manually.
AUTO_MIGRATE = _bool("TASK_AUTO_MIGRATE", True)

# In dev/test on SQLite we also create the minimal billing tables (users,
# customers) so the app runs standalone. On Postgres they belong to billing and
# are NEVER created or altered from here.
CREATE_BILLING_MIRROR = _bool("TASK_CREATE_BILLING_MIRROR", IS_SQLITE)

# Allow owners to create a BizAssist account from the task app. The row written
# is identical in shape to billing's own /signup (role=enterprise + BizID), so
# the same login works in billing too.
ALLOW_SIGNUP = _bool("TASK_ALLOW_SIGNUP", True)

# Raw GPS pings older than this are purged daily. Event locations (check-in,
# arrival, task completion) live on their own rows and are kept.
PING_RETENTION_DAYS = _int("TASK_PING_RETENTION_DAYS", 60)

# Comma-separated extra CORS origins (the Vercel URL, if the PWA is hosted there).
_default_origins = (
    "http://localhost:5176,http://127.0.0.1:5176,"
    "http://localhost:4173,http://127.0.0.1:4173"
)
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()
]

# Built PWA to serve at "/" (the Docker image copies frontend/dist here).
STATIC_DIR = os.environ.get("TASK_STATIC_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
