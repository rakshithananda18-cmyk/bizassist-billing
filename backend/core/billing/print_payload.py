"""
core/billing/print_payload.py — the normalized InvoicePrintPayload (v1).
========================================================================
ONE payload, MANY renderers. This module maps a stored Invoice (+ lines,
payments, seller, buyer, vertical config, print settings) into a versioned,
fully-computed, presentation-ready dict. Frontend invoice templates (Classic /
Modern / Thermal) are PURE functions of this payload — they never compute,
round, or derive money. All money figures here come from values the billing
command already persisted; this module NEVER recomputes tax.

Contract rules (plan §Phase-1):
  • pure read — no commit, no side effects
  • visibility is resolved HERE (gst_mode, igst_mode, columns, blocks) so a
    non-GST business can never accidentally render empty tax columns
  • payload_hash = SHA-256 over the money-bearing content; two builds of the
    same invoice hash identically (the e2e "switching never mutates" check)
  • every build emits one structured `payload_built` log line
"""
from services.dates import utc_now
import hashlib
import json
import logging
import os
from datetime import datetime

from database.models import Invoice, User, Customer
from core.models import InvoicePayment
from core import templates as T

logger = logging.getLogger("bizassist.invoice_render")

PAYLOAD_VERSION = 1

# ── Local-time rendering ─────────────────────────────────────────────────────
# Timestamps are STORED as naive UTC (TimestampMixin/utc_now). Printing
# them raw put UTC on invoices — 5h30 behind the merchant's wall clock. Render
# in the business timezone (env-tunable; the scheduler already assumes IST).
try:
    from zoneinfo import ZoneInfo
    _BIZ_TZ = ZoneInfo(os.getenv("BIZ_TIMEZONE", "Asia/Kolkata"))
except Exception:                                    # pragma: no cover
    _BIZ_TZ = None

from datetime import timezone as _utc_tz


def _local_time_str(dt) -> str:
    """Naive-UTC datetime → merchant-local 'hh:mm AM/PM'. None-safe."""
    if not dt:
        return None
    try:
        if _BIZ_TZ is not None:
            aware = dt.replace(tzinfo=_utc_tz.utc) if dt.tzinfo is None else dt
            local = aware.astimezone(_BIZ_TZ)
            return local.strftime("%I:%M %p").lstrip("0")
    except Exception:
        pass
    return dt.strftime("%H:%M")

# GST state codes (CBIC list) — code → state name.
GST_STATES = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala",
    "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman & Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}


def _r2(x) -> float:
    return round(float(x or 0.0), 2)


def log_event(action: str, *, invoice_id=None, invoice_uid=None, business_id=None,
              user_id=None, template_type=None, business_type=None,
              success=True, error=None, **extra):
    """One structured log line per invoice-render event (plan §1.3).
    Shared by the payload builder and the /sales/print-events beacon route."""
    fields = {
        "action": action, "invoice_id": invoice_id, "invoice_uid": invoice_uid,
        "business_id": business_id, "user_id": user_id,
        "template_type": template_type, "business_type": business_type,
        "success": bool(success), "error": error,
    }
    fields.update(extra or {})
    line = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    if success:
        logger.info("[INVOICE_RENDER] %s", line)
    else:
        logger.warning("[INVOICE_RENDER] %s", line)


# ── Amount in words (Indian numbering: lakh / crore) ─────────────────────────

_UNITS = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
          "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
          "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
         "Eighty", "Ninety"]


