"""
routers/runs.py — the day's route: plan it (owner), work it (staff).

Owner: plan a run (route × date × staff) with boxes/orders per shop and extra
tasks (return pickup, payment collection…), or generate today's runs from the
route templates. A stop can carry the shop's billing invoices: they fill the
delivery's boxes/orders/numbers, and `collect_due` adds a collection task for
what is still unpaid on them (app/invoices.py).
Staff: start the run, arrive at each shop (geofenced), complete its tasks,
skip a closed shop with a reason. Every staff action needs a fresh GPS fix and
an open attendance (checked in, not out).
"""
from __future__ import annotations

from datetime import date as _date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db, utc_now
from app.geo import GeoFix, distance_to, validate_fix
from app.invoices import MAX_PER_TASK, attach_invoices, balance_due, ensure_not_planned, resolve_invoices
from app.models import TASK_TYPES, FieldRoute, FieldRun, FieldRunStop, FieldShop, FieldStaff, FieldTask
from app.routers.attendance import require_checked_in
from app.security import Principal, current_principal, get_settings, require_owner, require_staff
from app.services import get_scoped, log_activity, prime_billing_reads, record_fix, run_out, run_stop_out
from app.timeutil import biz_local_to_utc, biz_today, iso_weekday, parse_hhmm

router = APIRouter(prefix="/api", tags=["runs"])


# ── Planning (owner) ──────────────────────────────────────────────────────────

class ExtraTaskIn(BaseModel):
    task_type: str = "general"
    title: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(None, max_length=1000)
    points: Optional[int] = Field(None, ge=0, le=1000)
    amount_expected: Optional[float] = Field(None, ge=0)


class StopPlanIn(BaseModel):
    shop_id: int
    boxes: Optional[int] = Field(None, ge=0, le=10000)
    orders_count: Optional[int] = Field(None, ge=0, le=1000)
    reference: Optional[str] = Field(None, max_length=200)
    delivery_points: Optional[int] = Field(None, ge=0, le=1000)
    invoice_ids: List[int] = Field(default_factory=list, max_length=MAX_PER_TASK)
    collect_due: bool = Field(False, description="Also collect what is unpaid on invoice_ids")
    tasks: List[ExtraTaskIn] = Field(default_factory=list)


class RunPlanIn(BaseModel):
    run_date: str
    staff_id: int
    route_id: Optional[int] = None
    name: Optional[str] = Field(None, max_length=80)
    due_time: Optional[str] = None  # HH:MM; default = route's due_time or 18:00
    notes: Optional[str] = Field(None, max_length=1000)
    # Omit to copy the route template's shops (no boxes yet).
    stops: Optional[List[StopPlanIn]] = None


def _check_day(day: str) -> str:
    try:
        return _date.fromisoformat(day).isoformat()
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Date must be YYYY-MM-DD")


def _check_task_type(t: str) -> str:
    if t not in TASK_TYPES:
        raise HTTPException(status_code=422, detail=f"task_type must be one of {list(TASK_TYPES)}")
    return t


def _add_stop(db: Session, p: Principal, run: FieldRun, plan: StopPlanIn, seq: int,
              due_at, default_points: int) -> FieldRunStop:
    shop = get_scoped(db, FieldShop, p.business_id, plan.shop_id, "Shop")
    invoices = resolve_invoices(db, p.business_id, shop, plan.invoice_ids)
    if plan.collect_due and not invoices:
        raise HTTPException(status_code=422, detail=f"Pick {shop.name}'s invoices to collect what is due on them")
    stop = FieldRunStop(business_id=p.business_id, run_id=run.id, shop_id=shop.id, seq=seq)
    db.add(stop)
    db.flush()
    if invoices or (plan.boxes or 0) > 0 or (plan.orders_count or 0) > 0:
        ensure_not_planned(db, p.business_id, "delivery", invoices)
        task = FieldTask(
            business_id=p.business_id, task_type="delivery", title="",
            staff_id=run.staff_id, shop_id=shop.id, run_id=run.id, run_stop_id=stop.id,
            due_at=due_at,
            points=plan.delivery_points if plan.delivery_points is not None else default_points,
            boxes_planned=plan.boxes, orders_count=plan.orders_count,
            reference=plan.reference, created_by=p.actor,
        )
        attach_invoices(db, task, invoices)
        task.boxes_planned, task.orders_count = task.boxes_planned or 0, task.orders_count or 0
        task.title = (f"Deliver {len(invoices)} invoice(s) to {shop.name}" if invoices and not task.boxes_planned
                      else f"Deliver {task.boxes_planned} box(es) to {shop.name}")
        db.add(task)
    due = [i for i in invoices if balance_due(i) > 0] if plan.collect_due else []
    if due:
        ensure_not_planned(db, p.business_id, "payment_collect", due)
        collect = FieldTask(
            business_id=p.business_id, task_type="payment_collect",
            title=f"Collect payment due on {len(due)} invoice(s)",
            staff_id=run.staff_id, shop_id=shop.id, run_id=run.id, run_stop_id=stop.id,
            due_at=due_at, points=default_points, created_by=p.actor,
        )
        attach_invoices(db, collect, due)
        db.add(collect)
    for t in plan.tasks:
        db.add(FieldTask(
            business_id=p.business_id, task_type=_check_task_type(t.task_type),
            title=t.title.strip(), description=t.description,
            staff_id=run.staff_id, shop_id=shop.id, run_id=run.id, run_stop_id=stop.id,
            due_at=due_at, points=t.points if t.points is not None else default_points,
            amount_expected=t.amount_expected, created_by=p.actor,
        ))
    db.flush()  # the next stop's ensure_not_planned must see this stop's invoices
    return stop


