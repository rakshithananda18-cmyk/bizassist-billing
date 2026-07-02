"""
core/billing/commands.py — the billing module's command handlers (Phase 1 + 1B).
=================================================================================
Command handlers:
  create_sale_invoice  — the billing counter command (Phase 1)
  record_payment       — append-only payment receipt (Phase 1B)
  create_credit_note   — return/reversal invoice, never edits the original (Phase 1B)

All commands:
  • ONE atomic transaction — the money write, any ledger movements, and status
    updates are committed together (all-or-nothing).
  • DETERMINISTIC — pure SQL arithmetic, never AI.
  • APPEND-ONLY — corrections are new rows, never overwrites.
  • IDEMPOTENT where applicable — same key → same result, not a double-post.

Money math lives here and is fully unit-tested. Routes stay thin.
"""
import logging
import re
from datetime import datetime
from typing import List, Optional

from sqlalchemy import func

from database.models import Invoice, InvoiceLineItem, Product, User
from core.models import InvoicePayment
from core.stock import ledger as SL

logger = logging.getLogger("bizassist.billing")


def _round2(x: float) -> float:
    return round(float(x or 0.0) + 1e-9, 2)


def _state_code(value: Optional[str]) -> Optional[str]:
    """Pull the 2-digit GST state code from '29' or '29-Karnataka' etc."""
    if not value:
        return None
    m = re.match(r"\s*(\d{2})", str(value))
    return m.group(1) if m else None


def _is_intra_state(business_state: Optional[str], place_of_supply: Optional[str]) -> bool:
    """
    Intra-state (CGST+SGST) when buyer's state == business state. If either is
    unknown, default to INTRA — the common local B2C retail case.
    """
    b = _state_code(business_state)
    p = _state_code(place_of_supply)
    if b is None or p is None:
        return True
    return b == p


def _line_rates(line: dict, product: Optional[Product]):
    """Resolve cgst/sgst/igst/cess rates: explicit line override → product → 0."""
    def pick(key):
        v = line.get(key)
        if v is not None:
            return float(v)
        if product is not None and getattr(product, key, None) is not None:
            return float(getattr(product, key))
        return 0.0
    return pick("cgst_rate"), pick("sgst_rate"), pick("igst_rate"), float(line.get("cess_rate") or 0.0)


def _compute_line(line: dict, product: Optional[Product], *, intra: bool, tax_inclusive: bool) -> dict:
    """
    Pure GST math for one line. Returns the fully-resolved line dict
    (taxable_value, per-head tax amounts, line_total) — no DB, no side effects.
    """
    qty   = float(line.get("quantity", 1) or 0)
    price = float(line.get("unit_price", 0) or 0)
    gross = qty * price

    # Line discount: absolute `discount` wins; else percent of gross.
    disc = float(line.get("discount") or 0.0)
    if not disc and line.get("discount_pct"):
        disc = gross * float(line["discount_pct"]) / 100.0
    net = max(gross - disc, 0.0)

    cgst_r, sgst_r, igst_r, cess_r = _line_rates(line, product)
    # Effective GST rate applied depends on intra/inter.
    gst_r = (cgst_r + sgst_r) if intra else igst_r
    total_r = gst_r + cess_r

    if tax_inclusive and total_r > 0:
        taxable = net / (1.0 + total_r / 100.0)
    else:
        taxable = net

    if intra:
        cgst_a = taxable * cgst_r / 100.0
        sgst_a = taxable * sgst_r / 100.0
        igst_a = 0.0
    else:
        cgst_a = 0.0
        sgst_a = 0.0
        igst_a = taxable * igst_r / 100.0
    cess_a = taxable * cess_r / 100.0
    line_total = taxable + cgst_a + sgst_a + igst_a + cess_a

    return {
        "product_id":   line.get("product_id"),
        "product_name": line.get("product_name") or (product.name if product else "Item"),
        "description":  line.get("description"),
        "hsn_sac":      line.get("hsn_sac") or (product.hsn_sac if product else None),
        "unit":         line.get("unit") or (product.unit if product else "Nos"),
        "quantity":     qty,
        "unit_price":   _round2(price),
        "discount":     _round2(disc),
        "discount_pct": float(line.get("discount_pct") or 0.0),
        "batch_no":     line.get("batch_no"),
        "serial_no":    line.get("serial_no"),
        # Sale-time print snapshots (invoice-template system, Phase 1). Nullable,
        # presentation-only — never enter the tax math above.
        "mrp":          (float(line["mrp"]) if line.get("mrp") is not None
                         else (product.mrp if product else None)),
        "expiry_date":  line.get("expiry_date"),
        "cgst_rate":    cgst_r if intra else 0.0,
        "sgst_rate":    sgst_r if intra else 0.0,
        "igst_rate":    0.0 if intra else igst_r,
        "cess_rate":    cess_r,
        "taxable_value": _round2(taxable),
        "cgst_amount":  _round2(cgst_a),
        "sgst_amount":  _round2(sgst_a),
        "igst_amount":  _round2(igst_a),
        "cess_amount":  _round2(cess_a),
        "line_total":   _round2(line_total),
    }


