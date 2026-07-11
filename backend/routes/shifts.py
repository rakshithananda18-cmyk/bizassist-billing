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


def _safe_uid(current_user: dict, db: Session) -> int:
    """Resolve the operator's user_id, with a cross-DB fallback.

    When a Local+Cloud user opens the cloud URL while still holding a
    local-issued JWT, the embedded user_id (e.g. 40) won't exist in the
    cloud DB's users table. In that case fall back to business_id (== the
    cloud-native owner id), which always exists.
    """
    uid = current_user.get("user_id") or current_user["id"]
    bid = current_user["id"]
    if uid == bid:
        return uid  # same value — no check needed
    # Verify the uid actually exists; if not, use the business owner's id.
    exists = db.query(User.id).filter(User.id == uid).first()
    return uid if exists else bid


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
            db, business_id=current_user["id"], user_id=_safe_uid(current_user, db),
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
        db, business_id=current_user["id"], user_id=_safe_uid(current_user, db))


@router.get("/shifts/current")
def current_shift(current_user: dict = Depends(get_active_user),
                  db: Session = Depends(get_db)):
    """The caller's active OPEN shift with a LIVE tally + movements, or {shift: null}."""
    shift = shifts.get_open_shift(
        db, business_id=current_user["id"], user_id=_safe_uid(current_user, db))
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
            db, business_id=current_user["id"], user_id=_safe_uid(current_user, db),
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
        db, business_id=current_user["id"], user_id=_safe_uid(current_user, db))
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
    if role in ("cashier", "supply adder") and shift.user_id != _safe_uid(current_user, db):
        raise HTTPException(status_code=403, detail="You can only tally your own shift.")
    return {"tally": shifts.compute_tally(db, shift)}


@router.get("/shifts/{shift_id}/invoices")
def shift_invoices(shift_id: int,
                   current_user: dict = Depends(get_active_user),
                   db: Session = Depends(get_db)):
    """Invoices that took a payment during this shift — powers the printable
    shift summary and the shift-history drill-down. Grouped per invoice with
    the amount collected IN THIS SHIFT (an invoice part-paid across two shifts
    shows its per-shift slice in each). Same visibility rule as /tally."""
    shift = (
        db.query(RegisterShift)
        .filter(RegisterShift.id == shift_id,
                RegisterShift.business_id == current_user["id"])
        .first()
    )
    if shift is None:
        raise HTTPException(status_code=404, detail=f"Shift {shift_id} not found")
    role = (current_user.get("role") or "").lower()
    if role in ("cashier", "supply adder") and shift.user_id != _safe_uid(current_user, db):
        raise HTTPException(status_code=403, detail="You can only view your own shift.")

    from core.models import InvoicePayment
    from database.models import Invoice
    rows = (
        db.query(InvoicePayment, Invoice)
        .join(Invoice, InvoicePayment.invoice_id == Invoice.id)
        .filter(InvoicePayment.business_id == current_user["id"],
                InvoicePayment.shift_id == shift.id)
        .order_by(InvoicePayment.id.asc())
        .all()
    )
    by_invoice = {}
    for pay, inv in rows:
        e = by_invoice.setdefault(inv.id, {
            "invoice_no": inv.invoice_id,
            "customer": inv.customer,
            "invoice_total": round(float(inv.total_amount or inv.amount or 0.0), 2),
            "status": inv.status,
            "collected_in_shift": 0.0,
            "modes": set(),
            "first_payment_at": None,
        })
        e["collected_in_shift"] = round(e["collected_in_shift"] + float(pay.amount_paid or 0.0), 2)
        if pay.payment_mode:
            e["modes"].add(str(pay.payment_mode).lower())
        ts = getattr(pay, "created_at", None)
        if ts and (e["first_payment_at"] is None or ts < e["first_payment_at"]):
            e["first_payment_at"] = ts
    out = []
    for e in by_invoice.values():
        e["modes"] = sorted(e["modes"])
        e["first_payment_at"] = e["first_payment_at"].isoformat() if e["first_payment_at"] else None
        out.append(e)
    out.sort(key=lambda r: r["first_payment_at"] or "")
    return {"shift_id": shift.id, "invoices": out,
            "total_collected": round(sum(r["collected_in_shift"] for r in out), 2)}


@router.post("/shifts/close")
def close_shift(req: CloseShiftRequest,
                current_user: dict = Depends(get_active_user),
                db: Session = Depends(get_db)):
    """Close the caller's open shift: record counted cash/UPI, snapshot the
    expectation, choose what stays in the drawer for the next shift, and log
    the removed remainder as a bank deposit / owner withdrawal."""
    try:
        shift = shifts.close_shift(
            db, business_id=current_user["id"], user_id=_safe_uid(current_user, db),
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
