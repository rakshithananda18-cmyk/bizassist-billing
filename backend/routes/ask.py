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
from groq import Groq
import os

from services.auth import get_active_user

router = APIRouter()

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class Prompt(BaseModel):
    message: str
    user_id: Optional[int] = None
    session_id: Optional[str] = None


@router.get("/")
def home():
    return {"message": "BizAssist AI server running"}


@router.post("/ask")
def ask_ai(prompt: Prompt, current_user: dict = Depends(get_active_user)):
    """
    Hybrid AI endpoint -- 4-tier routing:
      CONVERSATIONAL -> short reply, 0 tokens
      DIRECT         -> DB only, 0 tokens
      CACHE          -> cached response, 0 tokens
      AI_SIMPLE/COMPLEX -> Groq LLM
    """
    from services.ai_router import handle
    return handle(
        prompt_message=prompt.message,
        session_id_in=prompt.session_id,
        current_user=current_user,
        client=_client,
    )


@router.post("/ask/stream")
def ask_ai_stream(prompt: Prompt, current_user: dict = Depends(get_active_user)):
    """
    SSE streaming endpoint -- same routing logic as /ask but streams tokens.

    DIRECT/CACHE/CONVERSATIONAL: single 'replace' event (instant, 0 tokens).
    AI_SIMPLE:  streams final LLM response after optional tool call.
    AI_COMPLEX: streams synthesizer output with agent 'status' events first.

    Event format:  data: {"type": "...", ...}\\n\\n
    Types: status | token | replace | done | error
    """
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