def _next_invoice_number(db, business_id: int, counter_prefix: Optional[str] = None) -> str:
    """Per-business, PER-COUNTER sequential number when the caller doesn't supply one.

    Multi-terminal POS (plan §9.3): each terminal owns its own number series via a
    distinct ``counter_prefix`` (e.g. ``C1``, ``C2``, ``OW``) so two counters can
    never mint the same number for different sales. We count only invoices already
    in THIS prefix's series, so a brand-new counter starts at 1 independently.

    ``counter_prefix`` may arrive with or without a trailing '-'; normalised here.
    Falls back to the legacy ``INV`` series for single-counter / unspecified callers.
    """
    prefix = (counter_prefix or "INV").strip().rstrip("-") or "INV"
    n = (
        db.query(func.count(Invoice.id))
        .filter(Invoice.business_id == business_id, Invoice.invoice_id.like(f"{prefix}-%"))
        .scalar()
        or 0
    )
    return f"{prefix}-{n + 1:04d}"


def _invoice_number_taken(db, business_id: int, number: str) -> bool:
    return (
        db.query(Invoice.id)
        .filter(Invoice.business_id == business_id, Invoice.invoice_id == number)
        .first()
        is not None
    )


def _free_invoice_number(db, business_id: int, taken: str) -> str:
    """Next FREE number in the SAME series as ``taken`` (keeps its exact prefix,
    incl. any ``LCL-`` tag). Used when a concurrent sale already grabbed the
    requested number — we re-number rather than silently merge two distinct bills
    (§9.3b). Bumps the trailing digits, preserving zero-pad width."""
    import re
    m = re.match(r"^(.*?)(\d+)$", taken or "")
    if not m:
        base, n, width = f"{taken}-", 2, 1
    else:
        base, n, width = m.group(1), int(m.group(2)) + 1, len(m.group(2))
    cand = f"{base}{str(n).zfill(width)}"
    while _invoice_number_taken(db, business_id, cand):
        n += 1
        cand = f"{base}{str(n).zfill(width)}"
    return cand


