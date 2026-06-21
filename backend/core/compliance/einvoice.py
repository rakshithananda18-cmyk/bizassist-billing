"""
core/compliance/einvoice.py — GST e-invoice (IRN) & e-way-bill JSON builders.
=============================================================================
Turns a persisted sale `Invoice` (+ its line items, seller, buyer) into the
JSON payloads the GST system expects:

  * `build_einvoice_payload()`  → Form GST INV-01 ("Generate IRN") schema v1.1,
    the body posted to an IRP (NIC / IRIS) to mint the 64-char IRN + signed QR.
  * `build_eway_payload()`      → the standalone e-Way Bill "GenEWayBill" body.

Design choices (deliberate, so the output is trustworthy):
  * PURE functions over ORM objects — no DB, no network, no commit. The route
    (or a test) loads the rows and passes them in, so the math is unit-testable
    in isolation and the IRP/EWB HTTP call stays a separate concern.
  * SELF-CONSISTENT money: every figure is derived from the line items and the
    persisted tax amounts, then footed so item sums reconcile with ValDtls to
    within ₹1 (the tolerance the IRP enforces). We never invent taxes.
  * VALIDATE, don't guess: rather than emit silently-invalid JSON, each builder
    returns `(payload, warnings)`. `warnings` lists every mandatory field that
    is missing/blank (no seller GSTIN, no HSN, B2C buyer, …) so the caller can
    surface "fix these before filing" instead of a cryptic IRP rejection.

References: GST e-invoice schema (Form GST INV-01) v1.1; NIC e-Way Bill API.
"""
import logging
import re
from datetime import datetime

logger = logging.getLogger("bizassist.compliance")

SCHEMA_VERSION = "1.1"
GSTIN_RE = re.compile(r"^[0-9]{2}[0-9A-Z]{13}$")

# ── Statutory thresholds (verified 2026-06; see master plan §10.3 R7a) ────────
# E-way bill: mandatory once a single consignment's value exceeds ₹50,000
# (inter-state, uniform nationwide; some states set their own intra-state limit).
EWAY_THRESHOLD = 50000.0
# E-invoice (IRN): mandatory at ₹5 crore PAN-level aggregate annual turnover in any
# FY from 2017-18 onward. Turnover is a PAN-level figure we can't derive from a
# single tenant's data, so applicability is gated by an explicit per-business flag
# the owner sets once they cross the limit (a ₹2 cr reduction is proposed, not law).
EINVOICE_TURNOVER_THRESHOLD = 50000000.0


def eway_required(invoice, threshold: float = EWAY_THRESHOLD) -> bool:
    """True when this invoice's value crosses the e-way-bill threshold (₹50,000)."""
    return _r2(getattr(invoice, "total_amount", 0.0)) > threshold


def einvoice_applicable(e_invoice_enabled) -> bool:
    """Whether the business must issue e-invoices — gated by the owner-set flag,
    since the ₹5 cr trigger is PAN-level turnover that the app can't compute."""
    return bool(e_invoice_enabled)


# ── small helpers ─────────────────────────────────────────────────────────────

def _r2(x) -> float:
    return round(float(x or 0.0), 2)


def _s(x) -> str:
    return ("" if x is None else str(x)).strip()


def _fmt_date(d) -> str:
    """ISO 'YYYY-MM-DD' (how we persist) → e-invoice 'DD/MM/YYYY'. Blank stays blank."""
    s = _s(d)
    if not s:
        return ""
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s  # already some other format — pass through rather than crash


def _state_code(value, gstin=None) -> str:
    """2-digit GST state code. Prefer the first 2 digits of a GSTIN (authoritative),
    else a 2-digit `state_code` string, else ''."""
    g = _s(gstin)
    if len(g) >= 2 and g[:2].isdigit():
        return g[:2]
    v = _s(value)
    m = re.match(r"^(\d{1,2})", v)
    if m:
        return m.group(1).zfill(2)
    return ""


def _split_addr(address):
    """Free-text address → (Addr1, Addr2, Loc, Pin). Best-effort, never raises.
    Pin = first 6-digit run; Loc = last comma-separated chunk without the pin."""
    a = _s(address)
    pin = ""
    mp = re.search(r"\b(\d{6})\b", a)
    if mp:
        pin = mp.group(1)
        a = (a[:mp.start()] + a[mp.end():]).strip(" ,")
    parts = [p.strip() for p in a.split(",") if p.strip()]
    if not parts:
        return "", "", "", pin
    addr1 = parts[0]
    loc = parts[-1] if len(parts) > 1 else parts[0]
    addr2 = ", ".join(parts[1:-1]) if len(parts) > 2 else ""
    return addr1, addr2, loc, pin


