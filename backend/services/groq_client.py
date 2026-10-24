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
  GROQ_REASONING_EFFORT — how hard gpt-oss models think (default "low"; see below)
"""
import functools
import os
import logging
import threading
import time

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
# Groq retires models (console.groq.com/docs/deprecations), and a retired model
# answers 404 "does not exist or you do not have access to it" - for the
# retiree and for a model the key's project may not use alike:
#
#   meta-llama/llama-4-scout-17b-16e-instruct, qwen/qwen3-32b   off 2026-07-17
#   llama-3.3-70b-versatile                                       off 2026-08-16
#
# The last two were billing's defaults, so routing, AI_SIMPLE, CSV mapping,
# memory, bill-photo OCR and bill-text extraction all failed until overridden.
# Checked 2026-10-24 with the production key (answer, tool call, JSON mode,
# six Indian bills, billing's own router, a bill photo):
#
#   qwen/qwen3.8-27b     fast; tool calls and JSON; billing's router 8/8 as is;
#                        the only model reachable that reads images
#   openai/gpt-oss-120b  most accurate (6/6 Indian dates and amounts); a
#                        reasoning model, so it needs a token budget it can think
#                        in - see _tuned below
#
# Every model setting is a comma-separated list, first choice first; when Groq
# refuses one as gone, calls move to the next (see "Backup models" below). Each
# default lists the other checked model as its backup. Override per environment
# with GROQ_MODEL_SIMPLE / GROQ_MODEL_COMPLEX / GROQ_MODEL_ROUTER /
# GROQ_VISION_MODEL; a dead default is then one edit here.
DEFAULT_TEXT_MODEL = "qwen/qwen3.8-27b,openai/gpt-oss-120b"

# Harder questions, the agent loop, insights, PDF and bill-text extraction:
# where a misread amount or date costs money.
DEFAULT_COMPLEX_MODEL = "openai/gpt-oss-120b,qwen/qwen3.8-27b"

# Vision is a SEPARATE capability — a text model cannot read an invoice image,
# and pointing this at one would turn a clear 404 into a confusing wrong answer.
# So no backup: no other model the key reaches reads images.
DEFAULT_VISION_MODEL = "qwen/qwen3.8-27b"


# ── Reasoning models (gpt-oss) ───────────────────────────────────────────────
# gpt-oss thinks before it answers, and the thinking counts against the call's
# token budget. Billing's quick calls were sized for non-reasoning models
# (80-300 tokens: router, AI_SIMPLE, CSV mapping, planner), so gpt-oss ran out
# before finishing - "max completion tokens reached before generating a valid
# document" - on half the router's questions. Every call to one therefore gets
# `reasoning_effort` (low unless the call or GROQ_REASONING_EFFORT says
# otherwise) and at least MIN_REASONING_TOKENS of room. Low thinking answered
# the router 8/8 in ~100 tokens, and leaves the free plan's tokens-per-minute
# for more questions. Only the limit is raised: unused room costs nothing.
REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low")
MIN_REASONING_TOKENS = 1024


def is_reasoning_model(model) -> bool:
    return str(model or "").startswith("openai/gpt-oss")


def _tuned(kwargs: dict) -> dict:
    """The call's arguments, with room to think when the model is gpt-oss."""
    if not is_reasoning_model(kwargs.get("model")):
        return kwargs
    kwargs = dict(kwargs)
    kwargs.setdefault("reasoning_effort", REASONING_EFFORT)
    for key in ("max_tokens", "max_completion_tokens"):
        if kwargs.get(key) is not None and kwargs[key] < MIN_REASONING_TOKENS:
            kwargs[key] = MIN_REASONING_TOKENS
    return kwargs


