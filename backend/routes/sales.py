"""
routes/sales.py — thin HTTP layer over the billing command (Phase 1).
=====================================================================
Per FOUNDATION.md: routes stay thin. They authenticate, scope to the caller's
`business_id`, validate the request, and call the command/service. No business
logic here.

  POST /sales                      create a sale invoice (the counter "Save Bill")
  GET  /sales/products/search?q=   item-master autocomplete for the counter
  GET  /sales/barcode/{code}       resolve a scanned barcode → product
  GET  /sales/{invoice_no}         fetch one invoice (with line items)
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Product, Invoice, InvoiceLineItem
from services.auth import get_active_user
from core.billing import commands as billing
from core.catalog import barcode as PB

router = APIRouter()
logger = logging.getLogger("bizassist.routes.sales")


# ── Schemas ──────────────────────────────────────────────────────────────────

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
    serial_no:    Optional[str] = None
    expiry_date:  Optional[str] = None
    mrp:          Optional[float] = None
    attributes:   Optional[dict] = None   # vertical fields (size/colour/warranty…)
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
    tax_inclusive:   bool = False
    device_id:       Optional[str] = None


# ── Serializers ──────────────────────────────────────────────────────────────

def _line_out(li: InvoiceLineItem) -> dict:
    return {
        "product_id": li.product_id, "product_name": li.product_name,
        "hsn_sac": li.hsn_sac, "unit": li.unit,
        "quantity": li.quantity, "unit_price": li.unit_price,
        "discount": li.discount, "taxable_value": li.taxable_value,
        "cgst_amount": li.cgst_amount, "sgst_amount": li.sgst_amount,
        "igst_amount": li.igst_amount, "cess_amount": li.cess_amount,
        "line_total": li.line_total, "batch_no": li.batch_no, "serial_no": li.serial_no,
        "expiry_date": li.expiry_date, "mrp": li.mrp, "attributes": li.attributes,
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


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/sales")
def create_sale(req: SaleRequest,
                current_user: dict = Depends(get_active_user),
                db: Session = Depends(get_db)):
    """Create a sale invoice (atomic: invoice + lines + stock). Idempotent on invoice_no."""
    bid = current_user["id"]
    if not req.lines:
        raise HTTPException(status_code=422, detail="at least one line is required")
    # Shift stamping (Phase 3): the POS route (core/api/sales.py POST /invoices)
    # STRICTLY requires an open shift; this native API tags the sale with the
    # caller's open shift when one exists so it still enters the drawer tally.
    from core.shifts import service as shifts_svc
    operator_id = current_user.get("user_id") or bid
    active_shift = shifts_svc.get_open_shift(db, business_id=bid, user_id=operator_id)
    try:
        inv = billing.create_sale_invoice(
            db, business_id=bid,
            lines=[l.dict(exclude_none=True) for l in req.lines],
            shift_id=(active_shift.id if active_shift else None),
            customer=req.customer, customer_id=req.customer_id,
            invoice_no=req.invoice_no, invoice_date=req.invoice_date, due_date=req.due_date,
            place_of_supply=req.place_of_supply, invoice_type=req.invoice_type,
            payment_mode=req.payment_mode, paid_amount=req.paid_amount,
            reverse_charge=req.reverse_charge, tax_inclusive=req.tax_inclusive,
            device_id=req.device_id,
        )
        return _invoice_out(inv)
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
    inv = (
        db.query(Invoice)
        .filter(Invoice.business_id == current_user["id"], Invoice.invoice_id == invoice_no)
        .first()
    )
    if inv is None:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_no}' not found")
    return _invoice_out(inv)
