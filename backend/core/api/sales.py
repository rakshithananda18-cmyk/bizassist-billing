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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import Product, Invoice, InvoiceLineItem, User, Customer
from services.auth import get_active_user
from core.billing import commands as billing
from core.catalog import barcode as PB
from core import templates as T

router = APIRouter()
logger = logging.getLogger("bizassist.core.api.sales")


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


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/sales")
def create_sale(req: SaleRequest,
                current_user: dict = Depends(get_active_user),
                db: Session = Depends(get_db)):
    """Create a sale invoice (atomic: invoice + lines + stock). Idempotent on invoice_no."""
    bid = current_user["id"]
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
            device_id=req.device_id, godown_id=req.godown_id,
            cash_discount=req.cash_discount, mark_paid=req.mark_paid,
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
    """Fetch one invoice (with line items), scoped to the caller's business."""
    inv = (
        db.query(Invoice)
        .filter(Invoice.business_id == current_user["id"], Invoice.invoice_id == invoice_no)
        .first()
    )
    if inv is None:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_no}' not found")
    return _invoice_out(inv)


def num_to_words_indian(num: float) -> str:
    """Convert number to Indian English Rupees words."""
    try:
        rupees = int(num)
        paise = int(round((num - rupees) * 100))
        
        def words_under_100(n):
            units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
                     "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
            tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
            if n < 20:
                return units[n]
            else:
                return tens[n // 10] + (" " + units[n % 10] if n % 10 != 0 else "")

        def int_to_words(n):
            if n == 0:
                return "Zero"
            parts = []
            if n >= 10000000: # Crore
                crore = n // 10000000
                parts.append(words_under_100(crore) + " Crore")
                n %= 10000000
            if n >= 100000: # Lakh
                lakh = n // 100000
                parts.append(words_under_100(lakh) + " Lakh")
                n %= 100000
            if n >= 1000: # Thousand
                thousand = n // 1000
                parts.append(words_under_100(thousand) + " Thousand")
                n %= 1000
            if n >= 100: # Hundred
                hundred = n // 100
                parts.append(words_under_100(hundred) + " Hundred")
                n %= 100
            if n > 0:
                if parts:
                    parts.append("and " + words_under_100(n))
                else:
                    parts.append(words_under_100(n))
            return " ".join(parts)

        words = int_to_words(rupees) + " Rupees"
        if paise > 0:
            words += " and " + words_under_100(paise) + " Paise"
        return words + " Only"
    except Exception:
        return ""


def generate_invoice_html(inv: Invoice, biz: Optional[User], config: dict) -> str:
    import json
    terminology = config.get("terminology", {})
    bill_label = terminology.get("bill", "Bill")
    customer_label = terminology.get("customer", "Customer")
    product_label = terminology.get("product", "Product")

    # Load print settings from user settings
    print_settings = {
        "theme_color": "#C2714F",
        "page_size": "A4",
        "print_orientation": "portrait",
        "invoice_theme": "classic",
        "print_logo": True,
        "print_company_name": True,
        "print_company_address": True,
        "print_company_phone": True,
        "print_company_email": True,
        "print_gstin": True,
        "print_terms_conditions": True,
        "terms_conditions_text": "Thank you for your business!",
        "print_signature": True,
        "signature_label": "Authorised Signatory",
        "customer_signature": True,
        "customer_signature_label": "Customer Signature",
        "print_tax_breakdown": True,
        "print_item_sno": True,
        "print_item_hsn": True,
        "print_item_discount": True,
        "print_item_tax": True,
        "print_amount_in_words": False,
        "text_size": "medium",
    }

    if biz and biz.settings:
        try:
            saved = json.loads(biz.settings)
            if "print" in saved and isinstance(saved["print"], dict):
                print_settings.update(saved["print"])
        except Exception:
            pass

    theme = print_settings.get("invoice_theme", "classic")
    theme_color = print_settings.get("theme_color", "#C2714F")
    orientation = print_settings.get("print_orientation", "portrait")
    page_size = print_settings.get("page_size", "A4")

    # Font sizing mappings
    size_map = {"small": "11px", "medium": "13px", "large": "15px"}
    base_font_size = size_map.get(print_settings.get("text_size", "medium"), "13px")

    def fmt_curr(val):
        return f"₹{val:,.2f}" if val is not None else "₹0.00"

    # Dynamic columns
    headers = []
    if print_settings.get("print_item_sno", True):
        headers.append("<th style='width: 40px;'>#</th>")
    headers.append(f"<th>{product_label}</th>")
    if print_settings.get("print_item_hsn", True):
        headers.append("<th>HSN/SAC</th>")
    headers.append("<th class='text-right'>Qty</th>")
    headers.append("<th class='text-right'>Rate</th>")
    if print_settings.get("print_item_discount", True):
        headers.append("<th class='text-right'>Disc</th>")
    headers.append("<th class='text-right'>Taxable</th>")
    if print_settings.get("print_item_tax", True):
        headers.append("<th class='text-right'>GST</th>")
    headers.append("<th class='text-right'>Total</th>")
    headers_html = "\n".join(headers)

    lines_html = ""
    for idx, li in enumerate(inv.line_items):
        tax_rate = (li.cgst_rate or 0) + (li.sgst_rate or 0) + (li.igst_rate or 0)
        tax_amount = (li.cgst_amount or 0) + (li.sgst_amount or 0) + (li.igst_amount or 0)
        
        cells = []
        if print_settings.get("print_item_sno", True):
            cells.append(f"<td>{idx + 1}</td>")
        cells.append(f"<td>{li.product_name or '—'}</td>")
        if print_settings.get("print_item_hsn", True):
            cells.append(f"<td>{li.hsn_sac or '—'}</td>")
        cells.append(f"<td class='text-right'>{li.quantity or 0} {li.unit or 'Nos'}</td>")
        cells.append(f"<td class='text-right'>{fmt_curr(li.unit_price)}</td>")
        if print_settings.get("print_item_discount", True):
            cells.append(f"<td class='text-right'>{li.discount or 0}%</td>")
        cells.append(f"<td class='text-right'>{fmt_curr(li.taxable_value)}</td>")
        if print_settings.get("print_item_tax", True):
            cells.append(f"<td class='text-right'>{tax_rate}% ({fmt_curr(tax_amount)})</td>")
        cells.append(f"<td class='text-right'>{fmt_curr(li.line_total)}</td>")
        
        lines_html += f"<tr>{''.join(cells)}</tr>\n"

    # Merchant details section
    biz_header_lines = []
    if print_settings.get("print_company_name", True):
        biz_header_lines.append(f'<h1 class="biz-title">{biz.business_name if biz else "BizAssist Client"}</h1>')
    if print_settings.get("print_gstin", True) and biz and biz.gstin:
        biz_header_lines.append(f'<div style="font-weight: bold; margin-bottom: 2px;">GSTIN: {biz.gstin}</div>')
    if print_settings.get("print_company_address", True) and biz and biz.address:
        biz_header_lines.append(f'<div>{biz.address}</div>')
        
    contacts = []
    if print_settings.get("print_company_phone", True) and biz and biz.phone:
        contacts.append(f"Phone: {biz.phone}")
    if print_settings.get("print_company_email", True) and biz and biz.email:
        contacts.append(f"Email: {biz.email}")
    if contacts:
        biz_header_lines.append(f'<div>{" | ".join(contacts)}</div>')
    biz_header_html = "\n".join(biz_header_lines)

    # Tax breakdown rows
    cgst_row = f"<tr><td>CGST Total</td><td class='text-right'>{fmt_curr(inv.cgst_total)}</td></tr>" if print_settings.get("print_tax_breakdown", True) else ""
    sgst_row = f"<tr><td>SGST Total</td><td class='text-right'>{fmt_curr(inv.sgst_total)}</td></tr>" if print_settings.get("print_tax_breakdown", True) else ""
    igst_row = f"<tr><td>IGST Total</td><td class='text-right'>{fmt_curr(inv.igst_total)}</td></tr>" if print_settings.get("print_tax_breakdown", True) else ""

    # Amount in words
    words_html = ""
    if print_settings.get("print_amount_in_words", False):
        amt_words = num_to_words_indian(inv.total_amount)
        if amt_words:
            words_html = f"""
            <div style="margin-top: 15px; font-size: 11px; color: #475569; font-style: italic;">
                <strong>Amount in Words:</strong> {amt_words}
            </div>
            """

    # Terms
    terms_html = ""
    if print_settings.get("print_terms_conditions", True) and print_settings.get("terms_conditions_text"):
        terms_html = f"""
        <div style="margin-top: 30px; padding: 12px; background: #fdfdfd; border-left: 3px solid {theme_color}; page-break-inside: avoid; border-radius: 4px;">
            <strong style="color: #475569;">Terms & Conditions:</strong>
            <div style="white-space: pre-wrap; margin-top: 5px; font-size: 11px; color: #64748b;">{print_settings.get("terms_conditions_text")}</div>
        </div>
        """

    # Signatures
    sig_block_html = ""
    if print_settings.get("customer_signature", True) or print_settings.get("print_signature", True):
        sig_cols = []
        if print_settings.get("customer_signature", True):
            cust_label = print_settings.get("customer_signature_label", "Customer Signature")
            sig_cols.append(f"""
            <div style="text-align: center; flex: 1;">
                <div style="border-bottom: 1px solid #cbd5e1; width: 70%; margin: 40px auto 5px auto; height: 1px;"></div>
                <div style="font-size: 11px; color: #475569;">{cust_label}</div>
            </div>
            """)
        if print_settings.get("print_signature", True):
            sig_label = print_settings.get("signature_label", "Authorised Signatory")
            sig_cols.append(f"""
            <div style="text-align: center; flex: 1;">
                <div style="border-bottom: 1px solid #cbd5e1; width: 70%; margin: 40px auto 5px auto; height: 1px;"></div>
                <div style="font-size: 11px; color: #475569; font-weight: bold;">{sig_label}</div>
            </div>
            """)
        sig_block_html = f"""
        <div style="display: flex; justify-content: space-between; margin-top: 40px; page-break-inside: avoid;">
            {''.join(sig_cols)}
        </div>
        """

    # Theme CSS Injection
    theme_css = ""
    if theme == "modern":
        theme_css = f"""
            .biz-title {{
                color: {theme_color};
                font-size: 26px;
                font-weight: 800;
                margin: 0 0 5px 0;
            }}
            th {{
                background: {theme_color} !important;
                color: #ffffff !important;
                border: none !important;
                font-weight: 600;
                padding: 12px 10px;
            }}
            table {{
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            }}
            .panel-title {{
                background: #f1f5f9;
                padding: 6px 10px;
                border-radius: 4px;
                color: #475569;
                border: none;
                font-size: 9px;
            }}
        """
    elif theme == "minimal":
        theme_css = f"""
            .biz-title {{
                color: #0f172a;
                font-size: 22px;
                font-weight: 800;
                text-transform: uppercase;
                margin: 0 0 5px 0;
            }}
            th {{
                background: transparent !important;
                color: #000000 !important;
                border-bottom: 2px solid #000000 !important;
                border-top: 2px solid #000000 !important;
                font-weight: 700;
                padding: 6px 4px;
            }}
            td {{
                border-bottom: 1px solid #f1f5f9 !important;
                padding: 8px 4px;
            }}
            .panel-title {{
                border-bottom: 1.5px solid #0f172a;
                color: #0f172a;
                font-weight: 800;
                font-size: 9px;
            }}
        """
    else: # classic
        theme_css = f"""
            .biz-title {{
                font-size: 24px;
                font-weight: 700;
                color: {theme_color};
                margin: 0 0 5px 0;
            }}
            th {{
                background: #fdfaf7;
                border-bottom: 2px solid #e2e2e0;
                padding: 10px;
            }}
            td {{
                border-bottom: 1px solid #e2e2e0;
                padding: 10px;
            }}
            .panel-title {{
                border-bottom: 1px solid #e2e2e0;
                color: #8c8c88;
                font-size: 10px;
            }}
        """

    logo_html = ""
    if print_settings.get("print_logo", True) and biz and biz.logo:
        logo_html = f"""
        <div style="margin-bottom: 15px;">
            <img src="{biz.logo}" style="max-height: 60px; max-width: 180px; object-fit: contain;" alt="logo" />
        </div>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{bill_label} {inv.invoice_id}</title>
        <style>
            @page {{
                size: {page_size} {orientation};
                margin: 15mm;
            }}
            body {{
                font-family: 'DM Sans', Arial, sans-serif;
                color: #2b2b2a;
                margin: 0;
                padding: 0;
                font-size: {base_font_size};
                line-height: 1.5;
            }}
            .header {{
                display: flex;
                justify-content: space-between;
                border-bottom: 2px solid {theme_color};
                padding-bottom: 20px;
                margin-bottom: 30px;
            }}
            .invoice-title {{
                font-size: 28px;
                font-weight: 700;
                text-align: right;
                margin: 0 0 10px 0;
                color: #2b2b2a;
            }}
            .grid {{
                display: flex;
                justify-content: space-between;
                margin-bottom: 30px;
            }}
            .grid > div {{
                flex: 1;
            }}
            .panel-title {{
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                padding-bottom: 5px;
                margin-bottom: 10px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 30px;
            }}
            th {{
                text-align: left;
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                font-weight: 700;
            }}
            .text-right {{
                text-align: right;
            }}
            .totals-container {{
                display: flex;
                justify-content: space-end;
                margin-top: 20px;
            }}
            .totals-table {{
                width: 320px;
                margin-bottom: 0;
                margin-left: auto;
            }}
            .totals-table td {{
                padding: 6px 10px;
                border-bottom: 1px solid #f1f5f9;
            }}
            .totals-table tr.grand {{
                font-size: 15px;
                font-weight: 700;
                border-top: 2px solid {theme_color};
                border-bottom: 2px solid {theme_color};
            }}
            .badge {{
                display: inline-block;
                padding: 4px 10px;
                border-radius: 99px;
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
            }}
            .badge-Paid {{ background: #d1fae5; color: #065f46; }}
            .badge-Pending {{ background: #fef3c7; color: #92400e; }}
            .badge-Overdue {{ background: #fee2e2; color: #991b1b; }}
            
            {theme_css}
        </style>
    </head>
    <body>
        <div class="header">
            <div>
                {logo_html}
                {biz_header_html}
            </div>
            <div class="text-right">
                <h2 class="invoice-title">{bill_label}</h2>
                <div><strong>No:</strong> {inv.invoice_id}</div>
                <div><strong>Date:</strong> {inv.invoice_date}</div>
                <div style="margin-top: 10px;">
                    <span class="badge badge-{inv.status}">{inv.status}</span>
                </div>
            </div>
        </div>

        <div class="grid">
            <div>
                <div class="panel-title">Bill To ({customer_label})</div>
                <div style="font-size: 15px; font-weight: 700; margin-bottom: 5px;">{inv.customer or 'Walk-in Customer'}</div>
                <div>GSTIN: {inv.gstin_buyer or '—'}</div>
                <div>Place of Supply: {inv.place_of_supply or '—'}</div>
            </div>
            <div style="margin-left: 40px;">
                <div class="panel-title">Details</div>
                <div><strong>Payment Mode:</strong> {inv.payment_mode or 'Cash'}</div>
                <div><strong>Due Date:</strong> {inv.due_date or '—'}</div>
                <div><strong>Type:</strong> {inv.invoice_type or 'B2C'}</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    {headers_html}
                </tr>
            </thead>
            <tbody>
                {lines_html}
            </tbody>
        </table>

        <div class="totals-container">
            <table class="totals-table">
                <tr>
                    <td>Subtotal</td>
                    <td class="text-right">{fmt_curr(inv.subtotal)}</td>
                </tr>
                {cgst_row}
                {sgst_row}
                {igst_row}
                <tr>
                    <td>Round Off</td>
                    <td class="text-right">{fmt_curr(inv.round_off)}</td>
                </tr>
                <tr class="grand">
                    <td>Grand Total</td>
                    <td class="text-right">{fmt_curr(inv.total_amount)}</td>
                </tr>
                <tr>
                    <td>Amount Paid</td>
                    <td class="text-right">{fmt_curr(inv.paid_amount)}</td>
                </tr>
                <tr style="border-top: 1px solid #e2e2e0;">
                    <td><strong>Balance Due</strong></td>
                    <td class="text-right" style="color: #c02a2a; font-weight: 700;">
                        {fmt_curr(max((inv.total_amount or 0) - (inv.paid_amount or 0), 0.0))}
                    </td>
                </tr>
            </table>
        </div>
        
        {words_html}
        {terms_html}
        {sig_block_html}
        
        {f'<div style="margin-top: 30px; padding: 12px; background: #fdfdfd; border-left: 3px solid #64748b; font-size: 11px; border-radius: 4px;"><strong>Notes:</strong> {inv.notes}</div>' if inv.notes else ''}
    </body>
    </html>
    """
    return html


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

    biz = db.query(User).filter(User.id == bid).first()
    config = T.resolve_for(bid, db)
    html_content = generate_invoice_html(inv, biz, config)

    try:
        import weasyprint
        pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
        from fastapi import Response
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=invoice_{invoice_no}.pdf"
            }
        )
    except Exception:
        # Fallback to serving the printable HTML directly
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

