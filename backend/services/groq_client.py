"""
services/groq_client.py — one place to construct Groq clients (REVIEW_1 GAP-3).
===============================================================================
Why: every module used to build its own `Groq(api_key=...)` with NO timeout.
LLM calls run in the server threadpool (sync routes / sync SSE generators —
Starlette moves both off the event loop automatically), so a hung upstream
call doesn't freeze the loop — but it DOES pin a threadpool slot forever.
Enough hung calls = thread starvation = the whole API stalls.

The fix is boring and effective: a hard client-side timeout + bounded retries
on every Groq client. Tune via env:

  GROQ_TIMEOUT_SECS  — per-request timeout (default 60; covers 70B synthesis)
  GROQ_MAX_RETRIES   — SDK-level retries on transient failures (default 1)
"""
import os
import logging

from groq import Groq

logger = logging.getLogger("bizassist.groq_client")

GROQ_TIMEOUT_SECS = float(os.getenv("GROQ_TIMEOUT_SECS", "60"))
GROQ_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "1"))


def make_groq_client(api_key: str = None):
    """Groq client with timeout + bounded retries. Falls back to a plain
    client if an old SDK doesn't accept the kwargs (never blocks boot).

    When `LLM_FALLBACK_ENABLED=1`, the client is transparently wrapped with a
    provider-fallback chain (Groq → Gemini/OpenAI) so a Groq outage can't kill
    the AI features (AI Phase 0 / REVIEW_2 §1). Default off = plain Groq client,
    identical to previous behaviour. The wrapper mirrors the same
    `.chat.completions.create()` surface, so no call site changes."""
    key = api_key if api_key is not None else os.getenv("GROQ_API_KEY")
    try:
        base = Groq(api_key=key, timeout=GROQ_TIMEOUT_SECS, max_retries=GROQ_MAX_RETRIES)
    except TypeError:                                     # pragma: no cover
        logger.warning("[GROQ] SDK too old for timeout/max_retries kwargs — using defaults")
        base = Groq(api_key=key)

    if os.getenv("LLM_FALLBACK_ENABLED", "0") == "1":
        try:
            from services.llm_provider import wrap_with_fallback
            return wrap_with_fallback(base)
        except Exception as e:                            # never break client construction
            logger.warning("[GROQ] fallback wrap failed (%s) — using plain Groq client", e)
    return base