def create_sale_invoice(db, *, business_id: int, lines: list,
                        customer: Optional[str] = None,
                        customer_id: Optional[int] = None,
                        invoice_no: Optional[str] = None,
                        invoice_date: Optional[str] = None,
                        due_date: Optional[str] = None,
                        place_of_supply: Optional[str] = None,
                        invoice_type: Optional[str] = None,
                        payment_mode: Optional[str] = None,
                        paid_amount: float = 0.0,
                        reverse_charge: bool = False,
                        tax_inclusive: bool = False,
                        device_id: Optional[str] = None,
                        godown_id: Optional[int] = None,
                        bill_discount: float = 0.0,
                        cash_discount: float = 0.0,
                        counter_prefix: Optional[str] = None,
                        renumber_on_conflict: bool = False,
                        mark_paid: bool = False) -> Invoice:
    """
    COMMAND: create one sale invoice atomically (header + lines + stock moves).
    Commits the transaction.

    Numbering: the caller's ``invoice_no`` is used verbatim if given; otherwise a
    per-COUNTER number is allocated from ``counter_prefix`` (multi-terminal POS,
    plan §9.3 — each terminal owns its own series so two counters never collide).

    Idempotency: the authoritative retry guard is the route-level
    ``X-Client-Request-Id`` wall (``core.sync.idempotency`` — UNIQUE per business).
    The ``invoice_no`` match below is a benign SECONDARY wall: with per-counter
    prefixes a number is unique to one terminal's series, so a match here means a
    genuine retry of the SAME bill (safe to return), never two different sales
    merged — the silent-lost-sale failure mode that motivated §9.3.

    `lines`: list of dicts, each at least {quantity, unit_price} plus one of
    {product_id, product_name}; optional discount/discount_pct, tax rates
    (else taken from the product), hsn_sac, unit, batch_no, serial_no.

    Returns the persisted Invoice (with `.line_items` populated).
    """
    if not lines:
        raise ValueError("create_sale_invoice needs at least one line")

    number = (invoice_no or "").strip() or _next_invoice_number(db, business_id, counter_prefix)

    # ── Idempotency vs collision ─────────────────────────────────────────────
    existing = (
        db.query(Invoice)
        .filter(Invoice.business_id == business_id, Invoice.invoice_id == number)
        .first()
    )
    if existing is not None:
        if renumber_on_conflict:
            # A genuine retry of the SAME bill is caught upstream by the
            # X-Client-Request-Id wall, so reaching here with a taken number means
            # a DIFFERENT sale grabbed it concurrently (rare: same login/series on
            # two devices). Re-number into the next free slot in the same series
            # instead of returning the existing row → never merge two distinct
            # sales into one (silent lost bill, §9.3b). The caller prints/returns
            # this reassigned number.
            new_number = _free_invoice_number(db, business_id, number)
            logger.warning("[BILLING] invoice number %s already taken for biz %s — reassigned to %s",
                           number, business_id, new_number)
            number = new_number
        else:
            logger.info("[BILLING] idempotent hit — invoice %s already exists for biz %s",
                        number, business_id)
            return existing

    # ── State: intra vs inter (from business state + place of supply) ────────
    biz = db.query(User).filter(User.id == business_id).first()
    business_state = getattr(biz, "state_code", None) if biz else None
    intra = _is_intra_state(business_state, place_of_supply)

    # ── Compute every line (deterministic) ───────────────────────────────────
    computed = []
    for ln in lines:
        product = None
        if ln.get("product_id") is not None:
            product = db.query(Product).filter(
                Product.id == ln["product_id"], Product.business_id == business_id).first()
        elif ln.get("product_name"):
            product = db.query(Product).filter(
                Product.business_id == business_id, Product.name == ln["product_name"]).first()
        computed.append((_compute_line(ln, product, intra=intra, tax_inclusive=tax_inclusive),
                         product, ln))

    # ── Bill-level (whole-invoice) discount: apportion across lines by taxable
    #    share so the saved line items stay consistent with the header and GST is
    #    charged on the NET. No-op when bill_discount is 0 (the default), so all
    #    existing behaviour and tests are unchanged.
    bill_disc = max(_round2(bill_discount or 0.0), 0.0)
    gross_taxable = sum(c[0]["taxable_value"] for c in computed)
    if bill_disc > 0 and gross_taxable > 0:
        bd = min(bill_disc, gross_taxable)
        factor = (gross_taxable - bd) / gross_taxable
        for c in computed:
            ln = c[0]
            share = _round2(ln["taxable_value"] * (1.0 - factor))
            ln["discount"]      = _round2(ln["discount"] + share)
            ln["taxable_value"] = _round2(ln["taxable_value"] * factor)
            ln["cgst_amount"]   = _round2(ln["cgst_amount"] * factor)
            ln["sgst_amount"]   = _round2(ln["sgst_amount"] * factor)
            ln["igst_amount"]   = _round2(ln["igst_amount"] * factor)
            ln["cess_amount"]   = _round2(ln["cess_amount"] * factor)
            ln["line_total"]    = _round2(ln["taxable_value"] + ln["cgst_amount"]
                                          + ln["sgst_amount"] + ln["igst_amount"] + ln["cess_amount"])
        logger.info("[BILLING] applied bill discount %.2f (biz=%s) across %d lines",
                    bd, business_id, len(computed))

    subtotal = _round2(sum(c[0]["taxable_value"] for c in computed))
    cgst_t   = _round2(sum(c[0]["cgst_amount"]  for c in computed))
    sgst_t   = _round2(sum(c[0]["sgst_amount"]  for c in computed))
    igst_t   = _round2(sum(c[0]["igst_amount"]  for c in computed))
    cess_t   = _round2(sum(c[0]["cess_amount"]  for c in computed))
    disc_t   = _round2(sum(c[0]["discount"]     for c in computed))
    raw_total = subtotal + cgst_t + sgst_t + igst_t + cess_t
    rounded   = _round2(round(raw_total))           # round to nearest rupee
    round_off = _round2(rounded - raw_total)
    # Post-tax cash discount / round-off: reduces the PAYABLE only — never the
    # taxable value or GST (the "Cash Dis" line on real retail receipts; see
    # BENCHMARK_RECEIPT_MR_TRADERS.md). Clamped to [0, rounded]. 0 ⇒ exact no-op,
    # so all existing invoices/tests are unaffected.
    cash_disc = min(max(_round2(cash_discount or 0.0), 0.0), rounded)
    grand     = _round2(rounded - cash_disc)

    # mark_paid = "Paid & Print" at the counter → settle the full payable exactly,
    # immune to any cent-level drift between the client's payable and `grand`.
    paid = _round2(grand) if mark_paid else _round2(paid_amount)
    status = "Paid" if paid >= grand else ("Pending" if paid <= 0 else "Partial")

    # ── Write header ─────────────────────────────────────────────────────────
    inv = Invoice(
        business_id=business_id,
        invoice_id=number,
        customer=customer,
        customer_id=customer_id,
        godown_id=godown_id,
        amount=grand,                       # legacy total field
        total_amount=grand,
        status=status,
        invoice_date=(invoice_date or datetime.today().strftime("%Y-%m-%d")),
        due_date=due_date,
        place_of_supply=place_of_supply,
        invoice_type=invoice_type or ("B2B" if customer_id else "B2C"),
        reverse_charge=bool(reverse_charge),
        is_tax_inclusive=bool(tax_inclusive),
        subtotal=subtotal,
        cgst_total=cgst_t, sgst_total=sgst_t, igst_total=igst_t, cess_total=cess_t,
        discount_total=disc_t, round_off=round_off, cash_discount=cash_disc,
        paid_amount=paid, payment_mode=payment_mode,
        payment_date=(datetime.today().strftime("%Y-%m-%d") if paid > 0 else None),
    )
    db.add(inv)
    db.flush()                              # get inv.id for the line FKs + stock refs

    # Record the initial payment in InvoicePayment if the invoice is paid/partial at creation
    if paid > 0:
        pay_row = InvoicePayment(
            business_id=business_id,
            invoice_id=inv.id,
            customer_id=inv.customer_id,
            amount_paid=paid,
            payment_mode=payment_mode or "Cash",
            payment_date=inv.invoice_date,
            note=f"Initial payment for invoice {number}",
        )
        db.add(pay_row)

    # ── Write line items + stock movements (atomic) ──────────────────────────
    for c, product, raw in computed:
        db.add(InvoiceLineItem(invoice_id=inv.id, **c))

        # Deduct stock for stock-tracked products only.
        tracks = True if product is None else (product.track_inventory is not False)
        if tracks and c["quantity"]:
            line_batch_no = raw.get("batch_no")
            line_expiry_date = raw.get("expiry_date")
            SL.record_movement(
                db, business_id=business_id, movement_type=SL.SALE,
                qty_delta=-float(c["quantity"]),
                product_id=c["product_id"], product_name=c["product_name"],
                reference_type="invoice", reference_id=inv.id,
                note=f"sale {number}", device_id=device_id,
                godown_id=godown_id, batch_no=line_batch_no,
                expiry_date=line_expiry_date,
            )

    # Post the balanced double-entry journal (audit trail) within this same txn.
    from core.accounting import posting
    posting.post_sale(db, inv)

    db.commit()
    logger.info("[BILLING] sale %s biz=%s lines=%d total=%.2f status=%s intra=%s",
                number, business_id, len(computed), grand, status, intra)
    db.refresh(inv)
    return inv