# ── Backup models ────────────────────────────────────────────────────────────
# A model setting may list backups: "qwen/qwen3.8-27b,openai/gpt-oss-120b".
# When Groq refuses a model as gone - 404 "does not exist or you do not have
# access", or 400 "model_decommissioned" - the call is repeated on the next one
# and the refused model is skipped for GONE_RECHECK_SECS (one warning, not one
# per call), then tried again in case access comes back. Anything else (429,
# timeouts, bad requests) is not about the model and is raised as before. When
# every model in the list is refused, the last refusal is raised unchanged, so
# callers that react to it (purchase_ocr's vision latch) still see a 404.
GONE_RECHECK_SECS = 3600
_gone: dict = {}            # model -> time.monotonic() when Groq refused it
_gone_lock = threading.Lock()


def model_candidates(setting) -> list:
    """The models in a setting, first choice first."""
    return [m.strip() for m in str(setting or "").split(",") if m.strip()]


def _is_gone(model) -> bool:
    refused_at = _gone.get(model)
    return refused_at is not None and time.monotonic() - refused_at < GONE_RECHECK_SECS


def model_in_use(setting) -> str:
    """The model a setting answers with now: its first model Groq has not
    refused. For reports and usage records, which want one model's name."""
    candidates = model_candidates(setting)
    for model in candidates:
        if not _is_gone(model):
            return model
    return candidates[0] if candidates else str(setting or "")


def _refused_as_gone(exc) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 404:
        return True
    # Groq's error code is a field of its own, not part of the message text.
    return status == 400 and (getattr(exc, "code", None) == "model_decommissioned"
                              or "decommissioned" in str(exc).lower())


def _mark_gone(model: str, exc, backup) -> None:
    with _gone_lock:
        already = _is_gone(model)
        _gone[model] = time.monotonic()
    if already:
        return
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    reason = str((body.get("message") if isinstance(body, dict) else None) or exc)[:160]
    if backup:
        logger.warning("[GROQ] Groq refused model '%s' (%s). Using backup '%s' for the next %d min. "
                       "Groq may have retired it (console.groq.com/docs/deprecations) - replace it in "
                       "the GROQ_MODEL_* setting.", model, reason, backup, GONE_RECHECK_SECS // 60)
    else:
        logger.warning("[GROQ] Groq refused model '%s' (%s) and no backup model is left in its setting. "
                       "Groq may have retired it (console.groq.com/docs/deprecations).", model, reason)


def _wrap_create(create):
    """chat.completions.create with backup models and room for gpt-oss."""
    @functools.wraps(create)
    def call(*args, **kwargs):
        candidates = model_candidates(kwargs.get("model"))
        if not candidates:
            return create(*args, **kwargs)
        to_try = [m for m in candidates if not _is_gone(m)] or candidates
        for i, model in enumerate(to_try):
            try:
                return create(*args, **_tuned({**kwargs, "model": model}))
            except Exception as exc:
                if not _refused_as_gone(exc):
                    raise
                backup = to_try[i + 1] if i + 1 < len(to_try) else None
                _mark_gone(model, exc, backup)
                if backup is None:
                    raise
    return call


def make_groq_client(api_key: str = None):
    """Groq client with timeout + bounded retries. Falls back to a plain
    client if an old SDK doesn't accept the kwargs (never blocks boot).

    Groq is the ONLY provider. A `LLM_FALLBACK_ENABLED=1` hook used to wrap this
    in a Groq → Gemini/OpenAI chain; it was opt-in, the flag was never set in any
    environment, and it contradicted the stated architecture — so 334 lines of
    provider-shim plus its test are gone. If a second provider is ever wanted,
    that is a decision to make deliberately, not a dormant switch nobody has
    exercised.

    Its `chat.completions.create` takes a model LIST and moves to the next
    model when Groq refuses one as gone, and gives reasoning models (gpt-oss) a
    thinking level and enough tokens - whichever module makes the call."""
    key = api_key if api_key is not None else os.getenv("GROQ_API_KEY")
    try:
        base = Groq(api_key=key, timeout=GROQ_TIMEOUT_SECS, max_retries=GROQ_MAX_RETRIES)
    except TypeError:                                     # pragma: no cover
        logger.warning("[GROQ] SDK too old for timeout/max_retries kwargs — using defaults")
        base = Groq(api_key=key)

    completions = base.chat.completions
    completions.create = _wrap_create(completions.create)
    return base