def _item_rows(invoice, intra):
    """Per-item INV-01 rows + footed totals, derived from the stored line items."""
    rows, tot = [], {"ass": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0,
                     "cess": 0.0, "inv": 0.0}
    for i, li in enumerate(invoice.line_items, start=1):
        qty = float(li.quantity or 0.0)
        unit_price = _r2(li.unit_price)
        gross = _r2(unit_price * qty)
        disc = _r2(li.discount)
        ass = _r2(li.taxable_value)
        cgst = _r2(li.cgst_amount)
        sgst = _r2(li.sgst_amount)
        igst = _r2(li.igst_amount)
        cess = _r2(getattr(li, "cess_amount", 0.0))
        gst_rt = _r2((li.cgst_rate or 0) + (li.sgst_rate or 0)) if intra else _r2(li.igst_rate)
        item_val = _r2(ass + cgst + sgst + igst + cess)
        rows.append({
            "SlNo": str(i),
            "PrdDesc": _s(li.product_name) or "Item",
            "IsServc": "N",
            "HsnCd": _s(li.hsn_sac),
            "Qty": qty,
            "Unit": (_s(li.unit) or "NOS").upper()[:8],
            "UnitPrice": unit_price,
            "TotAmt": gross,
            "Discount": disc,
            "AssAmt": ass,
            "GstRt": gst_rt,
            "IgstAmt": igst,
            "CgstAmt": cgst,
            "SgstAmt": sgst,
            "CesRt": _r2(getattr(li, "cess_rate", 0.0)),
            "CesAmt": cess,
            "TotItemVal": item_val,
        })
        tot["ass"] += ass
        tot["cgst"] += cgst
        tot["sgst"] += sgst
        tot["igst"] += igst
        tot["cess"] += cess
        tot["inv"] += item_val
    for k in tot:
        tot[k] = _r2(tot[k])
    return rows, tot


# ── e-invoice (IRN) ───────────────────────────────────────────────────────────

