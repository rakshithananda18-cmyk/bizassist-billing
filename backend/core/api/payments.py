"""
core/api/payments.py — Payments & Credit Notes HTTP layer (Phase 1B).
====================================================================
Per FOUNDATION.md: routes stay thin. Scoped by business_id.

  POST /payments               record payment receipt against invoice
  POST /credit-notes           create credit note for a return / adjustment
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Invoice, InvoicePayment, Customer, Expense
from services.auth import get_active_user, restrict_cashier
from core.billing import commands as billing
from core.sync.idempotency import ReplayGuard, replay_guard
from services.realtime import realtime_manager

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.payments")


# ── Schemas ───────────────────────────────────────────────────────────────────

class RecordPaymentRequest(BaseModel):
    invoice_id: int
    amount_paid: float
    payment_mode: Optional[str] = "Cash"
    payment_date: Optional[str] = None
    note: Optional[str] = None
    idempotency_key: Optional[str] = None


class RecordPaymentRequestFlexible(BaseModel):
    # Backend native fields
    invoice_id: Optional[int] = None
    amount_paid: Optional[float] = None
    payment_mode: Optional[str] = None
    payment_date: Optional[str] = None
    note: Optional[str] = None
    idempotency_key: Optional[str] = None
    
    # Frontend compatibility fields
    type: Optional[str] = None
    invoice_ref: Optional[str] = None
    amount: Optional[float] = None
    method: Optional[str] = None
    reference: Optional[str] = None
    date: Optional[str] = None


class CreditNoteLine(BaseModel):
    product_id: Optional[int] = None
    product_name: str
    quantity: float
    unit_price: float
    cgst_rate: float = 0.0
    sgst_rate: float = 0.0
    igst_rate: float = 0.0
    hsn_sac: Optional[str] = None
    unit: str = "Nos"


class CreateCreditNoteRequest(BaseModel):
    invoice_id: int
    lines: List[CreditNoteLine]
    note: Optional[str] = None


# ── Dependencies ──────────────────────────────────────────────────────────────

# restrict_cashier is the single guard in services.auth (imported above).


# ── Serializers ───────────────────────────────────────────────────────────────

def _payment_out(p: InvoicePayment) -> dict:
    return {
        "id": p.id,
        "invoice_id": p.invoice_id,
        "customer_id": p.customer_id,
        "amount_paid": p.amount_paid,
        "payment_mode": p.payment_mode,
        "payment_date": p.payment_date,
        "note": p.note,
        "idempotency_key": p.idempotency_key,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _invoice_out(inv: Invoice) -> dict:
    return {
        "id": inv.id,
        "invoice_no": inv.invoice_id,
        "customer": inv.customer,
        "invoice_date": inv.invoice_date,
        "status": inv.status,
        "place_of_supply": inv.place_of_supply,
        "invoice_type": inv.invoice_type,
        "reverse_charge": inv.reverse_charge,
        "is_tax_inclusive": inv.is_tax_inclusive,
        "subtotal": inv.subtotal,
        "discount_total": inv.discount_total,
        "cgst_total": inv.cgst_total,
        "sgst_total": inv.sgst_total,
        "igst_total": inv.igst_total,
        "cess_total": inv.cess_total,
        "round_off": inv.round_off,
        "total_amount": inv.total_amount,
        "paid_amount": inv.paid_amount,
        "payment_mode": inv.payment_mode,
        "lines": [
            {
                "product_id": li.product_id, "product_name": li.product_name,
                "hsn_sac": li.hsn_sac, "unit": li.unit,
                "quantity": li.quantity, "unit_price": li.unit_price,
                "discount": li.discount, "taxable_value": li.taxable_value,
                "cgst_amount": li.cgst_amount, "sgst_amount": li.sgst_amount,
                "igst_amount": li.igst_amount, "cess_amount": li.cess_amount,
                "line_total": li.line_total, "batch_no": li.batch_no, "serial_no": li.serial_no,
            }
            for li in inv.line_items
        ]
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/payments")
def list_payments(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """List all payments for the business."""
    bid = current_user["id"]
    payments = (
        db.query(InvoicePayment)
        .filter(InvoicePayment.business_id == bid)
        .order_by(InvoicePayment.created_at.desc())
        .all()
    )
    result = []
    for p in payments:
        inv = db.query(Invoice).filter(Invoice.id == p.invoice_id, Invoice.business_id == bid).first()
        inv_no = inv.invoice_id if inv else f"#{p.invoice_id}"
        
        party_name = inv.customer if inv else None
        if not party_name and p.customer_id:
            c = db.query(Customer).filter(Customer.id == p.customer_id, Customer.business_id == bid).first()
            if c:
                party_name = c.name
                
        result.append({
            "id": p.id,
            "date": p.payment_date or (p.created_at.strftime("%Y-%m-%d") if p.created_at else None),
            # Full timestamp (naive UTC) so the UI can show the receipt time in IST,
            # not just the date. formatISTDateTime falls back to date-only otherwise.
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "invoice_ref": inv_no,
            "invoice_number": inv_no,
            "party_name": party_name,
            "customer_name": party_name,
            "type": "received",
            "amount": p.amount_paid,
            "method": p.payment_mode or "Cash",
            "reference": p.note or p.idempotency_key or "",
        })
    return result


@router.get("/invoices/{invoice_id}/account")
def invoice_account(
    invoice_id: int,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Per-invoice money view for the invoice viewer: totals, amount paid,
    outstanding, the list of payment receipts, and any linked returns (credit
    notes that reference this invoice). Read-only."""
    bid = current_user["id"]
    inv = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.business_id == bid).first()
    if inv is None:
        raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

    payments = (
        db.query(InvoicePayment)
        .filter(InvoicePayment.business_id == bid, InvoicePayment.invoice_id == invoice_id)
        .order_by(InvoicePayment.created_at.asc())
        .all()
    )

    total = round(inv.total_amount or inv.amount or 0.0, 2)
    # Derive paid from the payment ledger (source of truth), not inv.paid_amount —
    # a stale synced invoice can leave that column at 0 while receipts exist (the
    # "Pending but already paid" bug). Fall back to the column only when there are
    # no ledger rows.
    paid = round(sum(p.amount_paid or 0.0 for p in payments), 2) if payments else round(inv.paid_amount or 0.0, 2)
    outstanding = round(max(total - paid, 0.0), 2)
    status = "Paid" if (total > 0 and paid >= total) else ("Partial" if paid > 0 else (inv.status or "Pending"))

    def _date_only(d):
        return str(d).split("T")[0].split(" ")[0] if d else None

    payment_rows = [{
        "id": p.id,
        "date": _date_only(p.payment_date) or (p.created_at.strftime("%Y-%m-%d") if p.created_at else None),
        "amount": round(p.amount_paid or 0.0, 2),
        "method": p.payment_mode or "Cash",
        "note": p.note or "",
    } for p in payments]

    # Returns: credit notes referencing this invoice via the exact note phrase
    # written by create_credit_note — "Credit note against <invoice_no>." The
    # trailing '.' is the delimiter that disambiguates numbers that are prefixes
    # of one another (a bare substring LIKE matched 'INV-1' against 'INV-10' /
    # 'INV-100', and could pull credit notes for unrelated invoices).
    returns = []
    if inv.invoice_id:
        marker = f"Credit note against {inv.invoice_id}."
        cns = (
            db.query(Invoice)
            .filter(Invoice.business_id == bid,
                    Invoice.invoice_type == "credit_note",
                    Invoice.notes.ilike(f"%{marker}%"))
            .all()
        )
        returns = [{
            "id": cn.id,
            "credit_note_no": cn.invoice_id,
            "date": cn.invoice_date,
            "amount": round(cn.total_amount or cn.amount or 0.0, 2),
        } for cn in cns]

    return {
        "invoice_id": inv.id,
        "invoice_no": inv.invoice_id,
        "status": status,
        "total": total,
        "paid": paid,
        "outstanding": outstanding,
        "payments": payment_rows,
        "returns": returns,
    }


