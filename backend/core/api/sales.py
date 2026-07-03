"""
core/api/sales.py — thin HTTP layer over the billing command (Phase 1).
=======================================================================
Per FOUNDATION.md: routes stay thin. They authenticate, scope to the caller's
`business_id`, validate the request, and call the command/service. No business
logic here.

Lives under core/api/ (the billing ecosystem's HTTP layer) and is wired into
the app via core.api.core_router — the app entry point never imports it
directly.

  POST /sales                      create a sale invoice (the counter "Save Bill")
  GET  /sales/products/search?q=   item-master autocomplete for the counter
  GET  /sales/barcode/{code}       resolve a scanned barcode → product
  GET  /sales/{invoice_no}         fetch one invoice (with line items)
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Product, Invoice, InvoiceLineItem, User, Customer
from services.auth import get_active_user
from services.realtime import realtime_manager
from core.billing import commands as billing
from core.billing import print_payload as PP
from core.catalog import barcode as PB
from core import templates as T
from core.sync.idempotency import ReplayGuard, replay_guard

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.sales")


# ============================================================================
# ── SCHEMAS & REQUEST/RESPONSE MODELS ──
# ============================================================================

class SaleLine(BaseModel):
    product_id:   Optional[int] = None
    product_name: Optional[str] = None
    quantity:     float = 1.0
    unit_price:   float = 0.0
    discount:     Optional[float] = None
    discount_pct: Optional[float] = None
    hsn_sac:      Optional[str] = None
    unit:         Optional[str] = None
    batch_no:     Optional[str] = None
    expiry_date:  Optional[str] = None
    serial_no:    Optional[str] = None
    cgst_rate:    Optional[float] = None
    sgst_rate:    Optional[float] = None
    igst_rate:    Optional[float] = None
    cess_rate:    Optional[float] = None


class SaleRequest(BaseModel):
    lines:           List[SaleLine]
    customer:        Optional[str] = None
    customer_id:     Optional[int] = None
    invoice_no:      Optional[str] = None
    invoice_date:    Optional[str] = None
    due_date:        Optional[str] = None
    place_of_supply: Optional[str] = None
    invoice_type:    Optional[str] = None
    payment_mode:    Optional[str] = None
    paid_amount:     float = 0.0
    reverse_charge:  bool = False
    tax_inclusive:   Optional[bool] = None   # None → take the business config default
    device_id:       Optional[str] = None
    counter_prefix:  Optional[str] = None   # per-terminal invoice-number series (multi-counter POS §9.3)
    godown_id:       Optional[int] = None
    cash_discount:   float = 0.0   # POST-tax cash discount / round-off (₹) — reduces payable, not GST (R4)
    mark_paid:       bool = False   # "Paid & Print": settle the full payable exactly (status Paid)


# ── Serializers ──────────────────────────────────────────────────────────────

def _line_out(li: InvoiceLineItem) -> dict:
    return {
        "product_id": li.product_id, "product_name": li.product_name,
        "hsn_sac": li.hsn_sac, "unit": li.unit,
        "quantity": li.quantity, "unit_price": li.unit_price,
        "discount": li.discount, "taxable_value": li.taxable_value,
        "cgst_amount": li.cgst_amount, "sgst_amount": li.sgst_amount,
        "igst_amount": li.igst_amount, "cess_amount": li.cess_amount,
        "cgst_rate": li.cgst_rate, "sgst_rate": li.sgst_rate,
        "igst_rate": li.igst_rate, "cess_rate": li.cess_rate,
        "line_total": li.line_total, "batch_no": li.batch_no, "serial_no": li.serial_no,
    }


def _invoice_out(inv: Invoice) -> dict:
    return {
        "id": inv.id, "invoice_no": inv.invoice_id, "customer": inv.customer,
        "invoice_date": inv.invoice_date, "status": inv.status,
        "place_of_supply": inv.place_of_supply, "invoice_type": inv.invoice_type,
        "reverse_charge": inv.reverse_charge, "is_tax_inclusive": inv.is_tax_inclusive,
        "subtotal": inv.subtotal, "discount_total": inv.discount_total,
        "cgst_total": inv.cgst_total, "sgst_total": inv.sgst_total,
        "igst_total": inv.igst_total, "cess_total": inv.cess_total,
        "round_off": inv.round_off, "total_amount": inv.total_amount,
        "paid_amount": inv.paid_amount, "payment_mode": inv.payment_mode,
        "godown_id": inv.godown_id,
        "lines": [_line_out(li) for li in inv.line_items],
    }


def _product_out(p: Product) -> dict:
    return {
        "id": p.id, "name": p.name, "sku": p.sku, "unit": p.unit,
        "barcode": p.barcode, "hsn_sac": p.hsn_sac,
        "selling_price": p.selling_price, "mrp": p.mrp,
        "cgst_rate": p.cgst_rate, "sgst_rate": p.sgst_rate, "igst_rate": p.igst_rate,
        "track_inventory": p.track_inventory, "price_includes_tax": p.price_includes_tax,
    }


# ============================================================================
# ── ENDPOINT ROUTE HANDLERS ──
# ============================================================================

@router.post("/sales")
def create_sale(req: SaleRequest,
                background_tasks: BackgroundTasks,
                current_user: dict = Depends(get_active_user),
                db: Session = Depends(get_db),
                guard: ReplayGuard = Depends(replay_guard)):
    """Create a sale invoice (atomic: invoice + lines + stock). Idempotent on
    invoice_no AND, when the client sends X-Client-Request-Id, on that key (the
    offline outbox replay guard — see core.sync.idempotency)."""
    bid = current_user["id"]

    # Outer wall: an offline-replay/retry of an already-processed request returns
    # the stored response verbatim instead of re-doing the work.
    hit = guard.replay()
    if hit is not None:
        return hit

    if not req.lines:
        raise HTTPException(status_code=422, detail="at least one line is required")

    # tax_inclusive: honour an explicit client value; otherwise fall back to the
    # business's vertical config (e.g. pharmacy/supermarket bill on MRP-inclusive).
    tax_inclusive = req.tax_inclusive
    if tax_inclusive is None:
        cfg = T.resolve_for(bid, db)
        tax_inclusive = bool(cfg.get("billing", {}).get("tax_inclusive_default", False))

    try:
        inv = billing.create_sale_invoice(
            db, business_id=bid,
            lines=[l.model_dump(exclude_none=True) for l in req.lines],
            customer=req.customer, customer_id=req.customer_id,
            invoice_no=req.invoice_no, invoice_date=req.invoice_date, due_date=req.due_date,
            place_of_supply=req.place_of_supply, invoice_type=req.invoice_type,
            payment_mode=req.payment_mode, paid_amount=req.paid_amount,
            reverse_charge=req.reverse_charge, tax_inclusive=tax_inclusive,
            device_id=req.device_id, counter_prefix=req.counter_prefix, godown_id=req.godown_id,
            renumber_on_conflict=guard.active,
            cash_discount=req.cash_discount, mark_paid=req.mark_paid,
        )
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "invoice"})
        return guard.store(_invoice_out(inv))
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        db.rollback()
        logger.error("create_sale failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create the sale.")


@router.get("/sales/products/search")
def search_products(q: str = "", limit: int = 20,
                    current_user: dict = Depends(get_active_user),
                    db: Session = Depends(get_db)):
    """Item-master autocomplete for the counter — match name / SKU, or resolve an
    exact barcode first so a scan jumps straight to the product."""
    bid = current_user["id"]
    q = (q or "").strip()
    if not q:
        return {"items": []}

    # Exact barcode hit jumps to the top.
    hit = PB.resolve_barcode(db, bid, q)
    results = []
    if hit is not None:
        results.append(_product_out(hit))

    like = f"%{q}%"
    rows = (
        db.query(Product)
        .filter(Product.business_id == bid, Product.is_active == True,  # noqa: E712
                or_(Product.name.ilike(like), Product.sku.ilike(like)))
        .order_by(Product.name.asc())
        .limit(min(limit, 50))
        .all()
    )
    seen = {r["id"] for r in results}
    for p in rows:
        if p.id not in seen:
            results.append(_product_out(p))
    return {"items": results[:limit]}


@router.get("/sales/barcode/{code}")
def resolve_barcode(code: str,
                    current_user: dict = Depends(get_active_user),
                    db: Session = Depends(get_db)):
    """Scan → product, or 404 if the code is unknown/retired."""
    p = PB.resolve_barcode(db, current_user["id"], code)
    if p is None:
        raise HTTPException(status_code=404, detail=f"No product for barcode '{code}'")
    return _product_out(p)


@router.get("/sales/{invoice_no}")
def get_sale(invoice_no: str,
             current_user: dict = Depends(get_active_user),
             db: Session = Depends(get_db)):
    """Fetch one invoice (with line items), scoped to the caller's business."""
    inv = (
        db.query(Invoice)
        .filter(Invoice.business_id == current_user["id"], Invoice.invoice_id == invoice_no)
        .first()
    )
    if inv is None:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_no}' not found")
    return _invoice_out(inv)


