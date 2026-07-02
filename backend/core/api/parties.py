"""
core/api/parties.py — Customers & Vendors HTTP layer (Phase 1B).
================================================================
Covers BOTH customers (buyers) and vendors (suppliers) in one file since
the patterns are identical and sharing avoids duplication.

Outstanding dues = SUM(invoice.total_amount) - SUM(invoice.paid_amount) across
all invoices for that customer (read-only, deterministic SQL).

  GET  /customers?q=&page=        paginated customers
  POST /customers                  create customer
  GET  /customers/{id}             customer + outstanding dues
  PATCH /customers/{id}            update customer
  GET  /customers/{id}/ledger      invoices + payments for a customer

  GET  /vendors?q=&page=           paginated vendors
  POST /vendors                    create vendor
  GET  /vendors/{id}               vendor details
  PATCH /vendors/{id}              update vendor
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Customer, Vendor, Invoice
from services.auth import get_active_user
from services.realtime import realtime_manager, delta_event

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.parties")


# ── Customer Schemas ─────────────────────────────────────────────────────────

class CreateCustomer(BaseModel):
    name: str
    gstin: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    state_code: Optional[str] = None
    pan: Optional[str] = None
    credit_limit: float = 0.0
    credit_days: int = 30
    price_tier: Optional[str] = "standard"


class UpdateCustomer(BaseModel):
    name: Optional[str] = None
    gstin: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    state_code: Optional[str] = None
    pan: Optional[str] = None
    credit_limit: Optional[float] = None
    credit_days: Optional[int] = None
    price_tier: Optional[str] = None
    is_active: Optional[bool] = None


# ── Vendor Schemas ─────────────────────────────────────────────────────────

class CreateVendor(BaseModel):
    name: str
    gstin: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    state_code: Optional[str] = None
    pan: Optional[str] = None
    payment_terms_days: int = 30


class UpdateVendor(BaseModel):
    name: Optional[str] = None
    gstin: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    state_code: Optional[str] = None
    pan: Optional[str] = None
    payment_terms_days: Optional[int] = None
    last_gstr1_filed: Optional[str] = None
    filing_reliability: Optional[float] = None
    is_active: Optional[bool] = None


# ── Serializers ───────────────────────────────────────────────────────────────

def _customer_out(c: Customer, outstanding: float = 0.0, last_invoice_date: Optional[str] = None) -> dict:
    return {
        "id": c.id, "name": c.name, "gstin": c.gstin,
        "phone": c.phone, "email": c.email, "address": c.address,
        "state_code": c.state_code, "pan": c.pan,
        "credit_limit": c.credit_limit, "credit_days": c.credit_days,
        "price_tier": getattr(c, "price_tier", "standard"),
        "is_active": c.is_active,
        "outstanding_dues": round(outstanding, 2),
        "outstanding_balance": round(outstanding, 2),
        "last_invoice_date": last_invoice_date,
    }


def _vendor_out(v: Vendor, outstanding: float = 0.0, last_purchase_date: Optional[str] = None) -> dict:
    return {
        "id": v.id, "name": v.name, "gstin": v.gstin,
        "phone": v.phone, "email": v.email, "address": v.address,
        "state_code": v.state_code, "pan": v.pan,
        "payment_terms_days": v.payment_terms_days,
        "last_gstr1_filed": v.last_gstr1_filed,
        "filing_reliability": v.filing_reliability,
        "is_active": v.is_active,
        "outstanding_balance": round(outstanding, 2),
        "last_purchase_date": last_purchase_date,
    }


def _compute_vendor_stats(db: Session, business_id: int, vendor_id: int) -> tuple:
    """
    Outstanding = SUM(total_amount) for all unpaid/pending purchase invoices.
    Returns (outstanding, last_purchase_date).
    """
    from database.models import PurchaseInvoice
    row = (
        db.query(
            func.coalesce(func.sum(PurchaseInvoice.total_amount), 0.0),
            func.max(PurchaseInvoice.invoice_date)
        )
        .filter(
            PurchaseInvoice.business_id == business_id,
            PurchaseInvoice.supplier_id == vendor_id,
            PurchaseInvoice.status != "Paid",
        )
        .first()
    )
    
    # We also need the MAX(invoice_date) regardless of status
    last_date_row = (
        db.query(func.max(PurchaseInvoice.invoice_date))
        .filter(
            PurchaseInvoice.business_id == business_id,
            PurchaseInvoice.supplier_id == vendor_id,
        )
        .first()
    )
    
    if not row:
        return 0.0, None
    total_unpaid, _ = row
    last_date = last_date_row[0] if last_date_row else None
    return float(total_unpaid or 0), last_date


def _compute_customer_stats(db: Session, business_id: int, customer_id: int) -> tuple:
    """
    Outstanding = SUM(total_amount) - SUM(paid_amount) for all non-credit-note
    invoices of this customer. Read-only, deterministic SQL.
    Returns (outstanding, last_invoice_date).
    """
    row = (
        db.query(
            func.coalesce(func.sum(Invoice.total_amount), 0.0),
            func.coalesce(func.sum(Invoice.paid_amount), 0.0),
            func.max(Invoice.invoice_date)
        )
        .filter(
            Invoice.business_id == business_id,
            Invoice.customer_id == customer_id,
            Invoice.invoice_type != "credit_note",
        )
        .first()
    )
    if row is None:
        return 0.0, None
    total, paid, last_date = row
    return max(float(total or 0) - float(paid or 0), 0.0), last_date


# ── Customer Routes ───────────────────────────────────────────────────────────

@router.get("/customers")
def list_customers(
    q: str = "",
    page: int = 1,
    per_page: int = 20,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Paginated customers list scoped to business."""
    bid = current_user["id"]
    query = db.query(Customer).filter(Customer.business_id == bid)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Customer.name.ilike(like), Customer.phone.ilike(like),
                Customer.email.ilike(like), Customer.gstin.ilike(like))
        )

    total = query.count()
    items = (
        query.order_by(Customer.name.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "total": total, "page": page, "per_page": per_page,
        "items": [_customer_out(c, *_compute_customer_stats(db, bid, c.id)) for c in items],
    }


@router.post("/customers", status_code=201)
def create_customer(
    req: CreateCustomer,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Create a new customer record."""
    bid = current_user["id"]
    c = Customer(
        business_id=bid,
        name=req.name, gstin=req.gstin, phone=req.phone,
        email=req.email, address=req.address, state_code=req.state_code,
        pan=req.pan, credit_limit=req.credit_limit, credit_days=req.credit_days,
        price_tier=req.price_tier or "standard",
        is_active=True,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    dto = _customer_out(c)
    background_tasks.add_task(
        realtime_manager.broadcast, bid,
        delta_event("party", payload=dto, kind="customer", rid=c.id, uid=getattr(c, "uid", None)),
    )
    logger.info("[PARTIES] created customer %s (biz=%s)", c.id, bid)
    return dto


@router.get("/customers/{customer_id}")
def get_customer(
    customer_id: int,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Customer detail with current outstanding dues."""
    bid = current_user["id"]
    c = db.query(Customer).filter(
        Customer.id == customer_id, Customer.business_id == bid
    ).first()
    if c is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    outstanding, last_date = _compute_customer_stats(db, bid, customer_id)
    return _customer_out(c, outstanding, last_date)


@router.patch("/customers/{customer_id}")
def update_customer(
    customer_id: int,
    req: UpdateCustomer,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Update customer fields (no money history touched)."""
    bid = current_user["id"]
    c = db.query(Customer).filter(
        Customer.id == customer_id, Customer.business_id == bid
    ).first()
    if c is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    data = req.model_dump(exclude_none=True)
    for field, val in data.items():
        if hasattr(c, field):
            setattr(c, field, val)

    db.commit()
    db.refresh(c)
    outstanding, last_date = _compute_customer_stats(db, bid, customer_id)
    dto = _customer_out(c, outstanding, last_date)
    background_tasks.add_task(
        realtime_manager.broadcast, bid,
        delta_event("party", payload=dto, kind="customer", rid=c.id, uid=getattr(c, "uid", None)),
    )
    return dto


@router.get("/customers/{customer_id}/ledger")
def customer_ledger(
    customer_id: int,
    page: int = 1,
    per_page: int = 20,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """List of invoices and payments for a customer (account statement)."""
    bid = current_user["id"]
    c = db.query(Customer).filter(
        Customer.id == customer_id, Customer.business_id == bid
    ).first()
    if c is None:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

    inv_q = db.query(Invoice).filter(
        Invoice.business_id == bid,
        Invoice.customer_id == customer_id,
    ).order_by(Invoice.invoice_date.desc())

    total = inv_q.count()
    invoices = inv_q.offset((page - 1) * per_page).limit(per_page).all()

    entries = []
    for inv in invoices:
        entries.append({
            "type": "invoice",
            "invoice_no": inv.invoice_id,
            "invoice_id": inv.id,
            "date": inv.invoice_date,
            "due_date": inv.due_date,
            "total_amount": inv.total_amount,
            "paid_amount": inv.paid_amount,
            "outstanding": max((inv.total_amount or 0) - (inv.paid_amount or 0), 0),
            "status": inv.status,
        })

    outstanding_total, _ = _compute_customer_stats(db, bid, customer_id)
    return {
        "customer_id": customer_id,
        "customer_name": c.name,
        "outstanding_total": round(outstanding_total, 2),
        "total": total, "page": page, "per_page": per_page,
        "entries": entries,
    }


# ── Vendor Routes ──────────────────────────────────────────────────────────────

@router.get("/vendors")
def list_vendors(
    q: str = "",
    page: int = 1,
    per_page: int = 20,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Paginated vendors list scoped to business."""
    bid = current_user["id"]
    query = db.query(Vendor).filter(Vendor.business_id == bid)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Vendor.name.ilike(like), Vendor.phone.ilike(like),
                Vendor.email.ilike(like), Vendor.gstin.ilike(like))
        )

    total = query.count()
    items = (
        query.order_by(Vendor.name.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "total": total, "page": page, "per_page": per_page,
        "items": [_vendor_out(v, *_compute_vendor_stats(db, bid, v.id)) for v in items],
    }


@router.post("/vendors", status_code=201)
def create_vendor(
    req: CreateVendor,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Create a new vendor/supplier record."""
    bid = current_user["id"]
    v = Vendor(
        business_id=bid,
        name=req.name, gstin=req.gstin, phone=req.phone,
        email=req.email, address=req.address, state_code=req.state_code,
        pan=req.pan, payment_terms_days=req.payment_terms_days,
        is_active=True,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    dto = _vendor_out(v, 0.0, None)
    background_tasks.add_task(
        realtime_manager.broadcast, bid,
        delta_event("party", payload=dto, kind="vendor", rid=v.id, uid=getattr(v, "uid", None)),
    )
    logger.info("[PARTIES] created vendor %s (biz=%s)", v.id, bid)
    return dto


@router.get("/vendors/{vendor_id}")
def get_vendor(
    vendor_id: int,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Vendor detail scoped to business."""
    bid = current_user["id"]
    v = db.query(Vendor).filter(
        Vendor.id == vendor_id, Vendor.business_id == bid
    ).first()
    if v is None:
        raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
    outstanding, last_date = _compute_vendor_stats(db, bid, vendor_id)
    return _vendor_out(v, outstanding, last_date)


@router.patch("/vendors/{vendor_id}")
def update_vendor(
    vendor_id: int,
    req: UpdateVendor,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    """Update vendor fields."""
    bid = current_user["id"]
    v = db.query(Vendor).filter(
        Vendor.id == vendor_id, Vendor.business_id == bid
    ).first()
    if v is None:
        raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")

    data = req.model_dump(exclude_none=True)
    for field, val in data.items():
        if hasattr(v, field):
            setattr(v, field, val)

    db.commit()
    db.refresh(v)
    outstanding, last_date = _compute_vendor_stats(db, bid, vendor_id)
    dto = _vendor_out(v, outstanding, last_date)
    background_tasks.add_task(
        realtime_manager.broadcast, bid,
        delta_event("party", payload=dto, kind="vendor", rid=v.id, uid=getattr(v, "uid", None)),
    )
    return dto