@router.post("/payments", status_code=201)
def record_payment(
    req: RecordPaymentRequestFlexible,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
    guard: ReplayGuard = Depends(replay_guard),
):
    """Record payment receipt against an invoice. Supports both native and frontend schemas.
    Idempotent on the body `idempotency_key` (inner wall) AND, when sent, on the
    `X-Client-Request-Id` header (offline outbox replay — see core.sync.idempotency)."""
    bid = current_user["id"]
    payment_type = req.type or "received"

    hit = guard.replay()
    if hit is not None:
        return hit

    amt = req.amount if req.amount is not None else req.amount_paid
    if amt is None:
        raise HTTPException(status_code=422, detail="amount or amount_paid is required")
        
    mode = req.method or req.payment_mode or "Cash"
    p_date = req.date or req.payment_date
    p_note = req.reference or req.note
    
    inv_id = req.invoice_id
    inv = None
    if not inv_id and req.invoice_ref:
        inv = (
            db.query(Invoice)
            .filter(Invoice.business_id == bid, Invoice.invoice_id == req.invoice_ref)
            .first()
        )
        if inv:
            inv_id = inv.id
        else:
            try:
                potential_id = int(req.invoice_ref)
                inv = db.query(Invoice).filter(Invoice.id == potential_id, Invoice.business_id == bid).first()
                if inv:
                    inv_id = inv.id
            except ValueError:
                pass
    elif inv_id:
        inv = db.query(Invoice).filter(Invoice.id == inv_id, Invoice.business_id == bid).first()
                
    if not inv_id:
        raise HTTPException(status_code=422, detail=f"Invoice reference '{req.invoice_ref or req.invoice_id}' not found")

    # Shift stamping (Phase 3): a receipt taken while the operator has an open
    # shift counts toward that shift's drawer tally (credit collections too).
    from core.shifts import service as shifts_svc
    operator_id = current_user.get("user_id") or bid
    active_shift = shifts_svc.get_open_shift(db, business_id=bid, user_id=operator_id)

    try:
        p = billing.record_payment(
            db,
            business_id=bid,
            invoice_id=inv_id,
            amount_paid=amt,
            payment_mode=mode,
            payment_date=p_date,
            note=p_note,
            idempotency_key=req.idempotency_key,
            shift_id=(active_shift.id if active_shift else None),
        )
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "payment"})
        return guard.store({
            # Legacy/Test fields
            "id": p.id,
            "invoice_id": p.invoice_id,
            "customer_id": p.customer_id,
            "amount_paid": p.amount_paid,
            "payment_mode": p.payment_mode,
            "payment_date": p.payment_date,
            "note": p.note,
            "idempotency_key": p.idempotency_key,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            
            # Frontend fields
            "date": p.payment_date or (p.created_at.strftime("%Y-%m-%d") if p.created_at else None),
            "invoice_ref": req.invoice_ref or (inv.invoice_id if inv else str(inv_id)),
            "invoice_number": req.invoice_ref or (inv.invoice_id if inv else str(inv_id)),
            "party_name": inv.customer if inv else None,
            "customer_name": inv.customer if inv else None,
            "type": payment_type,
            "amount": p.amount_paid,
            "method": p.payment_mode,
            "reference": p.note or p.idempotency_key or "",
        }, status_code=201)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error("record_payment route failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not record payment")


