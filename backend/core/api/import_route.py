"""
core/api/import_route.py — Bulk import/export HTTP layer (Phase 1B).
==================================================================
Scoped by business_id. CASHIER is restricted.
"""
import csv
import io
import logging
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Product, Customer, Vendor, Invoice
from core.models import InvoicePayment, StockLedger
from services.auth import get_active_user, restrict_cashier
from services import import_data

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.import_route")


# ── Schemas ───────────────────────────────────────────────────────────────────

class ImportRequest(BaseModel):
    items: List[Dict[str, Any]]


# ── Dependencies ──────────────────────────────────────────────────────────────
# restrict_cashier is the single guard in services.auth (imported above).


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _parse_csv_file(file: UploadFile) -> List[Dict[str, Any]]:
    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    items = []
    for row in reader:
        items.append({k.lower().strip(): v for k, v in row.items() if k is not None})
    return items


def _to_csv_stream(headers: List[str], rows: List[List[Any]]):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    yield output.getvalue()
    output.close()
    
    for row in rows:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(row)
        yield output.getvalue()
        output.close()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/import/products")
async def import_products(
    request: Request,
    preview: bool = False,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Bulk import products via JSON array or CSV file upload.

    APPROVAL FLOW: with `?preview=1` the file is parsed and normalized but
    NOTHING is written — the rows come back for the review table in the UI.
    The client then POSTs the (possibly edited) rows as JSON without the
    flag to actually commit. Products never land silently from a file."""
    bid = current_user["id"]
    content_type = request.headers.get("content-type", "")
    items = []

    if "application/json" in content_type:
        try:
            body = await request.json()
            items = body.get("items", [])
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
    elif "multipart/form-data" in content_type:
        try:
            form = await request.form()
            file_val = form.get("file")
            if not file_val:
                raise HTTPException(status_code=400, detail="No file uploaded")
            items = await _parse_csv_file(file_val)
        except Exception as e:
            logger.error("Failed to parse CSV file for products: %s", e)
            raise HTTPException(status_code=400, detail="Invalid CSV format")
    else:
        raise HTTPException(status_code=415, detail="Unsupported media type")

    if preview:
        # Parse-only: normalize the fields the importer understands and flag
        # duplicates so the review table can warn before commit.
        from database.models import Product as _Product
        existing_skus = {
            s for (s,) in db.query(_Product.sku)
            .filter(_Product.business_id == bid, _Product.sku.isnot(None)).all()
        }
        existing_names = {
            (n or "").strip().lower() for (n,) in db.query(_Product.name)
            .filter(_Product.business_id == bid).all()
        }
        out = []
        for idx, it in enumerate(items):
            name = str(it.get("name") or "").strip()
            sku = (str(it.get("sku")).strip() or None) if it.get("sku") is not None else None
            problems = []
            if not name:
                problems.append("name required")
            elif name.lower() in existing_names:
                problems.append("a product with this name already exists")
            if sku and sku in existing_skus:
                problems.append(f"SKU '{sku}' already exists")
            out.append({
                "row": idx + 1,
                "name": name,
                "sku": sku,
                "barcode": it.get("barcode") or None,
                "unit": it.get("unit") or "Nos",
                "category": it.get("category") or None,
                "brand": it.get("brand") or None,
                "selling_price": it.get("selling_price") or 0,
                "cost_price": it.get("cost_price") or 0,
                "mrp": it.get("mrp") or None,
                "cgst_rate": it.get("cgst_rate") or 0,
                "sgst_rate": it.get("sgst_rate") or 0,
                "opening_stock": it.get("opening_stock") or 0,
                "problems": problems,
            })
        return {"preview": True, "count": len(out), "items": out}

    try:
        res = import_data.import_products_bulk(db, bid, items)
        return res
    except Exception as e:
        logger.error("import_products route failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Import failed")


@router.post("/import/customers")
async def import_customers(
    request: Request,
    preview: bool = False,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Bulk import customers via JSON array or CSV file upload.

    APPROVAL FLOW (parity with /import/products): with `?preview=1` the file
    is parsed and normalized but NOTHING is written — the rows come back for
    the review table, duplicates flagged. The client then POSTs the (possibly
    edited) rows as JSON without the flag to commit. Nothing lands silently."""
    bid = current_user["id"]
    content_type = request.headers.get("content-type", "")
    items = []

    if "application/json" in content_type:
        try:
            body = await request.json()
            items = body.get("items", [])
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
    elif "multipart/form-data" in content_type:
        try:
            form = await request.form()
            file_val = form.get("file")
            if not file_val:
                raise HTTPException(status_code=400, detail="No file uploaded")
            items = await _parse_csv_file(file_val)
        except Exception as e:
            logger.error("Failed to parse CSV file for customers: %s", e)
            raise HTTPException(status_code=400, detail="Invalid CSV format")
    else:
        raise HTTPException(status_code=415, detail="Unsupported media type")

    if preview:
        existing_names = {
            (n or "").strip().lower() for (n,) in db.query(Customer.name)
            .filter(Customer.business_id == bid).all()
        }
        existing_phones = {
            (p or "").strip() for (p,) in db.query(Customer.phone)
            .filter(Customer.business_id == bid, Customer.phone.isnot(None)).all() if p
        }
        out = []
        for idx, it in enumerate(items):
            name = str(it.get("name") or "").strip()
            phone = (str(it.get("phone")).strip() or None) if it.get("phone") is not None else None
            problems = []
            if not name:
                problems.append("name required")
            elif name.lower() in existing_names:
                problems.append("a customer with this name already exists")
            if phone and phone in existing_phones:
                problems.append(f"phone '{phone}' already exists")
            out.append({
                "row": idx + 1,
                "name": name,
                "phone": phone,
                "email": it.get("email") or None,
                "address": it.get("address") or None,
                "gstin": it.get("gstin") or None,
                "state_code": it.get("state_code") or None,
                "pan": it.get("pan") or None,
                "credit_limit": it.get("credit_limit") or 0,
                "credit_days": it.get("credit_days") or 30,
                "opening_dues": it.get("opening_dues") or 0,
                "problems": problems,
            })
        return {"preview": True, "count": len(out), "items": out}

    try:
        res = import_data.import_customers_bulk(db, bid, items)
        return res
    except Exception as e:
        logger.error("import_customers route failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Import failed")


@router.post("/import/vendors")
async def import_vendors(
    request: Request,
    preview: bool = False,
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Bulk import vendors via JSON array or CSV file upload.

    APPROVAL FLOW (parity with /import/products): with `?preview=1` the file
    is parsed and normalized but NOTHING is written — rows come back for the
    review table with duplicates flagged; commit happens on a flag-less POST."""
    bid = current_user["id"]
    content_type = request.headers.get("content-type", "")
    items = []

    if "application/json" in content_type:
        try:
            body = await request.json()
            items = body.get("items", [])
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")
    elif "multipart/form-data" in content_type:
        try:
            form = await request.form()
            file_val = form.get("file")
            if not file_val:
                raise HTTPException(status_code=400, detail="No file uploaded")
            items = await _parse_csv_file(file_val)
        except Exception as e:
            logger.error("Failed to parse CSV file for vendors: %s", e)
            raise HTTPException(status_code=400, detail="Invalid CSV format")
    else:
        raise HTTPException(status_code=415, detail="Unsupported media type")

    if preview:
        existing_names = {
            (n or "").strip().lower() for (n,) in db.query(Vendor.name)
            .filter(Vendor.business_id == bid).all()
        }
        existing_phones = {
            (p or "").strip() for (p,) in db.query(Vendor.phone)
            .filter(Vendor.business_id == bid, Vendor.phone.isnot(None)).all() if p
        }
        out = []
        for idx, it in enumerate(items):
            name = str(it.get("name") or "").strip()
            phone = (str(it.get("phone")).strip() or None) if it.get("phone") is not None else None
            problems = []
            if not name:
                problems.append("name required")
            elif name.lower() in existing_names:
                problems.append("a vendor with this name already exists")
            if phone and phone in existing_phones:
                problems.append(f"phone '{phone}' already exists")
            out.append({
                "row": idx + 1,
                "name": name,
                "phone": phone,
                "email": it.get("email") or None,
                "address": it.get("address") or None,
                "gstin": it.get("gstin") or None,
                "state_code": it.get("state_code") or None,
                "pan": it.get("pan") or None,
                "payment_terms_days": it.get("payment_terms_days") or 30,
                "problems": problems,
            })
        return {"preview": True, "count": len(out), "items": out}

    try:
        res = import_data.import_vendors_bulk(db, bid, items)
        return res
    except Exception as e:
        logger.error("import_vendors route failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Import failed")


# ── Export Endpoints ──────────────────────────────────────────────────────────

@router.get("/export/products")
def export_products(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Export product catalogue to CSV."""
    bid = current_user["id"]
    products = db.query(Product).filter(Product.business_id == bid).all()
    
    headers = ["name", "sku", "barcode", "selling_price", "cost_price", "mrp", "cgst_rate", "sgst_rate", "igst_rate", "category", "unit", "description"]
    rows = []
    for p in products:
        rows.append([
            p.name, p.sku, p.barcode, p.selling_price, p.cost_price, p.mrp,
            p.cgst_rate, p.sgst_rate, p.igst_rate, p.category, p.unit, p.description
        ])
        
    return StreamingResponse(
        _to_csv_stream(headers, rows),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=products_export.csv"}
    )


@router.get("/export/invoices")
def export_invoices(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Export sales invoices to CSV."""
    bid = current_user["id"]
    invoices = db.query(Invoice).filter(Invoice.business_id == bid).all()
    
    headers = ["invoice_number", "invoice_date", "customer_name", "subtotal", "discount_total", "taxable_value", "cgst_total", "sgst_total", "igst_total", "total_amount", "status", "notes"]
    rows = []
    for inv in invoices:
        cgst = inv.cgst_total or 0.0
        sgst = inv.sgst_total or 0.0
        igst = inv.igst_total or 0.0
        total_gst = cgst + sgst + igst
        taxable_val = (inv.total_amount or 0.0) - total_gst
        
        rows.append([
            inv.invoice_id, inv.invoice_date, inv.customer,
            inv.subtotal, inv.discount_total, taxable_val,
            cgst, sgst, igst, inv.total_amount, inv.status, inv.notes
        ])
        
    return StreamingResponse(
        _to_csv_stream(headers, rows),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices_export.csv"}
    )


@router.get("/export/payments")
def export_payments(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Export payment history to CSV."""
    bid = current_user["id"]
    payments = db.query(InvoicePayment).filter(InvoicePayment.business_id == bid).all()
    
    headers = ["date", "invoice_number", "customer_name", "amount", "method", "reference"]
    rows = []
    for p in payments:
        inv = db.query(Invoice).filter(Invoice.id == p.invoice_id, Invoice.business_id == bid).first()
        inv_no = inv.invoice_id if inv else f"#{p.invoice_id}"
        
        party_name = inv.customer if inv else None
        if not party_name and p.customer_id:
            c = db.query(Customer).filter(Customer.id == p.customer_id, Customer.business_id == bid).first()
            if c:
                party_name = c.name
                
        rows.append([
            p.payment_date or (p.created_at.strftime("%Y-%m-%d") if p.created_at else None),
            inv_no, party_name, p.amount_paid, p.payment_mode, p.note or ""
        ])
        
    return StreamingResponse(
        _to_csv_stream(headers, rows),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments_export.csv"}
    )


@router.get("/export/stock-ledger")
def export_stock_ledger(
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """Export stock ledger history to CSV."""
    bid = current_user["id"]
    movements = db.query(StockLedger).filter(StockLedger.business_id == bid).order_by(StockLedger.created_at.desc()).all()
    
    headers = ["date", "product_name", "movement_type", "qty_delta", "balance_after", "reference", "note"]
    rows = []
    for m in movements:
        rows.append([
            m.created_at.isoformat() if m.created_at else None,
            m.product_name, m.movement_type, m.qty_delta, m.balance_after,
            m.reference_type or "manual", m.note or ""
        ])
        
    return StreamingResponse(
        _to_csv_stream(headers, rows),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=stock_ledger_export.csv"}
    )
