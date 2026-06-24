"""
routes/actions.py — Tier 3 API (gated agentic actions).

  POST /action/preview  { action, params? }
                          -> what WOULD happen, no side effects. Shown in a
                             confirm modal before anything runs.
  POST /action/execute  { action, params?, session_id? }
                          -> performs the action, writes an audit row per item,
                             and records the result in chat history.

Nothing executes without an explicit confirm from the client.
"""
import uuid
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import get_active_user, restrict_cashier
from services.actions import preview as action_preview, execute as action_execute
from routes.intents import _persist_turn
from sqlalchemy.orm import Session
from database.db import get_db
from database.models import ActionLog

router = APIRouter()
logger = logging.getLogger("bizassist.actions")


class ActionRequest(BaseModel):
    action: str
    params: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    question: Optional[str] = None


@router.post("/action/preview")
def preview_action(req: ActionRequest, current_user: dict = Depends(restrict_cashier)):
    result = action_preview(req.action, current_user["id"], req.params)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {req.action}")
    return result


@router.post("/action/execute")
def execute_action(req: ActionRequest, current_user: dict = Depends(restrict_cashier)):
    user_id = current_user["id"]
    result = action_execute(req.action, user_id, req.params)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {req.action}")

    # Record the action result as a chat turn so it shows in history.
    session_id = req.session_id or str(uuid.uuid4())
    question = (req.question or "Send payment reminders").strip()
    title = _persist_turn(user_id, session_id, question, result.get("markdown", ""), source="db")
    # Wrap in unified response envelope
    markdown = result.get("markdown", "")
    return {
        "answer":       {"markdown": markdown, "title": question},
        "response":     markdown,       # backward-compat
        "source":       "action",
        "suggestions":  [],
        "session_id":   session_id,
        "session_title": title,
        "meta":         {"tokens": 0, "model": None, "cached": False},
        **{k: v for k, v in result.items() if k not in ("markdown",)},
    }


@router.get("/action/history")
def action_history(
    limit: int = 100,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Audit trail of executed actions, newest first."""
    rows = (
        db.query(ActionLog)
        .filter(ActionLog.business_id == current_user["id"])
        .order_by(ActionLog.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    return {"items": [{
        "id": r.id,
        "action": r.action,
        "target": r.target,
        "amount": r.amount,
        "detail": r.detail,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]}
