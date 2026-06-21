"""
core/api/period_lock.py — period close/lock HTTP layer (owner-only).
====================================================================
Lets an owner "close the books" through a date and lift it again. Cashiers are
blocked (`require_owner`). Every query is business_id-scoped. Enforcement of the
lock lives in `core/accounting/posting.post_entry`; these endpoints only manage
the lock/unlock event log.

  GET  /accounting/period-lock     current effective lock + full event history
  POST /accounting/period-lock     close the books through {through} (inclusive)
  POST /accounting/period-unlock   lift the current lock
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from services.auth import require_owner
from services.errors import ask_error
from core.accounting import period_lock

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.period_lock")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LockRequest(BaseModel):
    through: str               # inclusive YYYY-MM-DD
    note: Optional[str] = None


class UnlockRequest(BaseModel):
    note: Optional[str] = None


def _serialize(evt):
    return {
        "id": evt.id,
        "locked_through": evt.locked_through,
        "is_active": evt.is_active,
        "note": evt.note,
        "created_at": evt.created_at.isoformat() if evt.created_at else None,
    }


@router.get("/accounting/period-lock")
def get_period_lock(
    current_user: dict = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Current effective lock (None = open) plus the full lock/unlock history."""
    bid = current_user["id"]
    return {
        "locked_through": period_lock.effective_lock(db, bid),
        "history": [_serialize(e) for e in period_lock.lock_history(db, bid)],
    }


@router.post("/accounting/period-lock")
def set_period_lock(
    body: LockRequest,
    current_user: dict = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Close the books through `through` (inclusive YYYY-MM-DD)."""
    bid = current_user["id"]
    if not _DATE_RE.match(body.through or ""):
        raise ask_error(422, "bad_date", "`through` must be a YYYY-MM-DD date.")
    current = period_lock.effective_lock(db, bid)
    if current and body.through < current:
        # Moving the boundary *earlier* would re-open already-closed months.
        raise ask_error(
            409, "lock_regression",
            f"Books are already locked through {current}; cannot lock to an earlier date "
            f"({body.through}). Unlock first if you really need to re-open.",
            locked_through=current,
        )
    evt = period_lock.lock_period(db, business_id=bid, through=body.through, note=body.note)
    db.commit()
    db.refresh(evt)
    logger.info("[ACCT] period-lock set biz=%s through=%s", bid, body.through)
    return {"locked_through": body.through, "event": _serialize(evt)}


@router.post("/accounting/period-unlock")
def unset_period_lock(
    body: UnlockRequest,
    current_user: dict = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Lift the current lock (re-open the books)."""
    bid = current_user["id"]
    if not period_lock.effective_lock(db, bid):
        raise ask_error(409, "not_locked", "The books are not currently locked.")
    evt = period_lock.unlock_period(db, business_id=bid, note=body.note)
    db.commit()
    db.refresh(evt)
    logger.info("[ACCT] period-lock lifted biz=%s", bid)
    return {"locked_through": None, "event": _serialize(evt)}
