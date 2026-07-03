"""
core/shifts/service.py — shift & cash-drawer commands (plan Phase 3 + 3b).
==========================================================================
Rules (aligned with professional POS standards — Shopify/Lightspeed/Square):
  • ONE OPEN shift per user at a time.
  • EVERY counter sale requires an open shift — ALL roles including the owner
    (single-operator businesses need day-wise drawer accounting too).
  • APPEND-ONLY: a closed shift is never reopened or edited; cash-movement
    corrections are opposite movements, never edits.
  • DETERMINISTIC tallies: expected cash/UPI are pure SQL sums over the
    InvoicePayment + ShiftCashMovement rows stamped with this shift's id.
    Never AI, never client-supplied.

Float carry-forward (3b, Shopify model):
  • The previous shift's `closing_float` (what was LEFT in the drawer at close)
    is the SUGGESTED opening cash for the next shift. The operator may edit it;
    the difference is recorded as an `opening_variance` movement so every
    rupee's journey is auditable.
  • At close the operator counts the drawer (reconciliation happens on the FULL
    count), then chooses how much to leave for the next shift; the removed
    remainder is recorded as a `closing_removal` movement (→ bank / owner).

Tally definition:
  expected_cash = opening_cash + Σ cash receipts + Σ paid_in − Σ paid_out
  expected_upi  =                Σ upi receipts
  (opening_variance and closing_removal are audit-only and NEVER enter the
   tally: the entered opening cash is already the truth, and the closing
   removal happens after the count snapshot.)
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import func

from database.models import RegisterShift, ShiftCashMovement
from core.models import InvoicePayment, Expense

logger = logging.getLogger("bizassist.shifts")

# Movement vocabulary (Square "Paid In/Out" + Lightspeed cash movements).
PAID_IN_CATEGORIES = {"change_top_up"}
PAID_OUT_CATEGORIES = {"bank_deposit", "expense", "owner_withdrawal"}
AUDIT_ONLY_CATEGORIES = {"opening_variance", "closing_removal"}  # never in tally
REMOVAL_DESTINATIONS = {"bank_deposit", "owner_withdrawal"}


def _round2(x: float) -> float:
    return round(float(x or 0.0) + 1e-9, 2)


def _norm_mode(mode: Optional[str]) -> str:
    """Normalise free-form payment_mode strings into tally buckets."""
    m = (mode or "cash").strip().lower()
    if m in ("cash",):
        return "cash"
    if m in ("upi", "gpay", "phonepe", "paytm", "qr"):
        return "upi"
    if m in ("card", "credit card", "debit card"):
        return "card"
    return "other"


# ── Queries ──────────────────────────────────────────────────────────────────

def get_open_shift(db, *, business_id: int, user_id: int) -> Optional[RegisterShift]:
    """The user's active OPEN shift, or None."""
    return (
        db.query(RegisterShift)
        .filter(
            RegisterShift.business_id == business_id,
            RegisterShift.user_id == user_id,
            RegisterShift.status == "OPEN",
        )
        .order_by(RegisterShift.start_time.desc())
        .first()
    )


def require_open_shift(db, *, business_id: int, user_id: int) -> RegisterShift:
    """
    Gatekeeper for the billing counter: EVERY role (owner included) must have
    an open shift to ring a sale — this is what makes end-of-day tallies exact.
    Raises ValueError('shift_required') when there is none; routes map it to 409.
    """
    shift = get_open_shift(db, business_id=business_id, user_id=user_id)
    if shift is None:
        raise ValueError("shift_required")
    return shift