def build_einvoice_payload(*, seller, invoice, buyer=None):
    """Build the Form GST INV-01 payload for IRN generation.

    `seller`  : the business User row (gstin, business_name, address, state_code…).
    `invoice` : the sale Invoice with `.line_items` loaded.
    `buyer`   : the Customer row (None ⇒ walk-in / B2C).

    Returns (payload: dict, warnings: list[str]). A non-empty `warnings` means the
    IRP would reject the payload until those mandatory gaps are fixed.
    """
    warnings = []

    seller_gstin = _s(getattr(seller, "gstin", "")).upper()
    buyer_gstin = _s(getattr(buyer, "gstin", "")).upper() if buyer else ""

    # Place of supply drives intra (CGST+SGST) vs inter (IGST).
    pos = _state_code(getattr(invoice, "place_of_supply", ""), buyer_gstin) \
        or _state_code(getattr(buyer, "state_code", "") if buyer else "", buyer_gstin)
    seller_stcd = _state_code(getattr(seller, "state_code", ""), seller_gstin)
    intra = bool(pos) and bool(seller_stcd) and pos == seller_stcd
    # Fall back to the persisted tax split when state codes are unavailable.
    if not pos and not seller_stcd:
        intra = _r2(invoice.igst_total) <= 0

    s_a1, s_a2, s_loc, s_pin = _split_addr(getattr(seller, "address", ""))
    items, tot = _item_rows(invoice, intra)

    round_off = _r2(getattr(invoice, "round_off", 0.0))
    tot_inv_val = _r2(tot["inv"] + round_off)

    payload = {
        "Version": SCHEMA_VERSION,
        "TranDtls": {
            "TaxSch": "GST",
            "SupTyp": "B2B",
            "RegRev": "Y" if getattr(invoice, "reverse_charge", False) else "N",
            "IgstOnIntra": "N",
        },
        "DocDtls": {
            "Typ": "INV",
            "No": _s(invoice.invoice_id),
            "Dt": _fmt_date(invoice.invoice_date),
        },
        "SellerDtls": {
            "Gstin": seller_gstin,
            "LglNm": _s(getattr(seller, "business_name", "")) or "Seller",
            "Addr1": s_a1 or "NA",
            "Addr2": s_a2,
            "Loc": s_loc or "NA",
            "Pin": s_pin,
            "Stcd": seller_stcd,
            "Ph": _s(getattr(seller, "phone", "")),
            "Em": _s(getattr(seller, "email", "")),
        },
        "BuyerDtls": _buyer_block(buyer, buyer_gstin, pos),
        "ItemList": items,
        "ValDtls": {
            "AssVal": tot["ass"],
            "CgstVal": tot["cgst"],
            "SgstVal": tot["sgst"],
            "IgstVal": tot["igst"],
            "CesVal": tot["cess"],
            "RndOffAmt": round_off,
            "TotInvVal": tot_inv_val,
        },
    }

    # ── mandatory-field validation ───────────────────────────────────────────
    if not GSTIN_RE.match(seller_gstin):
        warnings.append("Seller GSTIN missing or malformed (15-char GSTIN required).")
    if not buyer or not GSTIN_RE.match(buyer_gstin):
        warnings.append("Buyer GSTIN missing — e-invoice/IRN applies to B2B only "
                        "(B2C invoices are not reported to the IRP).")
    if not payload["DocDtls"]["No"]:
        warnings.append("Document number (invoice_id) is blank.")
    if not payload["DocDtls"]["Dt"]:
        warnings.append("Document date is blank/invalid.")
    if not items:
        warnings.append("Invoice has no line items.")
    for r in items:
        if not r["HsnCd"]:
            warnings.append(f"Line {r['SlNo']} ({r['PrdDesc']}): HSN/SAC code missing.")
    if not payload["SellerDtls"]["Pin"]:
        warnings.append("Seller PIN code could not be derived from the address.")
    if _r2(getattr(invoice, "cash_discount", 0.0)) > 0:
        warnings.append("Cash discount is not represented in INV-01; TotInvVal reflects "
                        "the pre-cash-discount value (item sums + round-off).")

    logger.info("[COMPLIANCE] built e-invoice INV-01 inv=%s biz=%s intra=%s totinv=%.2f warns=%d",
                _s(invoice.invoice_id), getattr(invoice, "business_id", None),
                intra, tot_inv_val, len(warnings))
    return payload, warnings


def _buyer_block(buyer, buyer_gstin, pos):
    if buyer is None:
        return {"Gstin": "URP", "LglNm": "Walk-in / Unregistered", "Pos": pos or "96",
                "Addr1": "NA", "Loc": "NA", "Stcd": pos}
    b_a1, b_a2, b_loc, b_pin = _split_addr(getattr(buyer, "address", ""))
    return {
        "Gstin": buyer_gstin or "URP",
        "LglNm": _s(getattr(buyer, "name", "")) or "Buyer",
        "Pos": pos or _state_code(getattr(buyer, "state_code", ""), buyer_gstin) or "96",
        "Addr1": b_a1 or "NA",
        "Addr2": b_a2,
        "Loc": b_loc or "NA",
        "Pin": b_pin,
        "Stcd": _state_code(getattr(buyer, "state_code", ""), buyer_gstin),
        "Ph": _s(getattr(buyer, "phone", "")),
        "Em": _s(getattr(buyer, "email", "")),
    }


# ── e-Way Bill ────────────────────────────────────────────────────────────────

_TRANS_MODE = {"road": "1", "rail": "2", "air": "3", "ship": "4",
               "1": "1", "2": "2", "3": "3", "4": "4"}


