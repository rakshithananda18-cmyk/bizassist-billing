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

Startup default comes from the LLM_ROUTER env var; the admin endpoint
(POST /admin/router-mode) changes it live. In-memory by design — a restart
returns to the .env default, so a bad flip can never survive a reboot.
"""
import logging
import os
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
_explicit = None   # set ONLY via set_mode() (admin UI); wins over the env var


def _normalize(value: str):
    return _ALIASES.get((value or "").strip().lower())


def get_mode() -> str:
    """
    Current routing mode: 'off' (legacy) | 'shadow' | 'on' (new).
    Precedence: an explicit runtime set_mode() > the LLM_ROUTER env var.
    The env var is re-read on every call (cheap), so nothing is ever stale.
    """
    with _lock:
        if _explicit is not None:
            return _explicit
    return _normalize(os.getenv("LLM_ROUTER", "off")) or "off"


def set_mode(value: str) -> str:
    """
    Switch routing live. Accepts legacy/off, shadow, new/on/llm.
    Returns the canonical mode; raises ValueError on junk input.
    """
    global _explicit
    norm = _normalize(value)
    if norm is None:
        raise ValueError(
            f"invalid mode '{value}' — use one of: legacy, shadow, new")
    with _lock:
        old, _explicit = _explicit, norm
    logger.info(f"[ROUTER] mode switched: {_PRETTY.get(old) if old else 'env-default'} → {_PRETTY[norm]}")
    return norm


def reset_mode() -> None:
    """Clear the runtime override — fall back to the env default. (Tests/admin.)"""
    global _explicit
    with _lock:
        _explicit = None


def pretty(mode: str = None) -> str:
    """Human name for a mode ('off' → 'legacy', 'on' → 'new')."""
    return _PRETTY.get(mode or get_mode(), "legacy")
