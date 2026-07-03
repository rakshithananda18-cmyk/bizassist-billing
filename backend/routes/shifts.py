"""
routes/shifts.py — thin HTTP layer over core.shifts (plan Phase 3 + 3b).
========================================================================
Shift & Cash-Drawer Management. Per FOUNDATION.md: routes authenticate, scope
to the caller's business, validate, and call the service. No money math here.

  POST /shifts/open              open a shift with a counted cash float
  GET  /shifts/suggested-float   carry-forward suggestion (prev closing float)
  GET  /shifts/current           the caller's active OPEN shift (or null)
  GET  /shifts/{id}/tally        system-expected cash/UPI for one shift
  POST /shifts/movements         Paid In / Paid Out on the caller's open shift
  POST /shifts/close             count drawer, leave-in-drawer, CLOSE
  GET  /shifts                   owner-only: shift reconciliation history

Gatekeeper rule (user decision, 2026-07-03): EVERY role — cashier AND owner —
must have an OPEN shift to ring a sale. Single-operator businesses need
day-wise drawer accounting too, so there is no owner bypass.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import RegisterShift, User
from services.auth import get_active_user, require_owner
from core.shifts import service as shifts

router = APIRouter()
logger = logging.getLogger("bizassist.routes.shifts")


def _uid(current_user: dict) -> int:
    """The operator's own user id (staff tokens carry user_id; owner tokens may
    predate it — for an owner, business id IS the user id)."""
    return current_user.get("user_id") or current_user["id"]


# ── Schemas ──────────────────────────────────────────────────────────────────

class OpenShiftRequest(BaseModel):
    opening_cash: float
    notes: Optional[str] = None


class CashMovementRequest(BaseModel):
    movement_type: str                       # paid_in | paid_out
    category: str                            # change_top_up | bank_deposit | expense | owner_withdrawal
    amount: float
    note: Optional[str] = None
    expense_category: Optional[str] = None   # for category='expense': Rent|Utilities|…|Others


class CloseShiftRequest(BaseModel):
    closing_cash_actual: float
    closing_upi_actual: float = 0.0
    leave_in_drawer: Optional[float] = None      # default: leave everything
    removal_destination: str = "bank_deposit"    # bank_deposit | owner_withdrawal
    notes: Optional[str] = None


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/shifts/open", status_code=201)
def open_shift(req: OpenShiftRequest,
               current_user: dict = Depends(get_active_user),
               db: Session = Depends(get_db)):
    """Open a register shift with the counted opening cash float. If it differs
    from the carried-forward suggestion, an opening_variance movement is logged."""
    try:
        shift = shifts.open_shift(
            db, business_id=current_user["id"], user_id=_uid(current_user),
            opening_cash=req.opening_cash, notes=req.notes,
        )
        return {"shift": shifts.shift_out(shift, movements=shifts.list_movements(db, shift))}
    except ValueError as ve:
        code = str(ve)
        if code == "shift_already_open":
            raise HTTPException(status_code=409,
                                detail="You already have an open shift. Close it before opening a new one.")
        raise HTTPException(status_code=422, detail=code)


@router.get("/shifts/suggested-float")
def suggested_float(current_user: dict = Depends(get_active_user),
                    db: Session = Depends(get_db)):
    """The float to prefill in the Open Shift screen: the previous shift's
    'left in drawer' amount (same operator first, business-wide fallback)."""
    return shifts.suggested_opening_cash(
        db, business_id=current_user["id"], user_id=_uid(current_user))


@router.get("/shifts/current")
def current_shift(current_user: dict = Depends(get_active_user),
                  db: Session = Depends(get_db)):
    """The caller's active OPEN shift with a LIVE tally + movements, or {shift: null}."""
    shift = shifts.get_open_shift(
        db, business_id=current_user["id"], user_id=_uid(current_user))
    if shift is None:
        return {"shift": None}
    return {"shift": shifts.shift_out(shift,
                                      tally=shifts.compute_tally(db, shift),
                                      movements=shifts.list_movements(db, shift))}


