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
#                        in - see _tuned_for_reasoning below
#
# Override per environment with GROQ_MODEL_SIMPLE / GROQ_MODEL_COMPLEX /
# GROQ_MODEL_ROUTER / GROQ_VISION_MODEL; a dead default is then one edit here.
DEFAULT_TEXT_MODEL = "qwen/qwen3.8-27b"

# Harder questions, the agent loop, insights, PDF and bill-text extraction:
# where a misread amount or date costs money.
DEFAULT_COMPLEX_MODEL = "openai/gpt-oss-120b"

# Vision is a SEPARATE capability — a text model cannot read an invoice image,
# and pointing this at one would turn a clear 404 into a confusing wrong answer.
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


def _tuned_for_reasoning(create):
    @functools.wraps(create)
    def call(*args, **kwargs):
        if is_reasoning_model(kwargs.get("model")):
            kwargs.setdefault("reasoning_effort", REASONING_EFFORT)
            for key in ("max_tokens", "max_completion_tokens"):
                if kwargs.get(key) is not None and kwargs[key] < MIN_REASONING_TOKENS:
                    kwargs[key] = MIN_REASONING_TOKENS
        return create(*args, **kwargs)
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

    Its `chat.completions.create` gives reasoning models (gpt-oss) a thinking
    level and enough tokens, whichever module makes the call."""
    key = api_key if api_key is not None else os.getenv("GROQ_API_KEY")
    try:
        base = Groq(api_key=key, timeout=GROQ_TIMEOUT_SECS, max_retries=GROQ_MAX_RETRIES)
    except TypeError:                                     # pragma: no cover
        logger.warning("[GROQ] SDK too old for timeout/max_retries kwargs — using defaults")
        base = Groq(api_key=key)

    completions = base.chat.completions
    completions.create = _tuned_for_reasoning(completions.create)
    return base