# ── Invoice-template system (plan Phase 1) ───────────────────────────────────

@router.get("/sales/{invoice_no}/print-payload")
def get_print_payload(invoice_no: str,
                      current_user: dict = Depends(get_active_user),
                      db: Session = Depends(get_db)):
    """The normalized InvoicePrintPayload v1 — the ONE payload every invoice
    template (Classic / Modern / Thermal) renders from. Pure read; templates
    never recompute money. See core/billing/print_payload.py."""
    bid = current_user["id"]
    try:
        return PP.build_print_payload(db, business_id=bid, invoice_no=invoice_no,
                                      user_id=current_user.get("user_id") or bid)
    except LookupError:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_no}' not found")
    except Exception as e:
        logger.error("print-payload failed for %s: %s", invoice_no, e, exc_info=True)
        PP.log_event("payload_failed", business_id=bid, success=False, error=str(e)[:200])
        raise HTTPException(status_code=500, detail="Could not build the invoice payload.")


class PrintEvent(BaseModel):
    """Client-side render lifecycle beacon (plan §1.3). Fire-and-forget: the
    frontend never blocks printing on this call."""
    action:        str                      # template_selected|print_opened|pdf_generated|pdf_failed|shared|template_fallback_used|print_render_failed
    invoice_no:    Optional[str] = None
    template_type: Optional[str] = None
    success:       bool = True
    error:         Optional[str] = None
    extra:         Optional[dict] = None