def suggested_opening_cash(db, *, business_id: int, user_id: int) -> dict:
    """
    The float to PREFILL when opening a shift (Shopify model): the most recent
    CLOSED shift's `closing_float` — same OPERATOR first (multi-counter: each
    login is its own drawer), business-wide as a fallback (owner ↔ cashier
    trading one drawer). Falls back to the counted closing cash for shifts
    closed before leave-in-drawer existed. {suggested: None} = no history.
    """
    def latest(q):
        return q.filter(RegisterShift.status == "CLOSED") \
                .order_by(RegisterShift.end_time.desc()).first()

    base = db.query(RegisterShift).filter(RegisterShift.business_id == business_id)
    prev = latest(base.filter(RegisterShift.user_id == user_id)) or latest(base)
    if prev is None:
        return {"suggested": None, "source_shift_id": None, "source_end_time": None}
    amount = prev.closing_float if prev.closing_float is not None else prev.closing_cash_actual
    return {
        "suggested": _round2(amount) if amount is not None else None,
        "source_shift_id": prev.id,
        "source_end_time": prev.end_time.isoformat() if prev.end_time else None,
    }


# ── Commands ─────────────────────────────────────────────────────────────────

def open_shift(db, *, business_id: int, user_id: int,
               opening_cash: float, notes: Optional[str] = None) -> RegisterShift:
    """COMMAND: open a new register shift with a counted cash float. Commits.
    Rejects if the user already has an OPEN shift (close it first).

    Records the carry-forward expectation (`opening_expected`) and, when the
    operator opens with a DIFFERENT amount, an audit-only `opening_variance`
    movement — so a float that changed overnight is visible, not silent."""
    if opening_cash is None or float(opening_cash) < 0:
        raise ValueError("opening_cash must be zero or positive")

    existing = get_open_shift(db, business_id=business_id, user_id=user_id)
    if existing is not None:
        raise ValueError("shift_already_open")

    suggestion = suggested_opening_cash(db, business_id=business_id, user_id=user_id)
    expected = suggestion["suggested"]

    shift = RegisterShift(
        business_id=business_id,
        user_id=user_id,
        start_time=datetime.utcnow(),
        opening_cash=_round2(opening_cash),
        opening_expected=expected,
        status="OPEN",
        notes=notes,
    )
    db.add(shift)
    db.flush()

    if expected is not None and abs(_round2(opening_cash) - expected) >= 0.005:
        diff = _round2(_round2(opening_cash) - expected)
        db.add(ShiftCashMovement(
            business_id=business_id, shift_id=shift.id, user_id=user_id,
            movement_type=("paid_in" if diff > 0 else "paid_out"),
            category="opening_variance",
            amount=abs(diff),
            note=f"Opening float {_round2(opening_cash):.2f} differs from carried-forward "
                 f"{expected:.2f} (shift #{suggestion['source_shift_id']})",
        ))
        logger.info("[SHIFTS] opening variance %.2f biz=%s user=%s shift=%s",
                    diff, business_id, user_id, shift.id)

    db.commit()
    db.refresh(shift)
    logger.info("[SHIFTS] opened shift %s biz=%s user=%s float=%.2f (carried=%s)",
                shift.id, business_id, user_id, shift.opening_cash, expected)
    return shift


def record_cash_movement(db, *, business_id: int, user_id: int,
                         movement_type: str, category: str, amount: float,
                         note: Optional[str] = None,
                         expense_category: Optional[str] = None) -> ShiftCashMovement:
    """
    COMMAND: record a mid-shift Paid In / Paid Out on the caller's OPEN shift.
    Commits. Append-only — a mistake is corrected by an opposite movement.

    category='expense' additionally creates a REAL Expense row (Cash) and posts
    it to the double-entry journal (Dr <category> Expense, Cr Cash) — the ₹200
    drawer tea shows up in the P&L, not just the drawer tally.
    """
    shift = require_open_shift(db, business_id=business_id, user_id=user_id)

    if amount is None or float(amount) <= 0:
        raise ValueError("amount must be greater than 0")
    if movement_type == "paid_in":
        if category not in PAID_IN_CATEGORIES:
            raise ValueError(f"invalid paid_in category '{category}'")
    elif movement_type == "paid_out":
        if category not in PAID_OUT_CATEGORIES:
            raise ValueError(f"invalid paid_out category '{category}'")
    else:
        raise ValueError("movement_type must be paid_in or paid_out")

    expense_id = None
    if category == "expense":
        exp = Expense(
            business_id=business_id,
            expense_date=datetime.today().strftime("%Y-%m-%d"),
            category=(expense_category or "Others"),
            expense_type="Indirect",
            amount=_round2(amount),
            payment_mode="Cash",
            note=(note or f"Drawer paid-out (shift #{shift.id})"),
        )
        db.add(exp)
        db.flush()
        from core.accounting import posting
        posting.post_expense(db, exp)
        expense_id = exp.id

    mv = ShiftCashMovement(
        business_id=business_id, shift_id=shift.id, user_id=user_id,
        movement_type=movement_type, category=category,
        amount=_round2(amount), note=note, expense_id=expense_id,
    )
    db.add(mv)
    db.commit()
    db.refresh(mv)
    logger.info("[SHIFTS] movement %s/%s %.2f biz=%s shift=%s expense_id=%s",
                movement_type, category, mv.amount, business_id, shift.id, expense_id)
    return mv


