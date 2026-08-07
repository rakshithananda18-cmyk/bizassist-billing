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


# ── Model defaults ───────────────────────────────────────────────────────────
# One definition, because the previous one was SEVEN copies of the same literal
# across six modules (ai_router_execution, agent_graph, llm_router,
# memory_service, column_mapper, purchase_ocr ×2). When a key lost access to
# that model the router, AI_SIMPLE, memory distillation, CSV column mapping and
# OCR all broke at once, and there was no single place to repair it — every fix
# was a six-file search-and-replace waiting to miss one.
#
# Observed 2026-08-07: `meta-llama/llama-4-scout-17b-16e-instruct` returns
#
#   404 — "The model does not exist or you do not have access to it"
#
# for a key that authenticates fine and serves `openai/gpt-oss-120b`,
# `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` without complaint. It is
# listed in the Groq console, so this is the "or you do not have access" half —
# a tier/entitlement gate, not a decommission. A default nobody can be sure of
# is the wrong default: this one is verified reachable and tool-calling capable,
# which AI_SIMPLE requires.
#
# Override per environment with GROQ_MODEL_SIMPLE / GROQ_MODEL_COMPLEX.
DEFAULT_TEXT_MODEL = "llama-3.3-70b-versatile"

# Vision is a SEPARATE capability — a text model cannot read an invoice image,
# and pointing this at one would turn a clear 404 into a confusing wrong answer.
# Left as the vision-capable model even though the key above cannot reach it:
# purchase_ocr collects and reports provider errors, so it fails legibly.
DEFAULT_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def make_groq_client(api_key: str = None):
    """Groq client with timeout + bounded retries. Falls back to a plain
    client if an old SDK doesn't accept the kwargs (never blocks boot).

    Groq is the ONLY provider. A `LLM_FALLBACK_ENABLED=1` hook used to wrap this
    in a Groq → Gemini/OpenAI chain; it was opt-in, the flag was never set in any
    environment, and it contradicted the stated architecture — so 334 lines of
    provider-shim plus its test are gone. If a second provider is ever wanted,
    that is a decision to make deliberately, not a dormant switch nobody has
    exercised."""
    key = api_key if api_key is not None else os.getenv("GROQ_API_KEY")
    try:
        base = Groq(api_key=key, timeout=GROQ_TIMEOUT_SECS, max_retries=GROQ_MAX_RETRIES)
    except TypeError:                                     # pragma: no cover
        logger.warning("[GROQ] SDK too old for timeout/max_retries kwargs — using defaults")
        base = Groq(api_key=key)

    return base
