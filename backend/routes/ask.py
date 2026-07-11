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


@router.post("/ask")
def ask_ai(prompt: Prompt, current_user: dict = Depends(restrict_cashier),
           _plan: dict = Depends(require_plan("pro"))):
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
                  _plan: dict = Depends(require_plan("pro"))):
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
        yield from handle_stream(
            prompt_message=prompt.message,
            session_id_in=prompt.session_id,
            current_user=current_user,
            client=_client,
        )

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