def _movement_sums(db, shift: RegisterShift):
    """Σ paid_in / Σ paid_out that COUNT toward the drawer (audit-only excluded)."""
    rows = (
        db.query(ShiftCashMovement.movement_type,
                 func.coalesce(func.sum(ShiftCashMovement.amount), 0.0))
        .filter(
            ShiftCashMovement.business_id == shift.business_id,
            ShiftCashMovement.shift_id == shift.id,
            ~ShiftCashMovement.category.in_(AUDIT_ONLY_CATEGORIES),
        )
        .group_by(ShiftCashMovement.movement_type)
        .all()
    )
    sums = {"paid_in": 0.0, "paid_out": 0.0}
    for mtype, total in rows:
        if mtype in sums:
            sums[mtype] += float(total or 0.0)
    return sums


def compute_tally(db, shift: RegisterShift) -> dict:
    """
    QUERY: the system's expected drawer for this shift — pure SQL sums over the
    InvoicePayment rows (counter sales AND credit collections taken during it)
    plus the shift's counted cash movements. No side effects.
    """
    rows = (
        db.query(InvoicePayment.payment_mode,
                 func.coalesce(func.sum(InvoicePayment.amount_paid), 0.0))
        .filter(
            InvoicePayment.business_id == shift.business_id,
            InvoicePayment.shift_id == shift.id,
        )
        .group_by(InvoicePayment.payment_mode)
        .all()
    )
    by_mode = {"cash": 0.0, "upi": 0.0, "card": 0.0, "other": 0.0}
    for mode, total in rows:
        by_mode[_norm_mode(mode)] += float(total or 0.0)

    moves = _movement_sums(db, shift)
    expected_cash = _round2(shift.opening_cash + by_mode["cash"]
                            + moves["paid_in"] - moves["paid_out"])
    expected_upi = _round2(by_mode["upi"])
    return {
        "shift_id": shift.id,
        "opening_cash": _round2(shift.opening_cash),
        "sales_cash": _round2(by_mode["cash"]),
        "sales_upi": _round2(by_mode["upi"]),
        "sales_card": _round2(by_mode["card"]),
        "sales_other": _round2(by_mode["other"]),
        "paid_in": _round2(moves["paid_in"]),
        "paid_out": _round2(moves["paid_out"]),
        "expected_cash": expected_cash,
        "expected_upi": expected_upi,
    }