def build_eway_payload(*, seller, invoice, buyer=None, transport=None):
    """Build the NIC e-Way Bill ("GenEWayBill") payload from a sale invoice.

    `transport` (optional dict): {mode, distance, transporter_id, transporter_name,
    trans_doc_no, trans_doc_date, vehicle_no, vehicle_type}. Distance + mode (or a
    transporter id) are the practical minimum NIC enforces.

    Returns (payload: dict, warnings: list[str]).
    """
    transport = transport or {}
    warnings = []

    seller_gstin = _s(getattr(seller, "gstin", "")).upper()
    buyer_gstin = _s(getattr(buyer, "gstin", "")).upper() if buyer else "URP"

    pos = _state_code(getattr(invoice, "place_of_supply", ""), buyer_gstin) \
        or _state_code(getattr(buyer, "state_code", "") if buyer else "", buyer_gstin)
    seller_stcd = _state_code(getattr(seller, "state_code", ""), seller_gstin)
    intra = bool(pos) and bool(seller_stcd) and pos == seller_stcd
    if not pos and not seller_stcd:
        intra = _r2(invoice.igst_total) <= 0

    s_a1, s_a2, s_loc, s_pin = _split_addr(getattr(seller, "address", ""))
    b_a1, b_a2, b_loc, b_pin = _split_addr(getattr(buyer, "address", "") if buyer else "")

    item_list = []
    for li in invoice.line_items:
        gst_rt = _r2((li.cgst_rate or 0) + (li.sgst_rate or 0)) if intra else _r2(li.igst_rate)
        item_list.append({
            "productName": _s(li.product_name) or "Item",
            "hsnCode": _s(li.hsn_sac),
            "quantity": float(li.quantity or 0.0),
            "qtyUnit": (_s(li.unit) or "NOS").upper()[:3],
            "taxableAmount": _r2(li.taxable_value),
            "cgstRate": _r2(li.cgst_rate) if intra else 0.0,
            "sgstRate": _r2(li.sgst_rate) if intra else 0.0,
            "igstRate": 0.0 if intra else _r2(li.igst_rate),
            "cessRate": _r2(getattr(li, "cess_rate", 0.0)),
        })

    raw_mode = _s(transport.get("mode")).lower()
    trans_mode = _TRANS_MODE.get(raw_mode, "1")
    distance = int(transport.get("distance") or 0)

    payload = {
        "supplyType": "O",                      # Outward
        "subSupplyType": "1",                   # 1 = Supply
        "docType": "INV",
        "docNo": _s(invoice.invoice_id),
        "docDate": _fmt_date(invoice.invoice_date),
        "fromGstin": seller_gstin or "URP",
        "fromTrdName": _s(getattr(seller, "business_name", "")),
        "fromAddr1": s_a1, "fromAddr2": s_a2, "fromPlace": s_loc,
        "fromPincode": int(s_pin) if s_pin.isdigit() else 0,
        "fromStateCode": int(seller_stcd) if seller_stcd.isdigit() else 0,
        "actFromStateCode": int(seller_stcd) if seller_stcd.isdigit() else 0,
        "toGstin": buyer_gstin or "URP",
        "toTrdName": _s(getattr(buyer, "name", "")) if buyer else "Walk-in",
        "toAddr1": b_a1, "toAddr2": b_a2, "toPlace": b_loc,
        "toPincode": int(b_pin) if b_pin.isdigit() else 0,
        "toStateCode": int(pos) if pos.isdigit() else 0,
        "actToStateCode": int(pos) if pos.isdigit() else 0,
        "totalValue": _r2(invoice.subtotal),
        "cgstValue": _r2(invoice.cgst_total),
        "sgstValue": _r2(invoice.sgst_total),
        "igstValue": _r2(invoice.igst_total),
        "cessValue": _r2(getattr(invoice, "cess_total", 0.0)),
        "totInvValue": _r2(invoice.total_amount),
        "transactionType": 1,
        "transMode": trans_mode,
        "transDistance": str(distance),
        "transporterId": _s(transport.get("transporter_id")),
        "transporterName": _s(transport.get("transporter_name")),
        "transDocNo": _s(transport.get("trans_doc_no")),
        "transDocDate": _fmt_date(transport.get("trans_doc_date")),
        "vehicleNo": _s(transport.get("vehicle_no")).upper(),
        "vehicleType": (_s(transport.get("vehicle_type")) or "R").upper()[:1],
        "itemList": item_list,
    }

    if not GSTIN_RE.match(seller_gstin):
        warnings.append("Seller (from) GSTIN missing or malformed.")
    if distance <= 0:
        warnings.append("Transport distance (km) is required for the e-way bill.")
    if trans_mode == "1" and not payload["vehicleNo"] and not payload["transDocNo"]:
        warnings.append("Road transport: a vehicle number or transport document number is required.")
    if not payload["docNo"]:
        warnings.append("Document number (invoice_id) is blank.")
    if not item_list:
        warnings.append("Invoice has no line items.")

    logger.info("[COMPLIANCE] built e-way bill inv=%s biz=%s dist=%s mode=%s warns=%d",
                _s(invoice.invoice_id), getattr(invoice, "business_id", None),
                distance, trans_mode, len(warnings))
    return payload, warnings
