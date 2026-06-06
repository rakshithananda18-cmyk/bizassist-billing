"""
routes/intents.py — Tier 0 / Tier 1 API.

  POST /intent       { intent, params?, session_id?, question? }
                       -> deterministic answer + suggestions (0 AI tokens),
                          persisted to chat history so it shows like any other turn.
  POST /suggestions  { context, params? }
                       -> just the next-step chips for a context (e.g. "upload").
"""
import uuid
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database.db import SessionLocal
from database.models import ChatMessage
from services.auth import get_active_user
from services.intents import resolve_intent
from services.recommendations import recommend

router = APIRouter()
logger = logging.getLogger("bizassist.intents")


class IntentRequest(BaseModel):
    intent: str
    params: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    question: Optional[str] = None


class SuggestRequest(BaseModel):
    context: str
    params: Optional[Dict[str, Any]] = None


def _persist_turn(user_id: int, session_id: str, question: str, answer_md: str,
                  source: str = None, model_tier: str = None, cached: bool = False) -> str:
    """Save the user question + deterministic answer to chat history. Returns the session title."""
    db = SessionLocal()
    try:
        existing = db.query(ChatMessage).filter(
            ChatMessage.business_id == user_id,
            ChatMessage.session_id == session_id,
        ).count()
        if existing == 0:
            title = question[:40] + ("..." if len(question) > 40 else "")
        else:
            first = db.query(ChatMessage).filter(
                ChatMessage.business_id == user_id,
                ChatMessage.session_id == session_id,
            ).order_by(ChatMessage.id.asc()).first()
            title = (first.session_title if first and first.session_title else "Conversation")

        db.add(ChatMessage(business_id=user_id, role="user", content=question,
                           session_id=session_id, session_title=title))
        db.add(ChatMessage(business_id=user_id, role="assistant", content=answer_md,
                           session_id=session_id, session_title=title,
                           source=source, model_tier=model_tier, cached=cached))
        db.commit()
        return title
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to persist intent turn: {e}", exc_info=True)
        return "Conversation"
    finally:
        db.close()


@router.post("/intent")
def run_intent(req: IntentRequest, current_user: dict = Depends(get_active_user)):
    user_id = current_user["id"]
    env = resolve_intent(req.intent, user_id, req.params)
    if env is None:
        raise HTTPException(status_code=404, detail=f"Unknown intent: {req.intent}")

    session_id = req.session_id or str(uuid.uuid4())
    question = (req.question or env["answer"]["title"]).strip()
    title = _persist_turn(user_id, session_id, question, env["answer"]["markdown"],
                          source=env.get("source"), model_tier=env.get("model_tier"), cached=env.get("cached", False))

    env["session_id"] = session_id
    env["session_title"] = title
    return env


@router.post("/suggestions")
def get_suggestions(req: SuggestRequest, current_user: dict = Depends(get_active_user)):
    return {"suggestions": recommend(req.context, current_user["id"])}
