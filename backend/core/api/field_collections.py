"""
core/api/field_collections.py — Contacts & Payments → Field collections.

GET  /field-collections                    collections waiting for the owner
POST /field-collections/{task_uid}/confirm record them as payments (owner only)

The logic lives in core/field_team.py; this is the HTTP shell.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core import field_team
from database.db import get_db
from services.auth import require_owner
from services.realtime import realtime_manager

logger = logging.getLogger("bizassist.field_collections")
router = APIRouter()


@router.get("/field-collections")
def list_field_collections(current_user: dict = Depends(require_owner), db: Session = Depends(get_db)):
    if not field_team.available(db):
        return {"available": False, "collections": []}
    return {"available": True, "collections": field_team.pending_collections(db, current_user["id"])}


class Allocation(BaseModel):
    invoice_id: int
    amount: float = Field(..., ge=0)


class ConfirmRequest(BaseModel):
    allocations: List[Allocation] = Field(..., min_length=1, max_length=100)
    expected_confirmed: Optional[float] = Field(None, ge=0, allow_inf_nan=False)


@router.post("/field-collections/{task_uid}/confirm")
def confirm_field_collection(task_uid: str, req: ConfirmRequest, background_tasks: BackgroundTasks,
                             current_user: dict = Depends(require_owner), db: Session = Depends(get_db)):
    if not field_team.available(db):
        raise HTTPException(status_code=404, detail="Field Team collections are only in the cloud app")
    bid = current_user["id"]
    try:
        out = field_team.confirm_collection(db, bid, task_uid, [a.model_dump() for a in req.allocations],
                                            expected_confirmed=req.expected_confirmed)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except field_team.CollectionChangedError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(e))
    logger.info("[PAYMENT] field collection %s confirmed biz=%s bills=%s total=%s",
                task_uid, bid, len(out["recorded"]), out["confirmed_total"])
    background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "payment"})
    return out
