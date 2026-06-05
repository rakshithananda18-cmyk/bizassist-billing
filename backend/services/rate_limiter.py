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
from datetime import datetime, date
from database.db import SessionLocal
from database.models import RateLimitConfig, TokenUsage

logger = logging.getLogger("bizassist.rate_limiter")

# ── In-memory sliding window for per-minute tracking ─────────────────
# { business_id: deque of timestamps }
_minute_window: dict = defaultdict(deque)

# Default limits applied when no config exists for a user
DEFAULTS = {
    "requests_per_minute": 10,
    "requests_per_day":    500,
    "max_tokens_per_day":  50000,
    "complex_per_day":     20,
}


def _get_config(business_id: int) -> dict:
    """Fetch rate limit config for a user, falling back to defaults."""
    db = SessionLocal()
    try:
        cfg = db.query(RateLimitConfig).filter(
            RateLimitConfig.business_id == business_id,
            RateLimitConfig.active == True
        ).first()
        if cfg:
            return {
                "requests_per_minute": cfg.requests_per_minute,
                "requests_per_day":    cfg.requests_per_day,
                "max_tokens_per_day":  cfg.max_tokens_per_day,
                "complex_per_day":     cfg.complex_per_day,
            }
        return DEFAULTS.copy()
    finally:
        db.close()


def _get_today_usage(business_id: int) -> dict:
    """Returns today's query count, token total, and complex count from DB."""
    db = SessionLocal()
    try:
        today_start = datetime.combine(date.today(), datetime.min.time())
        rows = db.query(TokenUsage).filter(
            TokenUsage.business_id == business_id,
            TokenUsage.timestamp >= today_start
        ).all()

        total_queries  = len(rows)
        total_tokens   = sum(r.total_tokens or 0 for r in rows)
        complex_queries = sum(1 for r in rows if r.model_tier == "AI_COMPLEX")

        return {
            "queries_today":  total_queries,
            "tokens_today":   total_tokens,
            "complex_today":  complex_queries,
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
    now   = datetime.utcnow()

    # ── 1. Per-minute check (in-memory sliding window) ────────────────
    window = _minute_window[business_id]
    cutoff = now.timestamp() - 60
    while window and window[0] < cutoff:
        window.popleft()

    if len(window) >= cfg["requests_per_minute"]:
        logger.warning(f"[RateLimit] User {business_id} hit per-minute limit ({cfg['requests_per_minute']}/min)")
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
        logger.warning(f"[RateLimit] User {business_id} hit daily query limit ({cfg['requests_per_day']}/day)")
        return {
            "allowed": False,
            "reason":  f"Daily limit reached: max {cfg['requests_per_day']} queries per day.",
            "limit":   cfg["requests_per_day"],
            "used":    usage["queries_today"],
            "retry_after": "tomorrow"
        }

    if usage["tokens_today"] >= cfg["max_tokens_per_day"]:
        logger.warning(f"[RateLimit] User {business_id} hit daily token limit ({cfg['max_tokens_per_day']} tokens)")
        return {
            "allowed": False,
            "reason":  f"Daily token budget exhausted: max {cfg['max_tokens_per_day']:,} tokens per day.",
            "limit":   cfg["max_tokens_per_day"],
            "used":    usage["tokens_today"],
            "retry_after": "tomorrow"
        }

    if route == "AI_COMPLEX" and usage["complex_today"] >= cfg["complex_per_day"]:
        logger.warning(f"[RateLimit] User {business_id} hit daily complex limit ({cfg['complex_per_day']}/day)")
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