@router.post("/shifts/movements", status_code=201)
def record_movement(req: CashMovementRequest,
                    current_user: dict = Depends(get_active_user),
                    db: Session = Depends(get_db)):
    """Paid In / Paid Out on the caller's OPEN shift (Square model). A drawer
    'expense' paid-out also creates a real Expense row posted to the journal."""
    try:
        mv = shifts.record_cash_movement(
            db, business_id=current_user["id"], user_id=_uid(current_user),
            movement_type=req.movement_type, category=req.category,
            amount=req.amount, note=req.note, expense_category=req.expense_category,
        )
    except ValueError as ve:
        code = str(ve)
        if code == "shift_required":
            raise HTTPException(status_code=409,
                                detail="Open a register shift before recording cash movements.")
        raise HTTPException(status_code=422, detail=code)
    shift = shifts.get_open_shift(
        db, business_id=current_user["id"], user_id=_uid(current_user))
    return {"movement": shifts.movement_out(mv),
            "tally": shifts.compute_tally(db, shift) if shift else None}


@router.get("/shifts/{shift_id}/tally")
def shift_tally(shift_id: int,
                current_user: dict = Depends(get_active_user),
                db: Session = Depends(get_db)):
    """System-expected cash/UPI for one shift (float + receipts ± movements)."""
    shift = (
        db.query(RegisterShift)
        .filter(RegisterShift.id == shift_id,
                RegisterShift.business_id == current_user["id"])
        .first()
    )
    if shift is None:
        raise HTTPException(status_code=404, detail=f"Shift {shift_id} not found")
    # A cashier may only tally their OWN shift; owner-level roles see any.
    role = (current_user.get("role") or "").lower()
    if role in ("cashier", "supply adder") and shift.user_id != _uid(current_user):
        raise HTTPException(status_code=403, detail="You can only tally your own shift.")
    return {"tally": shifts.compute_tally(db, shift)}


@router.post("/shifts/close")
def close_shift(req: CloseShiftRequest,
                current_user: dict = Depends(get_active_user),
                db: Session = Depends(get_db)):
    """Close the caller's open shift: record counted cash/UPI, snapshot the
    expectation, choose what stays in the drawer for the next shift, and log
    the removed remainder as a bank deposit / owner withdrawal."""
    try:
        shift = shifts.close_shift(
            db, business_id=current_user["id"], user_id=_uid(current_user),
            closing_cash_actual=req.closing_cash_actual,
            closing_upi_actual=req.closing_upi_actual,
            leave_in_drawer=req.leave_in_drawer,
            removal_destination=req.removal_destination,
            notes=req.notes,
        )
        return {"shift": shifts.shift_out(shift, movements=shifts.list_movements(db, shift))}
    except ValueError as ve:
        code = str(ve)
        if code == "no_open_shift":
            raise HTTPException(status_code=409, detail="You have no open shift to close.")
        raise HTTPException(status_code=422, detail=code)


@router.get("/shifts")
def list_shifts(limit: int = 50, offset: int = 0,
                current_user: dict = Depends(require_owner),
                db: Session = Depends(get_db)):
    """Owner-only: shift reconciliation history for the whole business —
    who operated the register, when, cash/UPI discrepancies, and movements."""
    bid = current_user["id"]
    q = (
        db.query(RegisterShift)
        .filter(RegisterShift.business_id == bid)
        .order_by(RegisterShift.start_time.desc())
    )
    total = q.count()
    rows = q.offset(max(offset, 0)).limit(min(max(limit, 1), 200)).all()

    # Resolve operator display names in one query.
    user_ids = {r.user_id for r in rows}
    names = {}
    if user_ids:
        for u in db.query(User).filter(User.id.in_(user_ids)).all():
            names[u.id] = u.staff_login_name or u.username

    out = []
    for r in rows:
        d = shifts.shift_out(r, movements=shifts.list_movements(db, r))
        d["operator"] = names.get(r.user_id, f"user #{r.user_id}")
        out.append(d)
    return {"shifts": out, "total": total}