def _create_run(db: Session, p: Principal, req: RunPlanIn) -> FieldRun:
    day = _check_day(req.run_date)
    staff = get_scoped(db, FieldStaff, p.business_id, req.staff_id, "Staff member")
    if not staff.is_active:
        raise HTTPException(status_code=422, detail=f"{staff.name} is disabled")
    route = get_scoped(db, FieldRoute, p.business_id, req.route_id, "Route") if req.route_id else None
    if route is None and not req.stops:
        raise HTTPException(status_code=422, detail="Give a route or at least one stop")
    due_time = req.due_time or (route.due_time if route else "18:00")
    try:
        parse_hhmm(due_time)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="due_time must be HH:MM")
    if route is not None:
        clash = db.query(FieldRun.id).filter(
            FieldRun.business_id == p.business_id, FieldRun.route_id == route.id,
            FieldRun.run_date == day, FieldRun.status != "cancelled",
        ).first()
        if clash:
            raise HTTPException(status_code=409, detail=f"{route.name} is already planned for {day}")
    stops = req.stops if req.stops is not None else [StopPlanIn(shop_id=s.shop_id) for s in route.stops]
    if len({s.shop_id for s in stops}) != len(stops):
        raise HTTPException(status_code=422, detail="A shop appears twice in the run")

    settings = get_settings(db, p.business_id)
    due_at = biz_local_to_utc(day, due_time)
    run = FieldRun(
        business_id=p.business_id, route_id=route.id if route else None,
        name=(req.name or (route.name if route else f"Run {day}")).strip(),
        run_date=day, staff_id=staff.id, notes=req.notes,
    )
    db.add(run)
    db.flush()
    for i, plan in enumerate(stops):
        _add_stop(db, p, run, plan, i + 1, due_at, settings.default_task_points)
    return run


