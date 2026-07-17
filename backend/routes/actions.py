"""
routes/actions.py — Tier 3 API (gated agentic actions).

  POST /action/preview  { action, params? }
                          -> what WOULD happen, no side effects. Shown in a
                             confirm modal before anything runs.
  POST /action/execute  { action, params?, session_id?, confirm_token }
                          -> performs the action, writes an audit row per item,
                             and records the result in chat history.

Nothing executes without an explicit confirm from the client.

Phase-0 write rails (MASTER_REVIEW §3.2 #4, services/action_rails.py):
  * preview mints a `confirm_token` binding (business, action, exact params,
    10-min expiry); execute refuses without a valid one (403). Disable only
    for a mixed-version fleet with ACTION_CONFIRM_REQUIRED=0.
  * execute honours `X-Client-Request-Id` via the ReplayGuard wall — a
    double-clicked confirm replays the stored response, never re-executes.
  * a per-business daily cap per action is enforced in the dispatcher (429).
"""
import uuid
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import get_active_user, restrict_cashier
from services.actions import preview as action_preview, execute as action_execute
from services.action_rails import mint_confirm_token, verify_confirm_token, confirm_required
from core.sync.idempotency import ReplayGuard, replay_guard
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
    confirm_token: Optional[str] = None


@router.post("/action/preview")
def preview_action(req: ActionRequest, current_user: dict = Depends(restrict_cashier)):
    result = action_preview(req.action, current_user["id"], req.params)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {req.action}")
    # Write rail #1: bind this preview to (business, action, exact params).
    result["confirm_token"] = mint_confirm_token(current_user["id"], req.action, req.params)
    return result


@router.post("/action/execute")
def execute_action(req: ActionRequest,
                   current_user: dict = Depends(restrict_cashier),
                   guard: ReplayGuard = Depends(replay_guard)):
    user_id = current_user["id"]

    # Write rail #1: only a previewed (business, action, params) may execute.
    if confirm_required():
        ok, reason = verify_confirm_token(req.confirm_token, user_id, req.action, req.params)
        if not ok:
            logger.warning(f"[ACTION] execute refused biz={user_id} action={req.action}: confirm token {reason}")
            # 428 (not 403): this is a missing precondition — preview first —
            # not a role/permission block, which the role tests assert on 403.
            raise HTTPException(status_code=428,
                                detail=f"Action not confirmed (token {reason}). Preview it again and confirm.")

    # Write rail #2: replay wall — a retried/double-fired confirm must not re-execute.
    hit = guard.replay()
    if hit is not None:
        return hit

    result = action_execute(req.action, user_id, req.params)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {req.action}")
    if result.get("error") == "daily_cap_reached":
        # Write rail #3 (enforced in the dispatcher): surface as 429, not a silent no-op.
        raise HTTPException(status_code=429, detail=result.get("markdown", "Daily action cap reached."))

    # Record the action result as a chat turn so it shows in history.
    session_id = req.session_id or str(uuid.uuid4())
    question = (req.question or "Send payment reminders").strip()
    title = _persist_turn(user_id, session_id, question, result.get("markdown", ""), source="db")
    # Wrap in unified response envelope
    markdown = result.get("markdown", "")
    return guard.store({
        "answer":       {"markdown": markdown, "title": question},
        "response":     markdown,       # backward-compat
        "source":       "action",
        "suggestions":  [],
        "session_id":   session_id,
        "session_title": title,
        "meta":         {"tokens": 0, "model": None, "cached": False},
        **{k: v for k, v in result.items() if k not in ("markdown",)},
    })


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