_ALLOWED_PRINT_EVENTS = {
    "template_selected", "print_opened", "pdf_generated", "pdf_failed",
    "shared", "template_fallback_used", "print_render_failed",
    "print_settings_saved",
}

@router.post("/sales/print-events")
def post_print_event(ev: PrintEvent,
                     current_user: dict = Depends(get_active_user),
                     db: Session = Depends(get_db)):
    """Structured log sink for client-side invoice-render events."""
    if ev.action not in _ALLOWED_PRINT_EVENTS:
        raise HTTPException(status_code=422, detail=f"Unknown print event '{ev.action}'")
    bid = current_user["id"]
    biz_type = None
    try:
        biz_type = T.resolve_for(bid, db).get("key")
    except Exception:
        pass
    extra = {k: str(v)[:120] for k, v in (ev.extra or {}).items() if v is not None}
    PP.log_event(ev.action, business_id=bid,
                 user_id=current_user.get("user_id") or bid,
                 invoice_id=ev.invoice_no, template_type=ev.template_type,
                 business_type=biz_type, success=ev.success,
                 error=(ev.error or None), **extra)
    return {"ok": True}


import os
from jinja2 import Environment, FileSystemLoader

# Set up Jinja2 environment pointing to backend/core/billing/templates
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "billing", "templates")
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR))