@router.post("/runs", status_code=201)
def plan_run(req: RunPlanIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    run = _create_run(db, p, req)
    log_activity(db, p, "run.plan", entity="run", entity_id=run.id,
                 summary=f"{run.name} on {run.run_date}")
    db.commit()
    db.refresh(run)
    return run_out(run)


class GenerateIn(BaseModel):
    run_date: Optional[str] = None


@router.post("/runs/generate")
def generate_runs(req: GenerateIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    """Create the day's runs from route templates scheduled for that weekday and
    having a default staff member. Existing runs are left alone (idempotent)."""
    day = _check_day(req.run_date or biz_today())
    wd = iso_weekday(day)
    created, skipped = [], []
    routes = db.query(FieldRoute).filter(FieldRoute.business_id == p.business_id,
                                         FieldRoute.is_active.is_(True)).all()
    for route in routes:
        days = [int(x) for x in (route.weekdays or "").split(",") if x.strip()]
        if days and wd not in days:
            continue
        if route.default_staff_id is None or not route.stops:
            skipped.append({"route": route.name, "reason": "no default staff" if route.stops else "no shops"})
            continue
        exists = db.query(FieldRun.id).filter(
            FieldRun.business_id == p.business_id, FieldRun.route_id == route.id,
            FieldRun.run_date == day, FieldRun.status != "cancelled").first()
        if exists:
            skipped.append({"route": route.name, "reason": "already planned"})
            continue
        try:
            run = _create_run(db, p, RunPlanIn(run_date=day, staff_id=route.default_staff_id, route_id=route.id))
        except HTTPException as e:
            skipped.append({"route": route.name, "reason": e.detail})
            continue
        created.append(run)
    if created:
        log_activity(db, p, "run.generate", entity="run", summary=f"{len(created)} run(s) for {day}")
    db.commit()
    return {"run_date": day, "created": [run_out(r, with_stops=False) for r in created], "skipped": skipped}


@router.get("/runs")
def list_runs(day: Optional[str] = Query(None), p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    day = _check_day(day or biz_today())
    rows = (db.query(FieldRun)
            .filter(FieldRun.business_id == p.business_id, FieldRun.run_date == day)
            .order_by(FieldRun.name.asc()).all())
    prime_billing_reads(shops=[stop.shop for run in rows for stop in run.stops],
                        tasks=[task for run in rows for stop in run.stops for task in stop.tasks])
    return [run_out(r) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: int, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    run = get_scoped(db, FieldRun, p.business_id, run_id, "Run")
    if p.kind == "staff" and run.staff_id != p.staff.id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run_out(run)


class RunPatch(BaseModel):
    staff_id: Optional[int] = None
    notes: Optional[str] = Field(None, max_length=1000)


@router.patch("/runs/{run_id}")
def update_run(run_id: int, req: RunPatch, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    run = get_scoped(db, FieldRun, p.business_id, run_id, "Run")
    if req.staff_id is not None and req.staff_id != run.staff_id:
        staff = get_scoped(db, FieldStaff, p.business_id, req.staff_id, "Staff member")
        run.staff_id = staff.id
        # Pending work moves with the run; finished work keeps its doer.
        db.query(FieldTask).filter(FieldTask.run_id == run.id, FieldTask.status == "pending") \
            .update({FieldTask.staff_id: staff.id}, synchronize_session=False)
        log_activity(db, p, "run.reassign", entity="run", entity_id=run.id, summary=f"→ {staff.name}")
    if req.notes is not None:
        run.notes = req.notes
    db.commit()
    db.refresh(run)
    return run_out(run)


@router.post("/runs/{run_id}/stops", status_code=201)
def add_stop(run_id: int, req: StopPlanIn, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    run = get_scoped(db, FieldRun, p.business_id, run_id, "Run")
    if run.status in ("completed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"Run is {run.status}")
    if any(s.shop_id == req.shop_id for s in run.stops):
        raise HTTPException(status_code=409, detail="That shop is already on this run")
    due = next((t.due_at for s in run.stops for t in s.tasks if t.due_at), None) \
        or biz_local_to_utc(run.run_date, "18:00")
    settings = get_settings(db, p.business_id)
    stop = _add_stop(db, p, run, req, (max((s.seq for s in run.stops), default=0) + 1), due,
                     settings.default_task_points)
    log_activity(db, p, "run.add_stop", entity="run_stop", entity_id=stop.id, summary=run.name)
    db.commit()
    db.refresh(run)
    return run_out(run)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: int, p: Principal = Depends(require_owner), db: Session = Depends(get_db)):
    run = get_scoped(db, FieldRun, p.business_id, run_id, "Run")
    if run.status == "completed":
        raise HTTPException(status_code=409, detail="Completed runs cannot be cancelled")
    run.status = "cancelled"
    db.query(FieldTask).filter(FieldTask.run_id == run.id, FieldTask.status == "pending") \
        .update({FieldTask.status: "cancelled"}, synchronize_session=False)
    log_activity(db, p, "run.cancel", entity="run", entity_id=run.id, summary=run.name)
    db.commit()
    db.refresh(run)
    return run_out(run)


# ── Working the run (staff) ───────────────────────────────────────────────────

class GeoBody(BaseModel):
    geo: GeoFix


class SkipBody(BaseModel):
    geo: GeoFix
    reason: str = Field(..., min_length=2, max_length=300)


def _my_run(db: Session, p: Principal, run_id: int) -> FieldRun:
    run = get_scoped(db, FieldRun, p.business_id, run_id, "Run")
    if run.staff_id != p.staff.id:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status == "cancelled":
        raise HTTPException(status_code=409, detail="This run was cancelled by the owner")
    if run.run_date != biz_today():
        raise HTTPException(status_code=409, detail=f"This run is for {run.run_date}, not today")
    return run


def _my_stop(db: Session, p: Principal, stop_id: int) -> tuple[FieldRun, FieldRunStop]:
    stop = get_scoped(db, FieldRunStop, p.business_id, stop_id, "Stop")
    return _my_run(db, p, stop.run_id), stop


def _start(run: FieldRun, fix: GeoFix) -> None:
    run.status = "in_progress"
    run.started_at = utc_now()
    run.start_lat, run.start_lng = fix.lat, fix.lng


@router.post("/runs/{run_id}/start")
def start_run(run_id: int, body: GeoBody, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    settings = get_settings(db, p.business_id)
    fix = validate_fix(body.geo, settings.max_accuracy_m)
    require_checked_in(db, p.staff)
    run = _my_run(db, p, run_id)
    if run.status != "planned":
        raise HTTPException(status_code=409, detail=f"Run is already {run.status.replace('_', ' ')}")
    _start(run, fix)
    record_fix(db, p.staff, fix, event="run_start")
    log_activity(db, p, "run.start", entity="run", entity_id=run.id, summary=run.name, fix=fix)
    db.commit()
    db.refresh(run)
    return run_out(run)


@router.post("/run-stops/{stop_id}/arrive")
def arrive(stop_id: int, body: GeoBody, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    settings = get_settings(db, p.business_id)
    fix = validate_fix(body.geo, settings.max_accuracy_m)
    require_checked_in(db, p.staff)
    run, stop = _my_stop(db, p, stop_id)
    if stop.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {stop.status} at {stop.shop.name}")
    shop = stop.shop
    dist = distance_to(shop.lat, shop.lng, fix)
    outside = dist is not None and dist > settings.geofence_radius_m
    if outside and settings.geofence_enforced:
        raise HTTPException(
            status_code=422,
            detail=f"You are {int(dist)} m from {shop.name} (limit {settings.geofence_radius_m} m). Reach the shop and retry.",
        )
    if run.status == "planned":
        _start(run, fix)
    if shop.lat is None:
        # First visit pins the shop. Accuracy was already checked above.
        shop.lat, shop.lng, shop.location_source = fix.lat, fix.lng, "staff"
    stop.status = "arrived"
    stop.arrived_at = utc_now()
    stop.arrived_lat, stop.arrived_lng, stop.arrived_accuracy_m = fix.lat, fix.lng, fix.accuracy
    stop.arrival_distance_m = dist
    stop.outside_geofence = bool(outside)
    record_fix(db, p.staff, fix, event="arrive")
    log_activity(db, p, "stop.arrive", entity="run_stop", entity_id=stop.id,
                 summary=f"{shop.name}{f' · {int(dist)} m from pin' if dist is not None else ' · pinned'}", fix=fix)
    db.commit()
    db.refresh(stop)
    return run_stop_out(stop)


@router.post("/run-stops/{stop_id}/skip")
def skip_stop(stop_id: int, body: SkipBody, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    settings = get_settings(db, p.business_id)
    fix = validate_fix(body.geo, settings.max_accuracy_m)
    require_checked_in(db, p.staff)
    run, stop = _my_stop(db, p, stop_id)
    if stop.status in ("done", "skipped"):
        raise HTTPException(status_code=409, detail=f"Stop is already {stop.status}")
    stop.status = "skipped"
    stop.skip_reason = body.reason.strip()
    stop.done_at = utc_now()
    record_fix(db, p.staff, fix, event="skip")
    log_activity(db, p, "stop.skip", entity="run_stop", entity_id=stop.id,
                 summary=f"{stop.shop.name}: {stop.skip_reason}", fix=fix)
    maybe_complete_run(run)
    db.commit()
    db.refresh(stop)
    return run_stop_out(stop)


def maybe_complete_stop(stop: FieldRunStop) -> None:
    open_tasks = [t for t in stop.tasks if t.status == "pending"]
    if stop.status == "arrived" and not open_tasks:
        stop.status = "done"
        stop.done_at = utc_now()


def maybe_complete_run(run: FieldRun) -> None:
    if run.status != "completed" and run.stops and all(s.status in ("done", "skipped") for s in run.stops):
        run.status = "completed"
        run.completed_at = utc_now()


@router.post("/run-stops/{stop_id}/done")
def finish_stop(stop_id: int, body: GeoBody, p: Principal = Depends(require_staff), db: Session = Depends(get_db)):
    """Leave a shop that had no tasks (a pure visit). Shops with open tasks close
    automatically when their last task is completed."""
    settings = get_settings(db, p.business_id)
    fix = validate_fix(body.geo, settings.max_accuracy_m)
    require_checked_in(db, p.staff)
    run, stop = _my_stop(db, p, stop_id)
    if stop.status != "arrived":
        raise HTTPException(status_code=409, detail="Mark arrival at the shop first")
    if any(t.status == "pending" for t in stop.tasks):
        raise HTTPException(status_code=409, detail="Complete or report the open tasks first")
    stop.status = "done"
    stop.done_at = utc_now()
    record_fix(db, p.staff, fix, event="stop_done")
    log_activity(db, p, "stop.done", entity="run_stop", entity_id=stop.id, summary=stop.shop.name, fix=fix)
    maybe_complete_run(run)
    db.commit()
    db.refresh(stop)
    return run_stop_out(stop)
