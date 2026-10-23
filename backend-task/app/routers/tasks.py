"""
routers/tasks.py — tasks: owner assigns, staff completes on site for points.

Completion rules (server-enforced):
  * staff must be checked in, with a GPS fix within the accuracy limit;
  * a task on a route stop needs the stop's arrival marked first, so the work
    is tied to being at the shop;
  * on-time vs late is decided by SERVER completion time vs `due_at`;
  * points go to the append-only ledger (app/services.award_task_points).

A task can carry billing invoices (`invoice_ids`, app/invoices.py): their
numbers, boxes and amount due fill whatever the owner left blank.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db, utc_now
from app.geo import GeoFix, distance_to, validate_fix
from app.invoices import MAX_PER_TASK, attach_invoices, ensure_not_planned, resolve_invoices
from app.models import FieldRun, FieldRunStop, FieldShop, FieldTask
from app.routers.attendance import require_checked_in
from app.routers.runs import _check_task_type, maybe_complete_run, maybe_complete_stop
from app.security import Principal, get_settings, require_owner, require_staff
from app.services import award_task_points, get_scoped, log_activity, optional_staff, record_fix, task_out
from app.timeutil import biz_local_to_utc, day_bounds_utc

router = APIRouter(prefix="/api", tags=["tasks"])


class TaskIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    task_type: str = "general"
    description: Optional[str] = Field(None, max_length=1000)
    staff_id: int
    shop_id: Optional[int] = None
    due_date: Optional[str] = Field(None, description="YYYY-MM-DD business date")
    due_time: Optional[str] = Field(None, description="HH:MM business time")
    points: Optional[int] = Field(None, ge=0, le=1000)
    boxes_planned: Optional[int] = Field(None, ge=0, le=10000)
    orders_count: Optional[int] = Field(None, ge=0, le=1000)
    reference: Optional[str] = Field(None, max_length=200)
    amount_expected: Optional[float] = Field(None, ge=0)
    invoice_ids: List[int] = Field(default_factory=list, max_length=MAX_PER_TASK,
                                   description="Billing invoices of the shop's linked customer")


def _due(due_date: Optional[str], due_time: Optional[str]) -> Optional[datetime]:
    if not due_date:
        return None
    try:
        return biz_local_to_utc(due_date, due_time or "23:59")
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="Due date must be YYYY-MM-DD and time HH:MM")


@router.post("/tasks", status_code=201)
def create_task(req: TaskIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    staff = optional_staff(db, p.business_id, req.staff_id)
    shop = get_scoped(db, FieldShop, p.business_id, req.shop_id, "Shop") if req.shop_id is not None else None
    task_type = _check_task_type(req.task_type)
    invoices = resolve_invoices(db, p.business_id, shop, req.invoice_ids)
    ensure_not_planned(db, p.business_id, task_type, invoices)
    settings = get_settings(db, p.business_id)
    task = FieldTask(
        business_id=p.business_id,
        task_type=task_type,
        title=req.title.strip(),
        description=req.description,
        staff_id=staff.id,
        shop_id=req.shop_id,
        due_at=_due(req.due_date, req.due_time),
        points=req.points if req.points is not None else settings.default_task_points,
        boxes_planned=req.boxes_planned,
        orders_count=req.orders_count,
        reference=req.reference,
        amount_expected=req.amount_expected,
        created_by=p.actor,
    )
    attach_invoices(db, task, invoices)
    db.add(task)
    db.flush()
    log_activity(db, p, "task.create", entity="task", entity_id=task.id, summary=f"{task.title} → {staff.name}")
    db.commit()
    db.refresh(task)
    return task_out(task)


@router.get("/tasks")
def list_tasks(
    status: Optional[Literal["pending", "done", "cancelled", "overdue"]] = None,
    staff_id: Optional[int] = None,
    day: Optional[str] = Query(None, description="due on this business date"),
    p: Principal = Depends(require_owner),
    db: Session = Depends(get_db),
):
    q = db.query(FieldTask).filter(FieldTask.business_id == p.business_id)
    if status == "overdue":
        q = q.filter(FieldTask.status == "pending", FieldTask.due_at.isnot(None), FieldTask.due_at < utc_now())
    elif status:
        q = q.filter(FieldTask.status == status)
    if staff_id is not None:
        q = q.filter(FieldTask.staff_id == staff_id)
    if day:
        try:
            start, end = day_bounds_utc(day)
        except ValueError:
            raise HTTPException(status_code=422, detail="day must be YYYY-MM-DD")
        q = q.filter(FieldTask.due_at >= start, FieldTask.due_at < end)
    rows = q.order_by(FieldTask.due_at.is_(None), FieldTask.due_at.asc(), FieldTask.id.desc()).limit(500).all()
    return [task_out(t) for t in rows]


class TaskPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)
    staff_id: Optional[int] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    points: Optional[int] = Field(None, ge=0, le=1000)
    boxes_planned: Optional[int] = Field(None, ge=0, le=10000)
    orders_count: Optional[int] = Field(None, ge=0, le=1000)
    reference: Optional[str] = Field(None, max_length=200)
    amount_expected: Optional[float] = Field(None, ge=0)
    status: Optional[Literal["cancelled", "pending"]] = None


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, req: TaskPatch, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    task = get_scoped(db, FieldTask, p.business_id, task_id, "Task")
    if task.status == "done":
        raise HTTPException(status_code=409, detail="Completed tasks are part of the points ledger and cannot be edited")
    data = req.model_dump(exclude_unset=True)
    if "staff_id" in data:
        task.staff_id = optional_staff(db, p.business_id, data.pop("staff_id")).id
    if "due_date" in data or "due_time" in data:
        task.due_at = _due(data.pop("due_date", None), data.pop("due_time", None))
    for k, v in data.items():
        setattr(task, k, v.strip() if isinstance(v, str) and k == "title" else v)
    log_activity(db, p, "task.update", entity="task", entity_id=task.id, summary=", ".join(sorted(req.model_dump(exclude_unset=True))))
    if task.run_stop_id:
        stop = db.query(FieldRunStop).filter(FieldRunStop.id == task.run_stop_id).first()
        db.flush()
        db.refresh(stop)
        maybe_complete_stop(stop)
        run = db.query(FieldRun).filter(FieldRun.id == stop.run_id).first()
        maybe_complete_run(run)
    db.commit()
    db.refresh(task)
    return task_out(task)


@router.get("/my/tasks")
def my_tasks(
    status: Optional[Literal["pending", "done"]] = "pending",
    p: Principal = Depends(require_staff),
    db: Session = Depends(get_db),
):
    q = db.query(FieldTask).filter(FieldTask.business_id == p.business_id, FieldTask.staff_id == p.staff.id)
    if status:
        q = q.filter(FieldTask.status == status)
    rows = q.order_by(FieldTask.due_at.is_(None), FieldTask.due_at.asc(), FieldTask.id.asc()).limit(300).all()
    return [task_out(t) for t in rows]


class CompleteBody(BaseModel):
    geo: GeoFix
    note: Optional[str] = Field(None, max_length=1000)
    boxes_delivered: Optional[int] = Field(None, ge=0, le=10000)
    amount_collected: Optional[float] = Field(None, ge=0)


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: int, body: CompleteBody, p: Principal = Depends(require_staff),
                  db: Session = Depends(get_db)):
    settings = get_settings(db, p.business_id)
    fix = validate_fix(body.geo, settings.max_accuracy_m)
    require_checked_in(db, p.staff)
    task = get_scoped(db, FieldTask, p.business_id, task_id, "Task")
    if task.staff_id != p.staff.id:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "pending":
        raise HTTPException(status_code=409, detail=f"Task is already {task.status}")

    stop = run = None
    if task.run_stop_id:
        stop = db.query(FieldRunStop).filter(FieldRunStop.id == task.run_stop_id).first()
        run = db.query(FieldRun).filter(FieldRun.id == stop.run_id).first()
        if run.status == "cancelled":
            raise HTTPException(status_code=409, detail="This run was cancelled by the owner")
        if stop.status != "arrived":
            raise HTTPException(status_code=409, detail=f"Mark arrival at {stop.shop.name} first")

    if task.task_type == "delivery":
        if body.boxes_delivered is None:
            raise HTTPException(status_code=422, detail="Enter the number of boxes delivered")
        task.boxes_delivered = body.boxes_delivered
    if task.task_type == "payment_collect":
        if body.amount_collected is None:
            raise HTTPException(status_code=422, detail="Enter the amount collected (0 if nothing)")
        task.amount_collected = body.amount_collected

    shop = task.shop
    task.status = "done"
    task.completed_at = utc_now()
    task.completed_lat, task.completed_lng, task.completed_accuracy_m = fix.lat, fix.lng, fix.accuracy
    task.completion_distance_m = distance_to(shop.lat, shop.lng, fix) if shop else None
    task.completion_note = (body.note or "").strip() or None
    db.flush()
    pts = award_task_points(db, task, settings)
    record_fix(db, p.staff, fix, event="task_done")
    log_activity(db, p, "task.complete", entity="task", entity_id=task.id,
                 summary=f"{task.title} · {'on time' if task.on_time else 'late'} · +{pts}", fix=fix)
    if stop is not None:
        db.refresh(stop)
        maybe_complete_stop(stop)
        maybe_complete_run(run)
    db.commit()
    db.refresh(task)
    return task_out(task)