# ---------------------------------------------------------------------------
# Phase 1B — RecordPayment
# ---------------------------------------------------------------------------

def record_payment(db, *, business_id: int, invoice_id: int,
                   amount_paid: float,
                   payment_mode: Optional[str] = None,
                   payment_date: Optional[str] = None,
                   note: Optional[str] = None,
                   idempotency_key: Optional[str] = None) -> InvoicePayment:
    """
    COMMAND: record one payment receipt against an invoice (append-only).
    Commits the transaction. Idempotent on (business_id, idempotency_key).

    Updates invoice.paid_amount and .status:
      paid_amount >= total_amount → 'Paid'
      0 < paid_amount < total_amount → 'Partial'
      paid_amount == 0 → 'Pending' (matches create_sale_invoice; dashboard filters on 'Pending')

    NEVER deletes or overwrites a payment row — corrections are new rows.
    """
    # ── Idempotency: same key → return existing row ───────────────────────────
    if idempotency_key:
        existing = (
            db.query(InvoicePayment)
            .filter(
                InvoicePayment.business_id == business_id,
                InvoicePayment.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing is not None:
            logger.info("[BILLING] record_payment idempotent hit — key=%s biz=%s",
                        idempotency_key, business_id)
            return existing

    # ── Validate: invoice must belong to this business ────────────────────────
    inv = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id, Invoice.business_id == business_id)
        .first()
    )
    if inv is None:
        raise ValueError(f"Invoice {invoice_id} not found for this business")

    if amount_paid <= 0:
        raise ValueError("amount_paid must be greater than 0")

    # ── Append payment row ────────────────────────────────────────────────────
    pay = InvoicePayment(
        business_id=business_id,
        invoice_id=invoice_id,
        customer_id=inv.customer_id,
        amount_paid=_round2(amount_paid),
        payment_mode=payment_mode,
        payment_date=payment_date or datetime.today().strftime("%Y-%m-%d"),
        note=note,
        idempotency_key=idempotency_key,
    )
    db.add(pay)

    # ── Update invoice paid_amount + status ───────────────────────────────────
    # Recompute from DB to be consistent (accumulated payments, not just this one).
    db.flush()  # make the new row visible in the SUM below
    total_paid = (
        db.query(func.coalesce(func.sum(InvoicePayment.amount_paid), 0.0))
        .filter(
            InvoicePayment.business_id == business_id,
            InvoicePayment.invoice_id == invoice_id,
        )
        .scalar()
    )
    inv.paid_amount = _round2(total_paid)
    grand = _round2(inv.total_amount or inv.amount or 0.0)
    if inv.paid_amount >= grand > 0:
        inv.status = "Paid"
    elif inv.paid_amount > 0:
        inv.status = "Partial"
    else:
        inv.status = "Pending"   # vocab consistent with create_sale_invoice + dashboard filters
    inv.payment_mode = payment_mode or inv.payment_mode
    inv.payment_date = payment_date or datetime.today().strftime("%Y-%m-%d")

    # Post the receipt to the journal (Dr Cash, Cr Accounts Receivable).
    from core.accounting import posting
    posting.post_payment(db, pay)

    db.commit()
    logger.info("[BILLING] payment biz=%s invoice=%s amount=%.2f status=%s",
                business_id, invoice_id, amount_paid, inv.status)
    db.refresh(pay)
    return pay