@router.post("/credit-notes", status_code=201)
def create_credit_note(
    req: CreateCreditNoteRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Create a credit note invoice (atomic reversal, returns stock)."""
    bid = current_user["id"]
    try:
        lines = [l.model_dump() for l in req.lines]
        cn = billing.create_credit_note(
            db,
            business_id=bid,
            original_invoice_id=req.invoice_id,
            lines=lines,
            note=req.note,
        )
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "payment"})
        return _invoice_out(cn)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error("create_credit_note route failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create credit note")


# ── Expense Management Schemas & Endpoints ────────────────────────────────────

class CreateExpenseRequest(BaseModel):
    expense_date: str  # YYYY-MM-DD
    category: str
    expense_type: str  # Direct|Indirect
    amount: float
    payment_mode: str  # Cash|UPI|Bank
    note: Optional[str] = None


@router.get("/expenses")
def list_expenses(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    """List all expenses for the business."""
    bid = current_user["id"]
    expenses = db.query(Expense).filter(
        Expense.business_id == bid
    ).order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    
    return [
        {
            "id": exp.id,
            "expense_date": exp.expense_date,
            "category": exp.category,
            "expense_type": exp.expense_type,
            "amount": exp.amount,
            "payment_mode": exp.payment_mode,
            "note": exp.note,
            "created_at": exp.created_at.isoformat() if exp.created_at else None
        }
        for exp in expenses
    ]


@router.post("/expenses", status_code=201)
def create_expense(
    req: CreateExpenseRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    """Record a new business expense."""
    bid = current_user["id"]
    if req.amount <= 0:
        raise HTTPException(status_code=422, detail="Amount must be greater than zero")
    
    if req.expense_type not in ("Direct", "Indirect"):
        raise HTTPException(status_code=422, detail="Expense type must be Direct or Indirect")

    try:
        exp = Expense(
            business_id=bid,
            expense_date=req.expense_date,
            category=req.category,
            expense_type=req.expense_type,
            amount=req.amount,
            payment_mode=req.payment_mode,
            note=req.note
        )
        db.add(exp)
        db.flush()  # get exp.id for the journal posting
        # Post to the double-entry journal (Dr <Category> Expense, Cr Cash).
        from core.accounting import posting
        posting.post_expense(db, exp)
        db.commit()
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "payment"})
        db.refresh(exp)
        return {
            "id": exp.id,
            "expense_date": exp.expense_date,
            "category": exp.category,
            "expense_type": exp.expense_type,
            "amount": exp.amount,
            "payment_mode": exp.payment_mode,
            "note": exp.note,
            "created_at": exp.created_at.isoformat() if exp.created_at else None
        }
    except ValueError as ve:
        # Business-rule rejections (e.g. posting into a locked period) surface as
        # a clean 422 with the message, consistent with the other money routes.
        db.rollback()
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        db.rollback()
        logger.error("create_expense failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create expense")


@router.delete("/expenses/{expense_id}")
def delete_expense(
    expense_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    """Expenses are append-only financial records; use a reversal/void command."""
    bid = current_user["id"]
    exp = db.query(Expense).filter(
        Expense.id == expense_id,
        Expense.business_id == bid
    ).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")

    logger.warning(
        "delete_expense blocked for append-only financial record expense_id=%s biz=%s",
        expense_id,
        bid,
    )
    raise HTTPException(
        status_code=405,
        detail="Expenses are append-only financial records. Create a reversal/void entry instead.",
    )


# ── Credit Notes ──────────────────────────────────────────────────────────────

@router.get("/credit-notes")
def list_credit_notes(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    """Return all credit notes (return/reversal invoices) for the business."""
    bid = current_user["id"]
    cns = db.query(Invoice).filter(
        Invoice.business_id == bid,
        Invoice.invoice_type == "credit_note"
    ).order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).all()

    return [
        {
            "id": cn.id,
            "invoice_id": cn.invoice_id,
            "date": cn.invoice_date,
            "customer": cn.customer,
            "amount": cn.total_amount or cn.amount or 0,
            "status": cn.status,
            "reference_invoice": cn.reference_id,
            "note": cn.notes,
        }
        for cn in cns
    ]


# ── Pending / Overdue Invoices ─────────────────────────────────────────────────

@router.get("/pending-invoices")
def list_pending_invoices(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db)
):
    """Return all pending and overdue customer invoices (money owed to the business)."""
    from services.dates import biz_today_str
    bid = current_user["id"]
    today = biz_today_str()   # IST business date, not server-local
    # Match on lower-cased status: record_payment / create_sale_invoice write
    # "Partial" (capital P), but this filter used lowercase "partial" — so every
    # partially-settled invoice was silently dropped here while Contacts (balance
    # aggregation) and Invoices (raw status) still showed it as due. That's the
    # "Transactions says cleared, Contacts/Invoices say pending" mismatch.
    # Case-insensitive match + a positive-balance guard below keep this endpoint
    # a pure function of what's actually owed.
    invoices = db.query(Invoice).filter(
        Invoice.business_id == bid,
        Invoice.invoice_type != "credit_note",
        func.lower(Invoice.status).in_(["pending", "overdue", "partial"])
    ).order_by(Invoice.due_date.asc(), Invoice.id.desc()).all()

    # Derive "paid" from the payment ledger (source of truth), so an invoice whose
    # cached paid_amount is stale (e.g. a sync clobbered it back to 0) is still
    # correctly excluded once its receipts cover the total. Batched one query.
    inv_ids = [inv.id for inv in invoices]
    ledger_paid = {}
    if inv_ids:
        for iid, s in (db.query(InvoicePayment.invoice_id,
                                func.coalesce(func.sum(InvoicePayment.amount_paid), 0.0))
                       .filter(InvoicePayment.business_id == bid,
                               InvoicePayment.invoice_id.in_(inv_ids))
                       .group_by(InvoicePayment.invoice_id).all()):
            ledger_paid[iid] = round(s or 0.0, 2)

    result = []
    for inv in invoices:
        due = inv.due_date or ""
        total = inv.total_amount or inv.amount or 0
        # Ledger sum when the invoice has receipts; else the cached column.
        paid = ledger_paid.get(inv.id, round(inv.paid_amount or 0, 2))
        balance = round(max(total - paid, 0), 2)
        if balance <= 0.005:
            continue  # fully settled (per the ledger) — not a due
        is_overdue = due and due < today and (inv.status or "").lower() != "paid"
        result.append({
            "id": inv.id,
            "invoice_id": inv.invoice_id,
            "customer": inv.customer,
            "total_amount": total,
            "paid_amount": paid,
            "balance_due": balance,
            "due_date": due,
            "status": "Overdue" if is_overdue else inv.status,
            "invoice_date": inv.invoice_date,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        })
    return result


