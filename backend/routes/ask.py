"""
routes/ask.py
=============
Thin FastAPI endpoints for POST /ask and POST /ask/stream.

All routing and business logic lives in services/ai_router.py.
This file is intentionally minimal -- HTTP concerns only.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import os
import queue
import threading

# How long a stream may stay silent before a comment frame is sent. Well under
# the 60 s idle timeout common to reverse proxies, and far cheaper than the
# alternative — a working request killed mid-answer.
_HEARTBEAT_SECS = int(os.getenv("SSE_HEARTBEAT_SECS", "15"))

from services.auth import get_active_user, restrict_cashier, require_plan
from services.groq_client import make_groq_client

router = APIRouter()

# Optional: desktop installs may ship without an AI key — the app must still
# boot (Groq() raises at construction when api_key is None). AI endpoints
# return 503 below; billing/POS is unaffected.
# NOTE: these routes are sync `def` and the SSE generator is a sync generator —
# Starlette runs BOTH in its threadpool, so LLM latency never blocks the event
# loop. The groq_client timeout keeps a hung upstream call from pinning a
# threadpool slot forever (REVIEW_1 GAP-3 part 1).
_GROQ_KEY = os.getenv("GROQ_API_KEY")
_client = make_groq_client(_GROQ_KEY) if _GROQ_KEY else None


def _require_ai_client():
    if _client is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="AI features aren't configured on this device. "
                   "Add GROQ_API_KEY to the app's .env (or use cloud mode) and restart.",
        )


class Prompt(BaseModel):
    message: str
    user_id: Optional[int] = None
    session_id: Optional[str] = None


@router.get("/")
def home():
    return {"message": "BizAssist AI server running"}


# ── Pro gate, ENFORCED ───────────────────────────────────────────────────────
# `require_plan("pro")` alone is a no-op: it only bites when SUBSCRIPTION_ENFORCED=1,
# which is unset in production. So both endpoints below have CARRIED a Pro
# declaration that never once refused anyone — the AI has been free to every
# plan while the code read as though it were not.
#
# `force_enforcement=True` makes the existing declaration true without flipping
# the site-wide paywall, which stays a separate, deliberate decision (it would
# also gate /api/sync/push and the data-transfer import).
#
# THIS IS A LIVE BEHAVIOUR CHANGE: a free-plan business that was using the AI
# chat now gets 402 with no grace period. Checked before enabling — every
# business with chat history resolves to Pro (`plan='pro'`, no expiry), so the
# measured impact is nobody. Note `effective_plan` downgrades an EXPIRED Pro to
# free, so a lapsed subscription is refused too; that is the intent.
@router.post("/ask")
def ask_ai(prompt: Prompt, current_user: dict = Depends(restrict_cashier),
           _plan: dict = Depends(require_plan("pro", force_enforcement=True))):
    """
    Hybrid AI endpoint -- 4-tier routing:
      CONVERSATIONAL -> short reply, 0 tokens
      DIRECT         -> DB only, 0 tokens
      CACHE          -> cached response, 0 tokens
      AI_SIMPLE/COMPLEX -> Groq LLM
    """
    _require_ai_client()
    from services.ai_router import handle
    return handle(
        prompt_message=prompt.message,
        session_id_in=prompt.session_id,
        current_user=current_user,
        client=_client,
    )


@router.post("/ask/stream")
def ask_ai_stream(prompt: Prompt, current_user: dict = Depends(restrict_cashier),
                  _plan: dict = Depends(require_plan("pro", force_enforcement=True))):
    """
    SSE streaming endpoint -- same routing logic as /ask but streams tokens.

    DIRECT/CACHE/CONVERSATIONAL: single 'replace' event (instant, 0 tokens).
    AI_SIMPLE:  streams final LLM response after optional tool call.
    AI_COMPLEX: streams synthesizer output with agent 'status' events first.

    Event format:  data: {"type": "...", ...}\\n\\n
    Types: status | token | replace | done | error
    """
    _require_ai_client()
    from services.ai_router import handle_stream

    def generator():
        # ── Heartbeat ────────────────────────────────────────────────────────
        # An agent run is legitimately silent for long stretches: the LLM router
        # call, then up to AGENT_MAX_TOOL_ROUNDS model calls at GROQ_TIMEOUT_SECS
        # each. Nothing crossed the wire between them, so any intermediary with
        # an idle timeout — the HF Space's proxy included — was free to drop a
        # connection that was still working. The client then saw its reader
        # finish with no `done` event and spun forever.
        #
        # A comment frame (`: …`) is the SSE no-op: it keeps the connection warm
        # and every parser ignores it, including the `data: ` check in Chat.jsx.
        #
        # The pipeline is a BLOCKING generator, so it cannot be interleaved with
        # a timer directly — iterating it parks this thread inside next() for the
        # whole quiet period, which is exactly when a heartbeat is needed. Hence
        # the worker thread: it feeds a queue, and this side polls with a
        # timeout, emitting a beat whenever the queue is empty.
        q: "queue.Queue" = queue.Queue(maxsize=64)
        _DONE = object()

        def _pump():
            try:
                for chunk in handle_stream(
                    prompt_message=prompt.message,
                    session_id_in=prompt.session_id,
                    current_user=current_user,
                    client=_client,
                ):
                    q.put(chunk)
            except BaseException as exc:          # noqa: BLE001 — re-raised below
                q.put(exc)
            finally:
                q.put(_DONE)

        threading.Thread(target=_pump, name="ask-stream", daemon=True).start()

        while True:
            try:
                item = q.get(timeout=_HEARTBEAT_SECS)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if item is _DONE:
                return
            if isinstance(item, BaseException):
                # handle_stream already converts failures into `error` events;
                # anything reaching here escaped it, and must not be swallowed
                # into silence — that is the bug this endpoint is being fixed for.
                raise item
            yield item

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