class FrontendInvoiceRequest(BaseModel):
    customer_id: Optional[int] = None
    due_date: Optional[str] = None
    items: List[FrontendInvoiceItem]
    gst_enabled: bool = False
    notes: Optional[str] = None
    invoice_no: Optional[str] = None
    bill_discount: float = 0.0   # whole-invoice PRE-tax discount (absolute ₹), resolved on the client
    cash_discount: float = 0.0   # POST-tax cash discount / round-off (₹) — reduces payable, not GST (R4)
    paid_amount: float = 0.0     # amount received now → Paid/Partial/Unpaid status (default 0 = unpaid)
    mark_paid: bool = False      # "Paid & Print": settle the full payable exactly (status Paid)


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
    current_user: dict = Depends(get_active_user),
    db: Session = Depends(get_db),
):
    bid = current_user["id"]
    
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
            "expiry_date": it.expiry_date
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
            bill_discount=req.bill_discount,
            cash_discount=req.cash_discount,
            paid_amount=req.paid_amount,
            mark_paid=req.mark_paid,
        )
        if req.notes:
            inv.notes = req.notes
            db.commit()
            db.refresh(inv)
            
        return _invoice_out_for_frontend(inv)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as e:
        db.rollback()
        logger.error("create_invoice_frontend failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create invoice.")


