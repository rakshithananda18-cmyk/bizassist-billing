"""
routers/requests.py — what the shop asked for: an order note or a product
requirement list, captured at the shop (with location) by the field agent.

Manual item names today. The planned bridge to BizAssist Billing: pick items
from the owner's catalogue and convert an acknowledged request into a B2B
order / sale draft there (docs/FIELD_TEAM_MASTER_PLAN.md §Ecosystem).
"""
from __future__ import annotations

import json
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.geo import GeoFix, validate_fix
from app.models import FieldItemRequest, FieldRunStop, FieldShop
from app.routers.attendance import require_checked_in
from app.security import Principal, get_settings, require_owner, require_staff
from app.services import get_scoped, item_request_out, log_activity, record_fix

router = APIRouter(prefix="/api", tags=["requests"])


class ItemIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    qty: float = Field(..., gt=0, le=100000)
    unit: Optional[str] = Field(None, max_length=20)
    note: Optional[str] = Field(None, max_length=200)


class RequestIn(BaseModel):
    geo: GeoFix
    shop_id: int
    run_stop_id: Optional[int] = None
    kind: Literal["requirement", "order"] = "requirement"
    items: List[ItemIn] = Field(..., min_length=1, max_length=200)
    note: Optional[str] = Field(None, max_length=1000)


@router.post("/requests", status_code=201)
def create_request(req: RequestIn, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    settings = get_settings(db, p.business_id)
    fix = validate_fix(req.geo, settings.max_accuracy_m)
    require_checked_in(db, p.staff)
    shop = get_scoped(db, FieldShop, p.business_id, req.shop_id, "Shop")
    if req.run_stop_id is not None:
        stop = get_scoped(db, FieldRunStop, p.business_id, req.run_stop_id, "Stop")
        if stop.shop_id != shop.id:
            raise HTTPException(status_code=422, detail="Stop and shop do not match")
    row = FieldItemRequest(
        business_id=p.business_id, shop_id=shop.id, staff_id=p.staff.id, run_stop_id=req.run_stop_id,
        kind=req.kind, items_json=json.dumps([i.model_dump() for i in req.items]),
        note=(req.note or "").strip() or None, lat=fix.lat, lng=fix.lng, accuracy_m=fix.accuracy,
    )
    db.add(row)
    db.flush()
    record_fix(db, p.staff, fix, event="request")
    log_activity(db, p, "request.create", entity="item_request", entity_id=row.id,
                 summary=f"{shop.name} · {len(req.items)} item(s)", fix=fix)
    db.commit()
    db.refresh(row)
    return item_request_out(row)


@router.get("/requests")
def list_requests(status: Optional[str] = None, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    q = db.query(FieldItemRequest).filter(FieldItemRequest.business_id == p.business_id)
    if status:
        q = q.filter(FieldItemRequest.status == status)
    return [item_request_out(r) for r in q.order_by(FieldItemRequest.id.desc()).limit(300).all()]


@router.get("/my/requests")
def my_requests(p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    rows = (db.query(FieldItemRequest)
            .filter(FieldItemRequest.business_id == p.business_id, FieldItemRequest.staff_id == p.staff.id)
            .order_by(FieldItemRequest.id.desc()).limit(50).all())
    return [item_request_out(r) for r in rows]


class RequestStatus(BaseModel):
    status: Literal["new", "acknowledged", "fulfilled", "closed"]


@router.patch("/requests/{request_id}")
def set_request_status(request_id: int, req: RequestStatus, p: Principal = Depends(require_owner),
                       db: Session = Depends(get_db)):
    row = get_scoped(db, FieldItemRequest, p.business_id, request_id, "Request")
    row.status = req.status
    log_activity(db, p, "request.status", entity="item_request", entity_id=row.id, summary=req.status)
    db.commit()
    return item_request_out(row)
