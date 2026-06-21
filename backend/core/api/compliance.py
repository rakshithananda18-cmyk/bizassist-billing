"""
core/api/compliance.py — GST statutory JSON endpoints (owner-only).
===================================================================
Returns the e-invoice (IRN) and e-way-bill JSON payloads for a saved sale so the
owner can file them with an IRP / the NIC e-way portal. Read-only and
business_id-scoped; cashiers are blocked (`require_owner`). The builders live in
`core/compliance/einvoice.py` (pure, unit-tested); these endpoints only load the
rows and surface `{payload, warnings, ready}`.

  GET  /compliance/e-invoice/{invoice_id}         Form GST INV-01 payload for IRN
  POST /compliance/e-invoice/{invoice_id}/record  store the IRN/QR an IRP returned
  POST /compliance/e-way-bill/{invoice_id}        NIC e-Way Bill payload (+ transport)
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from database.db import get_db
from database.models import Invoice, Customer, User
from core.models import BusinessSettings
from services.auth import require_owner
from services.errors import ask_error
from core.compliance import einvoice

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.compliance")


def _einvoice_enabled(db, business_id) -> bool:
    """Owner-set flag (BusinessSettings.overrides JSON `e_invoice_enabled`) marking
    that the business has crossed the ₹5 cr e-invoice turnover threshold. Read
    defensively (default False) so unknown-key stripping or bad JSON can't error."""
    row = (
        db.query(BusinessSettings)
        .filter(BusinessSettings.business_id == business_id)
        .first()
    )
    if not row or not row.overrides:
        return False
    try:
        return bool(json.loads(row.overrides).get("e_invoice_enabled", False))
    except (ValueError, TypeError):
        return False


class RecordIRNRequest(BaseModel):
    irn: str                              # 64-char IRN the IRP minted
    ack_no: Optional[str] = None
    ack_date: Optional[str] = None
    qr_code: Optional[str] = None         # signed QR payload (base64)


class TransportInfo(BaseModel):
    mode: Optional[str] = None            # road|rail|air|ship (or 1-4)
    distance: Optional[int] = 0           # km between source & destination PINs
    transporter_id: Optional[str] = None
    transporter_name: Optional[str] = None
    trans_doc_no: Optional[str] = None
    trans_doc_date: Optional[str] = None  # YYYY-MM-DD
    vehicle_no: Optional[str] = None
    vehicle_type: Optional[str] = None    # R=Regular, O=ODC


def _load(db, business_id, invoice_id):
    """Load a sale (with line items), its seller (business) and buyer — all scoped."""
    inv = (
        db.query(Invoice)
        .options(selectinload(Invoice.line_items))
        .filter(Invoice.id == invoice_id, Invoice.business_id == business_id)
        .first()
    )
    if inv is None:
        raise ask_error(404, "invoice_not_found",
                        f"Invoice {invoice_id} not found for this business.")
    seller = db.query(User).filter(User.id == business_id).first()
    buyer = None
    if inv.customer_id:
        buyer = (
            db.query(Customer)
            .filter(Customer.id == inv.customer_id, Customer.business_id == business_id)
            .first()
        )
    return inv, seller, buyer


@router.get("/compliance/e-invoice/{invoice_id}")
def get_einvoice_json(
    invoice_id: int,
    current_user: dict = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Form GST INV-01 payload for IRN generation. `applicable` reflects the
    business's e-invoice turnover flag; `warnings` lists mandatory gaps; `ready` is
    True only when applicable AND there are no warnings (and no IRN yet)."""
    bid = current_user["id"]
    inv, seller, buyer = _load(db, bid, invoice_id)
    payload, warnings = einvoice.build_einvoice_payload(seller=seller, invoice=inv, buyer=buyer)
    applicable = einvoice.einvoice_applicable(_einvoice_enabled(db, bid))
    logger.info("[COMPLIANCE] e-invoice JSON requested inv=%s biz=%s applicable=%s ready=%s",
                invoice_id, bid, applicable, not warnings)
    return {"invoice_id": invoice_id, "irn": inv.irn, "applicable": applicable,
            "already_generated": bool(inv.irn), "payload": payload,
            "warnings": warnings, "ready": applicable and not warnings and not inv.irn}


@router.post("/compliance/e-invoice/{invoice_id}/record")
def record_einvoice_irn(
    invoice_id: int,
    body: RecordIRNRequest,
    current_user: dict = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Persist the IRN / ack / signed-QR an IRP returned for this sale (the columns
    already exist on `invoices`). Idempotent: re-recording the same IRN is a no-op;
    a different IRN on an already-stamped invoice is rejected (422)."""
    bid = current_user["id"]
    inv, _, _ = _load(db, bid, invoice_id)
    irn = (body.irn or "").strip()
    if not irn:
        raise ask_error(422, "bad_irn", "IRN is required.")
    if inv.irn and inv.irn != irn:
        raise ask_error(422, "irn_conflict",
                        f"Invoice already has IRN {inv.irn}; cannot overwrite with a different one.")
    inv.irn = irn
    inv.ack_no = body.ack_no or inv.ack_no
    inv.ack_date = body.ack_date or inv.ack_date
    inv.qr_code = body.qr_code or inv.qr_code
    db.commit()
    logger.info("[COMPLIANCE] IRN recorded inv=%s biz=%s irn=%s", invoice_id, bid, irn[:12])
    return {"invoice_id": invoice_id, "irn": inv.irn, "ack_no": inv.ack_no,
            "ack_date": inv.ack_date, "recorded": True}


@router.post("/compliance/e-way-bill/{invoice_id}")
def get_eway_json(
    invoice_id: int,
    transport: TransportInfo = TransportInfo(),
    current_user: dict = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """NIC e-Way Bill payload. `required` is True when the invoice value crosses the
    ₹50,000 threshold. Transport details (distance/mode/vehicle) are POSTed in the
    body since they aren't part of the invoice record."""
    bid = current_user["id"]
    inv, seller, buyer = _load(db, bid, invoice_id)
    payload, warnings = einvoice.build_eway_payload(
        seller=seller, invoice=inv, buyer=buyer, transport=transport.model_dump())
    required = einvoice.eway_required(inv)
    logger.info("[COMPLIANCE] e-way JSON requested inv=%s biz=%s required=%s ready=%s",
                invoice_id, bid, required, not warnings)
    return {"invoice_id": invoice_id, "required": required, "threshold": einvoice.EWAY_THRESHOLD,
            "payload": payload, "warnings": warnings, "ready": not warnings}