@router.get("/sales/{invoice_no}/pdf")
def get_invoice_pdf(
    invoice_no: str,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Fetch invoice as PDF (or HTML fallback if WeasyPrint is not installed)."""
    bid = current_user["id"]
    inv = (
        db.query(Invoice)
        .filter(Invoice.business_id == bid, Invoice.invoice_id == invoice_no)
        .first()
    )
    if inv is None:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_no}' not found")
        
    payload = PP.build_print_payload(db, business_id=bid, invoice_no=invoice_no, user_id=current_user.get("user_id") or bid)
    
    # Select template (fallback to classic A4)
    template_name = "invoice_classic_a4.html" 
    if inv.print_template == "thermal":
        template_name = "invoice_thermal.html"
        
    try:
        template = _jinja_env.get_template(template_name)
    except Exception:
        template = _jinja_env.get_template("invoice_classic_a4.html")
        
    html_content = template.render(payload=payload, **payload)
    
    try:
        import weasyprint
        pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
        from fastapi import Response
        PP.log_event("pdf_generated", business_id=bid, user_id=current_user.get("user_id") or bid, invoice_id=invoice_no, success=True)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=invoice_{invoice_no}.pdf"
            }
        )
    except Exception as e:
        # Fallback to serving the printable HTML directly
        PP.log_event("pdf_failed", business_id=bid, user_id=current_user.get("user_id") or bid, invoice_id=invoice_no, success=False, error=str(e))
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=html_content)


# ── Frontend Specific Integrations (Traditional Dashboard) ───────────────────

class FrontendInvoiceItem(BaseModel):
    product: str
    qty: float
    price: float
    product_id: Optional[int] = None
    cgst_rate: Optional[float] = None
    sgst_rate: Optional[float] = None
    igst_rate: Optional[float] = None
    batch_no: Optional[str] = None
    expiry_date: Optional[str] = None
    serial_no: Optional[str] = None   # electronics/mobile/repair verticals (Phase 2 line fields)
    attributes: Optional[dict] = None  # dynamic vertical fields (size/colour/warranty…) → JSON snapshot

class FrontendInvoiceRequest(BaseModel):
    customer_id: Optional[int] = None
    due_date: Optional[str] = None
    items: List[FrontendInvoiceItem]
    gst_enabled: bool = False
    notes: Optional[str] = None
    invoice_no: Optional[str] = None
    counter_prefix: Optional[str] = None   # per-terminal invoice-number series (multi-counter POS §9.3)
    bill_discount: float = 0.0   # whole-invoice PRE-tax discount (absolute ₹), resolved on the client
    cash_discount: float = 0.0   # POST-tax cash discount / round-off (₹) — reduces payable, not GST (R4)
    paid_amount: float = 0.0     # amount received now → Paid/Partial/Unpaid status (default 0 = unpaid)
    mark_paid: bool = False      # "Paid & Print": settle the full payable exactly (status Paid)
    payment_mode: Optional[str] = None  # cash|upi|card|credit — drives shift drawer tallies (Phase 3)


def _invoice_out_for_frontend(inv: Invoice) -> dict:
    return {
        "id": inv.id,
        "invoice_number": inv.invoice_id,
        "invoice_no": inv.invoice_id,
        "customer_name": inv.customer,
        "customer": inv.customer,
        "customer_id": inv.customer_id,
        "date": inv.invoice_date,
        "invoice_date": inv.invoice_date,
        "status": inv.status,
        "total_amount": inv.total_amount,
        "paid_amount": inv.paid_amount,
        "item_count": len(inv.line_items) if inv.line_items else 0,
        "notes": inv.notes,
        "invoice_type": inv.invoice_type
    }


@router.get("/invoices")
def list_invoices(
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """List all invoices for the business."""
    bid = current_user["id"]
    invoices = (
        db.query(Invoice)
        .filter(Invoice.business_id == bid)
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .all()
    )
    return [_invoice_out_for_frontend(inv) for inv in invoices]


@router.post("/invoices", status_code=201)
def create_sale_invoice_frontend(
    req: FrontendInvoiceRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
    guard: ReplayGuard = Depends(replay_guard),
):
    """The POS counter "Save Bill" path. Idempotent on invoice_no (inner wall) AND,
    when the offline outbox replays it, on the `X-Client-Request-Id` header (outer
    wall — see core.sync.idempotency). This is the route the client outbox flushes."""
    bid = current_user["id"]

    hit = guard.replay()
    if hit is not None:
        return hit

    # ── Shift gatekeeper (Phase 3): EVERY role — cashier AND owner — needs an
    # OPEN shift to ring a sale; that's what makes end-of-day tallies exact.
    # Offline bills are rung under an open shift too (the POS gate runs before
    # the outbox), so replays normally land while it's still open.
    from core.shifts import service as shifts_svc
    operator_id = current_user.get("user_id") or bid
    try:
        active_shift = shifts_svc.require_open_shift(db, business_id=bid, user_id=operator_id)
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="shift_required: open a register shift before billing.")

    # Resolve customer name
    customer_name = None
    if req.customer_id:
        cust = db.query(Customer).filter(Customer.id == req.customer_id, Customer.business_id == bid).first()
        if cust:
            customer_name = cust.name
            
    # Map lines
    lines = []
    for it in req.items:
        lines.append({
            "product_id": it.product_id,
            "product_name": it.product,
            "quantity": it.qty,
            "unit_price": it.price,
            "cgst_rate": it.cgst_rate,
            "sgst_rate": it.sgst_rate,
            "igst_rate": it.igst_rate,
            "batch_no": it.batch_no,
            "expiry_date": it.expiry_date,
            "serial_no": it.serial_no,
            "attributes": it.attributes
        })
        
    try:
        inv = billing.create_sale_invoice(
            db,
            business_id=bid,
            lines=lines,
            customer=customer_name,
            customer_id=req.customer_id,
            due_date=req.due_date,
            tax_inclusive=False,
            invoice_no=req.invoice_no,
            counter_prefix=req.counter_prefix,
            renumber_on_conflict=guard.active,  # §9.3b

            bill_discount=req.bill_discount,
            cash_discount=req.cash_discount,
            paid_amount=req.paid_amount,
            mark_paid=req.mark_paid,
            payment_mode=req.payment_mode,
            shift_id=active_shift.id,
        )
        if req.notes:
            inv.notes = req.notes
            db.commit()
            db.refresh(inv)

        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "invoice"})
        background_tasks.add_task(realtime_manager.broadcast, bid, {"type": "sync.trigger", "entity": "payment"})
        return guard.store(_invoice_out_for_frontend(inv), status_code=201)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        db.rollback()
        logger.error("create_invoice_frontend failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create invoice.")