def close_shift(db, *, business_id: int, user_id: int,
                closing_cash_actual: float,
                closing_upi_actual: float = 0.0,
                leave_in_drawer: Optional[float] = None,
                removal_destination: str = "bank_deposit",
                notes: Optional[str] = None) -> RegisterShift:
    """
    COMMAND: close the user's OPEN shift. Commits.

    Order of operations (industry standard):
      1. Snapshot the system expectation and record the FULL counted drawer —
         reconciliation always happens on the whole count.
      2. `leave_in_drawer` (default: everything) becomes `closing_float`, the
         next shift's suggested opening. The removed remainder is recorded as
         an audit-only `closing_removal` movement tagged with its destination
         (bank deposit / owner withdrawal).
    """
    shift = get_open_shift(db, business_id=business_id, user_id=user_id)
    if shift is None:
        raise ValueError("no_open_shift")
    if closing_cash_actual is None or float(closing_cash_actual) < 0:
        raise ValueError("closing_cash_actual must be zero or positive")
    if removal_destination not in REMOVAL_DESTINATIONS:
        raise ValueError("removal_destination must be bank_deposit or owner_withdrawal")

    counted = _round2(closing_cash_actual)
    left = counted if leave_in_drawer is None else _round2(leave_in_drawer)
    if left < 0 or left > counted:
        raise ValueError("leave_in_drawer must be between 0 and the counted cash")

    tally = compute_tally(db, shift)
    shift.closing_cash_expected = tally["expected_cash"]
    shift.closing_upi_expected = tally["expected_upi"]
    shift.closing_cash_actual = counted
    shift.closing_upi_actual = _round2(closing_upi_actual)
    shift.closing_float = left
    shift.end_time = datetime.utcnow()
    shift.status = "CLOSED"
    if notes:
        shift.notes = f"{shift.notes}\n{notes}".strip() if shift.notes else notes

    removed = _round2(counted - left)
    if removed > 0:
        dest_label = "Bank deposit" if removal_destination == "bank_deposit" else "Owner withdrawal"
        db.add(ShiftCashMovement(
            business_id=business_id, shift_id=shift.id, user_id=user_id,
            movement_type="paid_out", category="closing_removal",
            amount=removed,
            note=f"{dest_label} at shift close — left {left:.2f} in drawer",
        ))

    db.commit()
    db.refresh(shift)
    logger.info(
        "[SHIFTS] closed shift %s biz=%s user=%s cash exp=%.2f act=%.2f left=%.2f removed=%.2f · upi exp=%.2f act=%.2f",
        shift.id, business_id, user_id,
        shift.closing_cash_expected, shift.closing_cash_actual, left, removed,
        shift.closing_upi_expected, shift.closing_upi_actual,
    )
    return shift


# ── Serializers ──────────────────────────────────────────────────────────────

def movement_out(mv: ShiftCashMovement) -> dict:
    return {
        "id": mv.id,
        "movement_type": mv.movement_type,
        "category": mv.category,
        "amount": mv.amount,
        "note": mv.note,
        "expense_id": mv.expense_id,
        "created_at": mv.created_at.isoformat() if mv.created_at else None,
    }


def list_movements(db, shift: RegisterShift) -> list:
    rows = (
        db.query(ShiftCashMovement)
        .filter(ShiftCashMovement.business_id == shift.business_id,
                ShiftCashMovement.shift_id == shift.id)
        .order_by(ShiftCashMovement.id.asc())
        .all()
    )
    return [movement_out(m) for m in rows]


def shift_out(shift: RegisterShift, tally: Optional[dict] = None,
              movements: Optional[list] = None) -> dict:
    """Serializer shared by the routes."""
    d = {
        "id": shift.id,
        "uid": shift.uid,
        "user_id": shift.user_id,
        "start_time": shift.start_time.isoformat() if shift.start_time else None,
        "end_time": shift.end_time.isoformat() if shift.end_time else None,
        "opening_cash": shift.opening_cash,
        "opening_expected": shift.opening_expected,
        "closing_cash_expected": shift.closing_cash_expected,
        "closing_cash_actual": shift.closing_cash_actual,
        "closing_upi_expected": shift.closing_upi_expected,
        "closing_upi_actual": shift.closing_upi_actual,
        "closing_float": shift.closing_float,
        "status": shift.status,
        "notes": shift.notes,
    }
    if shift.status == "CLOSED":
        d["cash_discrepancy"] = _round2(
            (shift.closing_cash_actual or 0.0) - (shift.closing_cash_expected or 0.0))
        d["upi_discrepancy"] = _round2(
            (shift.closing_upi_actual or 0.0) - (shift.closing_upi_expected or 0.0))
    if tally:
        d["tally"] = tally
    if movements is not None:
        d["movements"] = movements
    return d
