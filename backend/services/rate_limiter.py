"""
rate_limiter.py
===============
Enforces per-user rate limits configured by admin.

Checks (in order):
  1. Requests per minute  — in-memory sliding window (burst protection)
  2. Requests per day     — from TokenUsage table (daily query cap)
  3. Tokens per day       — from TokenUsage table (cost control)
  4. AI_COMPLEX per day   — from TokenUsage table (agent graph cap)

Returns a dict: {"allowed": True} or {"allowed": False, "reason": "...", "limit": N, "used": N}
"""

import logging
from collections import defaultdict, deque
from datetime import datetime
from sqlalchemy import func, case
from database.db import SessionLocal
from database.models import RateLimitConfig, TokenUsage
from services.dates import utc_now

logger = logging.getLogger("bizassist.rate_limiter")

# ── In-memory sliding window for per-minute tracking ─────────────────
# { business_id: deque of timestamps }
_minute_window: dict = defaultdict(deque)

# ── In-memory sliding window for IP-based tracking (login brute-force)
_ip_window: dict = defaultdict(deque)

# ── In-memory sliding window for upload tracking (upload abuse) ──────
_upload_window: dict = defaultdict(deque)

# Default limits applied when no config exists for a user
DEFAULTS = {
    "requests_per_minute": 10,
    "requests_per_day":    500,
    "max_tokens_per_day":  50000,
    "complex_per_day":     20,
    "active":              True,
}


def _get_config(business_id: int) -> dict:
    """
    Fetch a user's rate-limit config, falling back to defaults.

    The saved row is the single source of truth for the *numbers* — we do NOT
    filter on `active` here, so the admin modal and the live usage stats always
    show the same limits. `active` is returned separately and gates enforcement
    in check_rate_limit(): active=False means rate limiting is OFF for this
    merchant (allow everything), NOT "revert to the stricter defaults".
    """
    db = SessionLocal()
    try:
        cfg = db.query(RateLimitConfig).filter(
            RateLimitConfig.business_id == business_id
        ).first()
        if cfg:
            return {
                "requests_per_minute": cfg.requests_per_minute,
                "requests_per_day":    cfg.requests_per_day,
                "max_tokens_per_day":  cfg.max_tokens_per_day,
                "complex_per_day":     cfg.complex_per_day,
                "active":              cfg.active,
            }
        return DEFAULTS.copy()
    finally:
        db.close()


def _get_today_usage(business_id: int) -> dict:
    """
    Returns today's query count, token total, and complex count.

    Uses a single SQL aggregate (COUNT/SUM) instead of loading every row of the
    day into Python and summing — O(1) work in the DB on every AI request (H4).
    """
    db = SessionLocal()
    try:
        # UTC boundary — TokenUsage.timestamp is stored with utc_now(), so
        # "today" must also be UTC. Using local date.today() here mis-counted the
        # daily total near midnight (e.g. first hours of an IST day, when utcnow()
        # is still the previous UTC date), under-enforcing the cap.
        today_start = datetime.combine(utc_now().date(), datetime.min.time())
        total_queries, total_tokens, complex_queries = (
            db.query(
                func.count(TokenUsage.id),
                func.coalesce(func.sum(TokenUsage.total_tokens), 0),
                func.coalesce(
                    func.sum(case((TokenUsage.model_tier == "AI_COMPLEX", 1), else_=0)), 0
                ),
            )
            .filter(
                TokenUsage.business_id == business_id,
                TokenUsage.timestamp >= today_start,
            )
            .one()
        )
        return {
            "queries_today":  int(total_queries or 0),
            "tokens_today":   int(total_tokens or 0),
            "complex_today":  int(complex_queries or 0),
        }
    finally:
        db.close()


