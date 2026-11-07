"""
services/router_mode.py — runtime switch between LEGACY and NEW routing.
========================================================================
Lets you flip routers WHILE THE SERVER IS RUNNING (no restart):

    legacy  — the exact previous behaviour: regex stack routes, the LLM router
              is never called. (alias: "off")
    shadow  — legacy still answers everything; the LLM router runs silently in
              the background and logs AGREE/DISAGREE for analyze_llm_shadow.py.
    new     — the LLM router steers (advise / action / analyze / chat / direct);
              legacy remains the automatic fallback on any LLM failure.
              (alias: "on")

The admin endpoint persists overrides in platform_settings. Every instance
refreshes its cache within 30 seconds; LLM_ROUTER supplies the default when
there is no saved override.
"""
import logging
import os
import time
from threading import Lock

logger = logging.getLogger("bizassist.router_mode")

_ALIASES = {
    "legacy": "off", "off": "off",
    "shadow": "shadow",
    "new": "on", "on": "on", "llm": "on",
}
VALID_MODES = ("off", "shadow", "on")
_PRETTY = {"off": "legacy", "shadow": "shadow", "on": "new"}

_lock = Lock()
_explicit = None
_cached_at = 0.0
_cached_value = None
_cache_known = False
_CACHE_TTL_S = 30
_store_warned = False


def _normalize(value: str):
    return _ALIASES.get((value or "").strip().lower())


def _store(value=None, *, updated_by=None, delete=False):
    from database.db import SessionLocal
    from database.models import PlatformSetting
    from services.dates import utc_now
    db = SessionLocal()
    try:
        row = db.get(PlatformSetting, "llm_router")
        if delete:
            if row is not None:
                db.delete(row)
            db.commit()
        elif value is not None:
            if row is None:
                db.add(PlatformSetting(key="llm_router", value=value, updated_at=utc_now(), updated_by=updated_by))
            else:
                row.value, row.updated_at, row.updated_by = value, utc_now(), updated_by
            db.commit()
        else:
            return _normalize(row.value) if row else None
    finally:
        db.close()


def get_mode() -> str:
    global _explicit, _cached_at, _cached_value, _cache_known, _store_warned
    with _lock:
        if _cache_known and _explicit == _cached_value and time.monotonic() - _cached_at < _CACHE_TTL_S:
            return _explicit or _normalize(os.getenv("LLM_ROUTER", "off")) or "off"
        try:
            _explicit = _store()
        except Exception as exc:
            if not _store_warned:
                logger.warning("[ROUTER] Persistent mode unavailable; using this instance's mode: %s", type(exc).__name__)
                _store_warned = True
        _cached_at, _cached_value, _cache_known = time.monotonic(), _explicit, True
        return _explicit or _normalize(os.getenv("LLM_ROUTER", "off")) or "off"


def set_mode(value: str, *, updated_by=None) -> str:
    global _explicit, _cached_at, _cached_value, _cache_known
    norm = _normalize(value)
    if norm is None:
        raise ValueError(f"invalid mode '{value}' — use one of: legacy, shadow, new")
    # Persist before changing the running process, so a failed admin write is
    # visible and never claims to have changed every instance.
    _store(norm, updated_by=updated_by)
    with _lock:
        _explicit, _cached_at, _cached_value, _cache_known = norm, time.monotonic(), norm, True
    logger.info("[ROUTER] mode switched to %s", _PRETTY[norm])
    return norm


def reset_mode() -> None:
    global _explicit, _cached_at, _cached_value, _cache_known
    try:
        _store(delete=True)
    except Exception as exc:
        logger.warning("[ROUTER] Persistent reset unavailable: %s", type(exc).__name__)
    with _lock:
        _explicit, _cached_at, _cached_value, _cache_known = None, 0.0, None, False


def pretty(mode: str = None) -> str:
    """Human name for a mode ('off' → 'legacy', 'on' → 'new')."""
    return _PRETTY.get(mode or get_mode(), "legacy")