# ---------------------------------------------------------------------------
# Phase 1B — CreateCreditNote
# ---------------------------------------------------------------------------

def create_credit_note(db, *, business_id: int,
                       original_invoice_id: int,
                       lines: List[dict],
                       note: Optional[str] = None,
                       credit_note_no: Optional[str] = None) -> Invoice:
    """
    COMMAND: create a credit note (return/reversal) against an existing invoice.

    Rules:
      • NEVER edits the original invoice (append-only principle).
      • Creates a NEW Invoice row with invoice_type='credit_note' linked to the
        original via notes/invoice_id field convention.
      • Writes return_in stock movements for each returned product line.
      • Amounts are negative to represent reversal (credit note convention).

    `lines`: list of {product_id, qty, reason} — the items being returned.
    Returns the new credit note Invoice.
    """
    if not lines:
        raise ValueError("create_credit_note needs at least one line")

    # ── Validate: original invoice must belong to this business ───────────────
    orig = (
        db.query(Invoice)
        .filter(Invoice.id == original_invoice_id, Invoice.business_id == business_id)
        .first()
    )
    if orig is None:
        raise ValueError(f"Invoice {original_invoice_id} not found for this business")

    # Auto-generate credit note number
    cn_number = (credit_note_no or "").strip()
    if not cn_number:
        n = db.query(func.count(Invoice.id)).filter(
            Invoice.business_id == business_id,
            Invoice.invoice_type == "credit_note"
        ).scalar() or 0
        cn_number = f"CN-{n + 1:04d}"

    # ── Collect product info and compute lines ─────────────────────────────────
    cn_lines = []
    for ln in lines:
        pid = ln.get("product_id")
        qty = float(ln.get("qty") or ln.get("quantity") or 0)
        reason = ln.get("reason", "return")
        if qty <= 0:
            raise ValueError(f"Return qty must be > 0 for product {pid}")

        product = None
        if pid:
            product = db.query(Product).filter(
                Product.id == pid, Product.business_id == business_id
            ).first()

        # Find the original line to get pricing
        orig_line = None
        if pid and orig.line_items:
            for li in orig.line_items:
                if li.product_id == pid:
                    orig_line = li
                    break

        unit_price = (orig_line.unit_price if orig_line else 0.0) or 0.0
        taxable = _round2(qty * unit_price)
        cgst_r = (orig_line.cgst_rate if orig_line else 0.0) or 0.0
        sgst_r = (orig_line.sgst_rate if orig_line else 0.0) or 0.0
        igst_r = (orig_line.igst_rate if orig_line else 0.0) or 0.0
        cgst_a = _round2(taxable * cgst_r / 100.0)
        sgst_a = _round2(taxable * sgst_r / 100.0)
        igst_a = _round2(taxable * igst_r / 100.0)
        line_total = _round2(taxable + cgst_a + sgst_a + igst_a)

        cn_lines.append({
            "product_id": pid,
            "product_name": (product.name if product else
                             (orig_line.product_name if orig_line else f"Product {pid}")),
            "hsn_sac": (product.hsn_sac if product else
                        (orig_line.hsn_sac if orig_line else None)),
            "unit": (product.unit if product else
                     (orig_line.unit if orig_line else "Nos")),
            "quantity": qty,
            "unit_price": _round2(unit_price),
            "taxable_value": taxable,
            "cgst_rate": cgst_r, "sgst_rate": sgst_r, "igst_rate": igst_r,
            "cgst_amount": cgst_a, "sgst_amount": sgst_a, "igst_amount": igst_a,
            "line_total": line_total,
            "description": reason,
            "_product": product,
        })

    subtotal = _round2(sum(l["taxable_value"] for l in cn_lines))
    cgst_t   = _round2(sum(l["cgst_amount"]   for l in cn_lines))
    sgst_t   = _round2(sum(l["sgst_amount"]   for l in cn_lines))
    igst_t   = _round2(sum(l["igst_amount"]   for l in cn_lines))
    grand    = _round2(subtotal + cgst_t + sgst_t + igst_t)

    # ── Write credit note header ───────────────────────────────────────────────
    cn = Invoice(
        business_id=business_id,
        invoice_id=cn_number,
        customer=orig.customer,
        customer_id=orig.customer_id,
        invoice_type="credit_note",
        invoice_date=datetime.today().strftime("%Y-%m-%d"),
        status="Paid",  # a credit note is immediately settled
        amount=grand,
        total_amount=grand,
        subtotal=subtotal,
        cgst_total=cgst_t, sgst_total=sgst_t, igst_total=igst_t,
        paid_amount=grand,
        notes=f"Credit note against {orig.invoice_id}. {note or ''}".strip(),
    )
    db.add(cn)
    db.flush()  # get cn.id for FKs + stock refs

    # ── Write line items + return_in stock movements ───────────────────────────
    for ln in cn_lines:
        product = ln.pop("_product", None)
        db.add(InvoiceLineItem(invoice_id=cn.id, discount=0.0, discount_pct=0.0,
                               batch_no=None, serial_no=None, cess_rate=0.0,
                               cess_amount=0.0, **{k: v for k, v in ln.items()}))

        # Return stock for tracked products
        tracks = True if product is None else (product.track_inventory is not False)
        if tracks and ln["quantity"]:
            SL.record_movement(
                db, business_id=business_id,
                movement_type=SL.RETURN_IN,
                qty_delta=+float(ln["quantity"]),
                product_id=ln["product_id"],
                product_name=ln["product_name"],
                reference_type="credit_note",
                reference_id=cn.id,
                note=f"return for {orig.invoice_id}",
            )

    # Post the reversal to the journal (Dr Sales/GST, Cr Accounts Receivable).
    from core.accounting import posting
    posting.post_credit_note(db, cn)

    db.commit()
    logger.info("[BILLING] credit_note %s biz=%s orig=%s lines=%d total=%.2f",
                cn_number, business_id, orig.invoice_id, len(cn_lines), grand)
    db.refresh(cn)
    return cn