def check_rate_limit(business_id: int, route: str = "AI_SIMPLE") -> dict:
    """
    Main entry point. Call before processing any AI query.

    Args:
        business_id: The user's ID
        route: "AI_SIMPLE", "AI_COMPLEX", or "DIRECT"

    Returns:
        {"allowed": True} or
        {"allowed": False, "reason": str, "limit": int, "used": int}
    """
    # DIRECT queries are always free — no limit check needed
    if route == "DIRECT":
        return {"allowed": True}

    cfg   = _get_config(business_id)

    # Rate limiting explicitly disabled for this merchant -> allow everything.
    if not cfg.get("active", True):
        return {"allowed": True}

    now   = utc_now()

    # ── 1. Per-minute check (in-memory sliding window) ────────────────
    window = _minute_window[business_id]
    cutoff = now.timestamp() - 60
    while window and window[0] < cutoff:
        window.popleft()

    if len(window) >= cfg["requests_per_minute"]:
        logger.warning(f"[RATELIMIT] User {business_id} hit per-minute limit ({cfg['requests_per_minute']}/min)")
        return {
            "allowed": False,
            "reason":  f"Rate limit: max {cfg['requests_per_minute']} requests per minute.",
            "limit":   cfg["requests_per_minute"],
            "used":    len(window),
            "retry_after": "60 seconds"
        }
    window.append(now.timestamp())

    # ── 2–4. Daily checks (from DB) ───────────────────────────────────
    usage = _get_today_usage(business_id)

    if usage["queries_today"] >= cfg["requests_per_day"]:
        logger.warning(f"[RATELIMIT] User {business_id} hit daily query limit ({cfg['requests_per_day']}/day)")
        return {
            "allowed": False,
            "reason":  f"Daily limit reached: max {cfg['requests_per_day']} queries per day.",
            "limit":   cfg["requests_per_day"],
            "used":    usage["queries_today"],
            "retry_after": "tomorrow"
        }

    if usage["tokens_today"] >= cfg["max_tokens_per_day"]:
        logger.warning(f"[RATELIMIT] User {business_id} hit daily token limit ({cfg['max_tokens_per_day']} tokens)")
        return {
            "allowed": False,
            "reason":  f"Daily token budget exhausted: max {cfg['max_tokens_per_day']:,} tokens per day.",
            "limit":   cfg["max_tokens_per_day"],
            "used":    usage["tokens_today"],
            "retry_after": "tomorrow"
        }

    if route == "AI_COMPLEX" and usage["complex_today"] >= cfg["complex_per_day"]:
        logger.warning(f"[RATELIMIT] User {business_id} hit daily complex limit ({cfg['complex_per_day']}/day)")
        return {
            "allowed": False,
            "reason":  f"Daily limit for advanced analysis reached: max {cfg['complex_per_day']} per day.",
            "limit":   cfg["complex_per_day"],
            "used":    usage["complex_today"],
            "retry_after": "tomorrow"
        }

    return {"allowed": True}


def get_usage_summary(business_id: int) -> dict:
    """Returns current usage + limits for a business. Used by admin dashboard."""
    cfg   = _get_config(business_id)
    usage = _get_today_usage(business_id)
    return {
        "business_id":         business_id,
        "queries_today":       usage["queries_today"],
        "queries_limit":       cfg["requests_per_day"],
        "tokens_today":        usage["tokens_today"],
        "tokens_limit":        cfg["max_tokens_per_day"],
        "complex_today":       usage["complex_today"],
        "complex_limit":       cfg["complex_per_day"],
        "requests_per_minute": cfg["requests_per_minute"],
    }


def check_ip_rate_limit(ip_address: str, limit: int = 10) -> dict:
    """
    In-memory sliding window rate limiter by IP (for /login).
    Default limit: 10 requests per minute.
    """
    now = utc_now().timestamp()
    window = _ip_window[ip_address]
    cutoff = now - 60
    while window and window[0] < cutoff:
        window.popleft()

    if len(window) >= limit:
        logger.warning(f"[RATELIMIT] IP {ip_address} hit rate limit ({limit}/min)")
        return {
            "allowed": False,
            "reason": f"Rate limit exceeded: max {limit} login requests per minute.",
            "limit": limit,
            "used": len(window),
            "retry_after": "60 seconds"
        }
    window.append(now)
    return {"allowed": True}


def check_upload_rate_limit(business_id: int, limit: int = 5) -> dict:
    """
    In-memory sliding window rate limiter by business_id (for /upload).
    Default limit: 5 file uploads per minute.
    """
    now = utc_now().timestamp()
    window = _upload_window[business_id]
    cutoff = now - 60
    while window and window[0] < cutoff:
        window.popleft()

    if len(window) >= limit:
        logger.warning(f"[RATELIMIT] User {business_id} hit upload rate limit ({limit}/min)")
        return {
            "allowed": False,
            "reason": f"Rate limit exceeded: max {limit} file uploads per minute.",
            "limit": limit,
            "used": len(window),
            "retry_after": "60 seconds"
        }
    window.append(now)
    return {"allowed": True}