def _under_100(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    return _TENS[n // 10] + ((" " + _UNITS[n % 10]) if n % 10 else "")


def _int_words(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    for div, label in ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand"), (100, "Hundred")):
        if n >= div:
            parts.append(_under_100(n // div) + " " + label)
            n %= div
    if n:
        parts.append(("and " if parts else "") + _under_100(n))
    return " ".join(parts)


def amount_in_words(amount: float) -> str:
    """₹ amount → 'X Rupees and Y Paise Only' (Indian numbering)."""
    try:
        amount = _r2(amount)
        rupees = int(amount)
        paise = int(round((amount - rupees) * 100))
        words = _int_words(rupees) + " Rupees"
        if paise:
            words += " and " + _under_100(paise) + " Paise"
        return words + " Only"
    except Exception:
        return ""


# ── Internals ─────────────────────────────────────────────────────────────────

def _user_print_settings(user: User) -> tuple:
    """→ (settings.print, settings.transactions) as dicts (empty on any parse issue)."""
    try:
        saved = json.loads(user.settings) if user and user.settings else {}
        pr = saved.get("print", {})
        tx = saved.get("transactions", {})
        return (pr if isinstance(pr, dict) else {}), (tx if isinstance(tx, dict) else {})
    except (ValueError, TypeError):
        return {}, {}


def _resolve_title(inv: Invoice, seller_gstin: str, transactions: dict) -> str:
    """Invoice title per plan §1.1. A stored invoice_title always wins."""
    stored = getattr(inv, "invoice_title", None)
    if stored:
        return stored
    itype = (inv.invoice_type or "").lower()
    status = (inv.status or "").lower()
    if itype == "estimate" or status == "estimate":
        return "Estimate"
    if itype == "proforma":
        return "Proforma Invoice"
    if (inv.total_amount or 0) < 0 or itype == "credit_note":
        return "Credit Note"
    if transactions.get("composite_scheme"):
        return "Bill of Supply"
    if seller_gstin:
        return "Tax Invoice"
    return "Retail Invoice"


def _line_out(idx: int, li) -> dict:
    gst_rate = _r2((li.cgst_rate or 0) + (li.sgst_rate or 0) + (li.igst_rate or 0))
    attrs = None
    raw_attrs = getattr(li, "attributes", None)
    if raw_attrs:
        try:
            attrs = json.loads(raw_attrs) if isinstance(raw_attrs, str) else raw_attrs
        except (ValueError, TypeError):
            attrs = None
    return {
        "sno": idx, "name": li.product_name or "Item", "description": li.description,
        "hsn_sac": li.hsn_sac, "batch_no": li.batch_no,
        "expiry": getattr(li, "expiry_date", None), "mrp": getattr(li, "mrp", None),
        "serial_no": li.serial_no,
        "qty": float(li.quantity or 0), "unit": li.unit or "Nos",
        "rate": _r2(li.unit_price), "discount": _r2(li.discount),
        "taxable_value": _r2(li.taxable_value), "gst_rate": gst_rate,
        "cgst": _r2(li.cgst_amount), "sgst": _r2(li.sgst_amount),
        "igst": _r2(li.igst_amount), "cess": _r2(li.cess_amount),
        "line_total": _r2(li.line_total), "attributes": attrs,
    }


def _tax_summary(lines: list) -> list:
    """HSN-wise tax annexure (GSTR-1 style): group by (hsn, gst_rate)."""
    groups = {}
    for l in lines:
        key = (l["hsn_sac"] or "—", l["gst_rate"])
        g = groups.setdefault(key, {"hsn": key[0], "rate": key[1],
                                    "taxable": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0})
        g["taxable"] += l["taxable_value"]
        g["cgst"] += l["cgst"]
        g["sgst"] += l["sgst"]
        g["igst"] += l["igst"]
    out = [{k: (_r2(v) if isinstance(v, float) else v) for k, v in g.items()}
           for g in groups.values()]
    return sorted(out, key=lambda g: (g["hsn"], g["rate"]))


def _payload_hash(invoice_no: str, totals: dict, lines: list) -> str:
    """Deterministic SHA-256 over the money-bearing content (2dp-formatted, so
    float noise can't shift it — same trick as the journal chain hash)."""
    body = {
        "invoice_no": invoice_no,
        "totals": {k: (f"{v:.2f}" if isinstance(v, (int, float)) and v is not None else v)
                   for k, v in totals.items() if k != "amount_in_words"},
        "lines": [[l["name"], f'{l["qty"]:g}', f'{l["rate"]:.2f}', f'{l["line_total"]:.2f}']
                  for l in lines],
    }
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _header_layout(pr: dict) -> list:
    saved = pr.get("header_layout")
    default = [
        {"key": "logo", "align": "center"},
        {"key": "company_name", "align": "center"},
        {"key": "company_address", "align": "center"},
        {"key": "company_contact", "align": "center"},
        {"key": "gstin", "align": "center"},
    ]
    if not saved or not isinstance(saved, list):
        return default
    clean = []
    valid_keys = [d["key"] for d in default]
    for l in saved:
        if isinstance(l, dict) and l.get("key") in valid_keys:
            align = l.get("align", "center")
            clean.append({
                "key": l["key"],
                "align": align if align in ("left", "center", "right") else "center"
            })
    present = {d["key"] for d in clean}
    for d in default:
        if d["key"] not in present:
            clean.append(d)
    return clean


# ── The builder ───────────────────────────────────────────────────────────────

def build_print_payload(db, *, business_id: int, invoice_no: str, user_id=None) -> dict:
    """Map one stored invoice → InvoicePrintPayload v1. Raises LookupError if the
    invoice doesn't exist for this business (route turns that into a 404)."""
    inv = (
        db.query(Invoice)
        .filter(Invoice.business_id == business_id, Invoice.invoice_id == invoice_no)
        .first()
    )
    if inv is None:
        raise LookupError(f"Invoice '{invoice_no}' not found")

    seller = db.query(User).filter(User.id == business_id).first()
    buyer_row = None
    if inv.customer_id:
        buyer_row = (
            db.query(Customer)
            .filter(Customer.id == inv.customer_id, Customer.business_id == business_id)
            .first()
        )

    cfg = T.resolve_for(business_id, db)
    business_type = cfg.get("key", "general")
    pr, tx = _user_print_settings(seller)

    cashier = db.query(User).filter(User.id == user_id).first() if user_id else seller
    counter_prefix = cashier.counter_prefix if cashier else None
    cashier_gen = {}
    if cashier and cashier.settings:
        try:
            cashier_gen = json.loads(cashier.settings).get("general", {})
        except Exception:
            pass

    seller_gstin = (seller.gstin or "").strip() if seller else ""
    gst_mode = bool(seller_gstin)
    lines = [_line_out(i + 1, li) for i, li in enumerate(inv.line_items)]
    igst_mode = _r2(inv.igst_total) > 0 or any(l["igst"] > 0 for l in lines)

    # ── Missing-field / mismatch checks (warn, never fail the render) ────────
    missing = []
    if gst_mode:
        if not (seller and seller.state_code):
            missing.append("seller.state_code")
        if (inv.invoice_type or "").upper() == "B2B":
            if not inv.gstin_buyer:
                missing.append("buyer.gstin")
            if not inv.place_of_supply:
                missing.append("invoice.place_of_supply")
    if missing:
        log_event("payload_missing_fields", invoice_id=inv.id, invoice_uid=getattr(inv, "uid", None),
                  business_id=business_id, user_id=user_id, business_type=business_type,
                  success=True, missing=",".join(missing))
    if gst_mode and igst_mode and seller and seller.state_code and inv.place_of_supply:
        pos_code = str(inv.place_of_supply).strip()[:2]
        if pos_code == str(seller.state_code).strip().zfill(2):
            log_event("gst_field_mismatch", invoice_id=inv.id, business_id=business_id,
                      business_type=business_type, success=True,
                      expected="inter-state place_of_supply", found=inv.place_of_supply)

    # ── Totals (all persisted by the command — nothing recomputed) ───────────
    grand = _r2(inv.total_amount if inv.total_amount is not None else inv.amount)
    paid = _r2(inv.paid_amount)
    totals = {
        "subtotal": _r2(inv.subtotal),                    # Σ taxable (command-defined)
        "total_discount": _r2(inv.discount_total),
        "taxable_amount": _r2(inv.subtotal),
        "cgst_total": _r2(inv.cgst_total), "sgst_total": _r2(inv.sgst_total),
        "igst_total": _r2(inv.igst_total), "cess_total": _r2(inv.cess_total),
        "round_off": _r2(inv.round_off),
        "cash_discount": _r2(getattr(inv, "cash_discount", 0)),
        "grand_total": grand,
        "amount_paid": paid,
        "balance_due": _r2(max(grand - paid, 0.0)),
        "amount_in_words": amount_in_words(grand),
    }

    # ── Payments (split-tender rows; legacy single-mode fallback) ────────────
    pay_rows = (
        db.query(InvoicePayment)
        .filter(InvoicePayment.business_id == business_id,
                InvoicePayment.invoice_id == inv.id)
        .order_by(InvoicePayment.id.asc())
        .all()
    )
    # `time` is the receipt's clock time in the business timezone (IST) — shown
    # next to the payment so a settlement reads e.g. "Settlement (FIFO) · 2026-07-22 1:21 AM".
    payments = [{"mode": p.payment_mode or "Cash", "amount": _r2(p.amount_paid),
                 "reference": p.note, "date": p.payment_date,
                 "time": _local_time_str(p.created_at)} for p in pay_rows]
    if not payments and paid > 0:
        payments = [{"mode": inv.payment_mode or "Cash", "amount": paid,
                     "reference": None, "date": inv.payment_date,
                     "time": _local_time_str(inv.created_at)}]

    # ── Visibility (resolved once, honored by every renderer) ────────────────
    columns = ["sno", "item", "qty", "unit", "rate", "discount", "total"]
    if gst_mode:
        columns += ["hsn", "taxable", "gst"]
        columns += ["igst"] if igst_mode else ["cgst", "sgst"]
    for col, key in (("batch", "batch_no"), ("expiry", "expiry"),
                     ("mrp", "mrp"), ("serial", "serial_no")):
        if any(l.get(key) for l in lines):
            columns.append(col)
    blocks = []
    if buyer_row and buyer_row.address:
        blocks.append("buyer_address")
    if pr.get("upi_id"):
        blocks.append("upi_qr")
    if pr.get("bank_details"):
        blocks.append("bank")
    if totals["balance_due"] > 0:
        blocks.append("balance_due")

    seller_state_code = str(seller.state_code).zfill(2) if seller and seller.state_code else None
    buyer_state_code = str(buyer_row.state_code).zfill(2) if buyer_row and buyer_row.state_code else None

    dt = inv.invoice_date or ""
    payload = {
        "version": PAYLOAD_VERSION,
        "invoice": {
            "id": inv.id, "uid": getattr(inv, "uid", None), "number": inv.invoice_id,
            "title": _resolve_title(inv, seller_gstin, tx),
            "date": dt, "time": _local_time_str(inv.created_at),
            "place_of_supply": inv.place_of_supply, "due_date": inv.due_date,
            "notes": inv.notes, "status": inv.status,
            "is_credit": bool((inv.total_amount or 0) < 0),
            "invoice_type": inv.invoice_type,
            "reverse_charge": bool(inv.reverse_charge),
            "uid_token": getattr(inv, "uid_token", None),
            "public_url": (
                f"{os.getenv('FRONTEND_URL', '').rstrip('/')}/public/invoice/{inv.uid_token}"
                if getattr(inv, "uid_token", None) else None
            ),
            "is_tax_inclusive": bool(inv.is_tax_inclusive),
        },
        "seller": {
            "name": (seller.business_name if seller else None) or "BizAssist Business",
            "logo_url": seller.logo if seller else None,
            "address": seller.address if seller else None,
            "phone": seller.phone if seller else None,
            "email": seller.email if seller else None,
            "gstin": seller_gstin or None,
            "state": GST_STATES.get(seller_state_code), "state_code": seller_state_code,
            "biz_id": seller.public_id if seller else None,
            "upi": ({"vpa": pr.get("upi_id")} if pr.get("upi_id") else None),
            "bank": pr.get("bank_details") or None,
        },
        "buyer": {
            "name": (buyer_row.name if buyer_row else None) or inv.customer or "Cash Sale",
            "phone": buyer_row.phone if buyer_row else None,
            "billing_address": buyer_row.address if buyer_row else None,
            "shipping_address": None,
            "gstin": inv.gstin_buyer or (buyer_row.gstin if buyer_row else None),
            "state": GST_STATES.get(buyer_state_code), "state_code": buyer_state_code,
            "customer_type": ("registered" if (inv.gstin_buyer or (buyer_row and buyer_row.gstin))
                              else ("wholesale" if buyer_row and buyer_row.price_tier == "wholesale"
                                    else "retail")),
        },
        "lines": lines,
        "totals": totals,
        "payments": payments,
        "tax_summary": _tax_summary(lines) if gst_mode else [],
        "footer": {
            "terms": pr.get("terms_conditions_text") if pr.get("print_terms_conditions", True) else None,
            "return_policy": pr.get("return_policy_text"),
            "signature_label": pr.get("signature_label", "Authorised Signatory"),
            "customer_signature_label": pr.get("customer_signature_label", "Customer Signature"),
            "thank_you": pr.get("thank_you_note", "Thank you for your business!"),
            "computer_generated_note": True,
        },
        "visibility": {"gst_mode": gst_mode, "igst_mode": igst_mode,
                       "columns": columns, "blocks": blocks},
        "settings": {
            "header_layout": _header_layout(pr),
            "print_item_sno": pr.get("print_item_sno", True),
            "print_item_hsn": pr.get("print_item_hsn", True),
            "print_item_tax": pr.get("print_item_tax", True),
            "print_tax_breakdown": pr.get("print_tax_breakdown", True),
            "print_amount_in_words": pr.get("print_amount_in_words", True),
            "print_signature": pr.get("print_signature", True),
            "customer_signature": pr.get("customer_signature", False),
            "prices_incl_gst": pr.get("prices_incl_gst", False),
            "fssai_no": pr.get("fssai_no"),
            "text_size": cashier_gen.get("text_size", pr.get("text_size", "medium")),
            "print_logo": pr.get("print_logo", True),
            "print_company_name": pr.get("print_company_name", True),
            "print_company_address": pr.get("print_company_address", True),
            "print_company_phone": pr.get("print_company_phone", True),
            "print_company_email": pr.get("print_company_email", True),
            "print_gstin": pr.get("print_gstin", True),
            "thermal_page_size": cashier_gen.get("thermal_page_size", pr.get("thermal_page_size", "3inch")),
            "counter_id": counter_prefix,
            "cashier_name": getattr(cashier, "username", "POS") if cashier else "POS",
            "print_invoice_qr": pr.get("print_invoice_qr", False),
        },
        "meta": {
            "business_type": business_type,
            "template_default": pr.get("invoice_template", "classic"),
            "generated_at": utc_now().isoformat() + "Z",
            "payload_hash": _payload_hash(inv.invoice_id, totals, lines),
        },
    }

    log_event("payload_built", invoice_id=inv.id, invoice_uid=getattr(inv, "uid", None),
              business_id=business_id, user_id=user_id, business_type=business_type,
              success=True, gst_mode=gst_mode, line_count=len(lines),
              payload_hash=payload["meta"]["payload_hash"][:12])
    return payload
