import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import PurchaseInvoice, PurchaseInvoiceLineItem, User
from services.auth import get_active_user, restrict_cashier
from services.purchase_ocr import parse_purchase_file
from services.purchase_mapper import map_purchase_items_to_catalog
from core.purchase import commands as purchase_commands
from core.sync.idempotency import ReplayGuard, replay_guard
from services.realtime import realtime_manager

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.purchases")


# ── Helper Serializers ────────────────────────────────────────────────────────

def _line_out(li: PurchaseInvoiceLineItem) -> dict:
    return {
        "id": li.id,
        "product_id": li.product_id,
        "product_name": li.product_name,
        "hsn_sac": li.hsn_sac,
        "unit": li.unit,
        "quantity": li.quantity,
        "purchase_unit": li.purchase_unit,
        "conversion_factor": li.conversion_factor,
        "unit_price": li.unit_price,
        "cgst_rate": li.cgst_rate,
        "sgst_rate": li.sgst_rate,
        "igst_rate": li.igst_rate,
        "taxable_value": li.taxable_value,
        "cgst_amount": li.cgst_amount,
        "sgst_amount": li.sgst_amount,
        "igst_amount": li.igst_amount,
        "line_total": li.line_total,
        "batch": li.batch,
        "expiry": li.expiry,
        "confidence_score": li.confidence_score,
        "is_matched": li.is_matched
    }


def _invoice_out(inv: PurchaseInvoice) -> dict:
    return {
        "id": inv.id,
        "supplier_id": inv.supplier_id,
        "supplier_name": inv.supplier_name,
        "invoice_number": inv.invoice_number,
        "invoice_date": inv.invoice_date,
        "due_date": inv.due_date,
        "status": inv.status,
        "notes": inv.notes,
        "file_id": inv.file_id,
        "gstin_buyer": inv.gstin_buyer,
        "place_of_supply": inv.place_of_supply,
        "invoice_type": inv.invoice_type,
        "subtotal": inv.subtotal,
        "cgst_total": inv.cgst_total,
        "sgst_total": inv.sgst_total,
        "igst_total": inv.igst_total,
        "cess_total": inv.cess_total,
        "total_amount": inv.total_amount,
        "reverse_charge": inv.reverse_charge,
        "is_tax_inclusive": inv.is_tax_inclusive,
        "discount_total": inv.discount_total,
        "round_off": inv.round_off,
        "irn": inv.irn,
        "ack_no": inv.ack_no,
        "ack_date": inv.ack_date,
        "qr_code": inv.qr_code,
        "godown_id": inv.godown_id,
        "lines": [_line_out(li) for li in inv.line_items]
    }


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/purchases/upload")
async def upload_purchase_bill(
    file: UploadFile = File(...),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db)
):
    """Upload a supplier invoice file (PDF/Image) and parse it into a structured JSON draft."""
    if current_user.get("role") == "cashier":
        raise HTTPException(status_code=403, detail="Permission denied: cashiers cannot upload supplier bills.")

    bid = current_user["id"]
    try:
        content = await file.read()
        parsed_invoice = parse_purchase_file(content, file.filename)
        
        # Fuzzy catalog match on the parsed line items
        items = parsed_invoice.get("items", [])
        mapped_items = map_purchase_items_to_catalog(db, bid, items)
        parsed_invoice["items"] = mapped_items
        
        return parsed_invoice
    except ValueError as ve:
        logger.warning("Upload bill validation failed: %s", ve)
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        logger.error("Upload bill failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to parse bill file: {str(e)}")


@router.post("/purchases/confirm")
def confirm_purchase_invoice(
    payload: dict,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
    guard: ReplayGuard = Depends(replay_guard),
):
    """Confirm a reviewed purchase invoice draft and save it to the database + stock ledger.
    Idempotent on (business_id, supplier_id, invoice_number) (inner wall) AND, when
    sent, on the `X-Client-Request-Id` header (offline replay — core.sync.idempotency)."""
    if current_user.get("role") == "cashier":
        raise HTTPException(status_code=403, detail="Permission denied: cashiers cannot record purchases.")

    bid = current_user["id"]

    hit = guard.replay()
    if hit is not None:
        return hit

    try:
        inv = purchase_commands.accept_supplier_invoice(db, bid, payload)
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "purchase"})
        return guard.store(_invoice_out(inv))
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        db.rollback()
        logger.error("Confirm purchase invoice failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not confirm the purchase invoice.")


@router.get("/purchases")
def list_purchases(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db)
):
    """List all purchase invoices for the current business."""
    if current_user.get("role") == "cashier":
        raise HTTPException(status_code=403, detail="Permission denied: cashiers cannot view purchase history.")

    bid = current_user["id"]
    invoices = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.business_id == bid,
        (PurchaseInvoice.invoice_type != "debit_note") | (PurchaseInvoice.invoice_type.is_(None))
    ).order_by(PurchaseInvoice.id.desc()).all()
    
    return [_invoice_out(inv) for inv in invoices]


@router.get("/purchases/debit-notes")
def list_debit_notes(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db)
):
    """List all debit notes (purchase returns) for the business."""
    if current_user.get("role") == "cashier":
        raise HTTPException(status_code=403, detail="Permission denied: cashiers cannot view purchase returns.")

    bid = current_user["id"]
    notes = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.business_id == bid,
        PurchaseInvoice.invoice_type == "debit_note"
    ).order_by(PurchaseInvoice.id.desc()).all()
    
    return [_invoice_out(n) for n in notes]


@router.get("/purchases/{purchase_id}")
def get_purchase_detail(
    purchase_id: int,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db)
):
    """Retrieve details for a single purchase invoice."""
    if current_user.get("role") == "cashier":
        raise HTTPException(status_code=403, detail="Permission denied: cashiers cannot view purchase details.")

    bid = current_user["id"]
    inv = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.id == purchase_id,
        PurchaseInvoice.business_id == bid
    ).first()
    
    if not inv:
        raise HTTPException(status_code=404, detail="Purchase invoice not found.")
        
    return _invoice_out(inv)


# ── Debit Notes Schemas & Endpoints ──────────────────────────────────────────

class DebitNoteLine(BaseModel):
    product_id: int
    quantity: float
    reason: Optional[str] = "return"


class CreateDebitNoteRequest(BaseModel):
    original_purchase_id: int
    debit_note_number: Optional[str] = None
    lines: List[DebitNoteLine]
    note: Optional[str] = None


@router.post("/purchases/debit-notes", status_code=201)
def create_debit_note(
    req: CreateDebitNoteRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db)
):
    """Record a purchase return / debit note against a purchase invoice."""
    if current_user.get("role") == "cashier":
        raise HTTPException(status_code=403, detail="Permission denied: cashiers cannot record returns.")

    bid = current_user["id"]
    try:
        lines = [line.model_dump() for line in req.lines]
        dn = purchase_commands.create_debit_note(
            db,
            business_id=bid,
            original_purchase_id=req.original_purchase_id,
            lines=lines,
            note=req.note,
            debit_note_no=req.debit_note_number
        )
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "purchase"})
        return _invoice_out(dn)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        db.rollback()
        logger.error("create_debit_note route failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create debit note")

