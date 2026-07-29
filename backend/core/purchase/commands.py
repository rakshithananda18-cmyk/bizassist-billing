import logging
import math
from datetime import datetime
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from database.models import PurchaseInvoice, PurchaseInvoiceLineItem, Product, Vendor, Inventory
from core.stock import ledger as SL

logger = logging.getLogger("bizassist.purchase")


_MONEY_TOLERANCE = 0.05


def _finite_number(value, field: str, *, minimum: Optional[float] = None) -> float:
    """Read a numeric request value without allowing NaN/Infinity into the books."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number.")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number.") from None
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number.")
    if minimum is not None and result < minimum:
        raise ValueError(f"{field} cannot be less than {minimum:g}.")
    return result


def _optional_money(value, field: str, *, minimum: float = 0.0) -> float:
    """Read optional invoice-level money fields, using zero only when omitted."""
    if value in (None, ""):
        return 0.0
    return _finite_number(value, field, minimum=minimum)


def _normalise_purchase_draft(invoice_data: dict) -> dict:
    """Validate and calculate the financial/stock facts of a purchase draft.

    OCR output and browser payloads are untrusted input.  The purchase header,
    line items, stock ledger and journal must therefore come from the same
    validated quantities, rates and taxes.  In particular, an empty bill or a
    zero/negative quantity must never result in a financial document or stock
    movement.
    """
    if not isinstance(invoice_data, dict):
        raise ValueError("Purchase bill data is invalid.")

    supplier_name = invoice_data.get("supplier_name")
    invoice_number = invoice_data.get("invoice_number")
    if not isinstance(supplier_name, str) or not supplier_name.strip():
        raise ValueError("Supplier name is required.")
    if not isinstance(invoice_number, str) or not invoice_number.strip():
        raise ValueError("Invoice number is required.")

    raw_items = invoice_data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("A purchase bill needs at least one item.")

    items = []
    subtotal = cgst_total = sgst_total = igst_total = 0.0
    for line_no, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            raise ValueError(f"Item {line_no} is invalid.")
        product_name = raw_item.get("product_name")
        if not isinstance(product_name, str) or not product_name.strip():
            raise ValueError(f"Item {line_no} needs a product name.")

        quantity = _finite_number(raw_item.get("quantity"), f"Item {line_no} quantity", minimum=0.0)
        conversion_factor = _finite_number(
            raw_item.get("conversion_factor", 1.0),
            f"Item {line_no} conversion factor",
            minimum=0.0,
        )
        unit_price = _finite_number(raw_item.get("unit_price"), f"Item {line_no} unit price", minimum=0.0)
        if quantity <= 0:
            raise ValueError(f"Item {line_no} quantity must be greater than zero.")
        if conversion_factor <= 0:
            raise ValueError(f"Item {line_no} conversion factor must be greater than zero.")

        tax_rates = {}
        for tax_name in ("cgst", "sgst", "igst"):
            rate = _optional_money(raw_item.get(f"{tax_name}_rate"), f"Item {line_no} {tax_name.upper()} rate")
            if rate > 100:
                raise ValueError(f"Item {line_no} {tax_name.upper()} rate cannot exceed 100%.")
            tax_rates[tax_name] = rate
        if sum(tax_rates.values()) > 100:
            raise ValueError(f"Item {line_no} combined GST rate cannot exceed 100%.")

        # Use the entered qty/rate as the sole source of every persisted
        # monetary line value.  Never trust stale OCR line totals after an edit.
        taxable_value = round(quantity * unit_price, 2)
        cgst_amount = round(taxable_value * tax_rates["cgst"] / 100, 2)
        sgst_amount = round(taxable_value * tax_rates["sgst"] / 100, 2)
        igst_amount = round(taxable_value * tax_rates["igst"] / 100, 2)
        line_total = round(taxable_value + cgst_amount + sgst_amount + igst_amount, 2)

        item = dict(raw_item)
        item.update({
            "product_name": product_name.strip(),
            "quantity": quantity,
            "conversion_factor": conversion_factor,
            "unit_price": unit_price,
            "taxable_value": taxable_value,
            "cgst_amount": cgst_amount,
            "sgst_amount": sgst_amount,
            "igst_amount": igst_amount,
            "line_total": line_total,
        })
        items.append(item)
        subtotal += taxable_value
        cgst_total += cgst_amount
        sgst_total += sgst_amount
        igst_total += igst_amount

    subtotal = round(subtotal, 2)
    cgst_total = round(cgst_total, 2)
    sgst_total = round(sgst_total, 2)
    igst_total = round(igst_total, 2)
    cess_total = _optional_money(invoice_data.get("cess_total"), "CESS total")
    discount_total = _optional_money(invoice_data.get("discount_total"), "Discount total")
    round_off = _optional_money(invoice_data.get("round_off"), "Round-off", minimum=-1.0)
    if round_off > 1.0:
        raise ValueError("Round-off must be between -1 and 1.")

    calculated_total = round(
        subtotal + cgst_total + sgst_total + igst_total + cess_total - discount_total + round_off,
        2,
    )
    if calculated_total <= 0:
        raise ValueError("Purchase bill total must be greater than zero.")

    # Non-zero supplied header values are an explicit claim about the source
    # document.  Reject conflicts rather than posting a payable which disagrees
    # with its stock lines.  A zero/missing OCR header is treated as absent and
    # filled from the reviewed lines.
    claimed_headers = {
        "subtotal": subtotal,
        "cgst_total": cgst_total,
        "sgst_total": sgst_total,
        "igst_total": igst_total,
        "total_amount": calculated_total,
    }
    for field, calculated in claimed_headers.items():
        supplied = _optional_money(invoice_data.get(field), field.replace("_", " "))
        if supplied and abs(supplied - calculated) > _MONEY_TOLERANCE:
            raise ValueError(
                f"Purchase bill {field.replace('_', ' ')} does not match its reviewed items. "
                "Correct the items or the invoice totals before confirming."
            )

    normalised = dict(invoice_data)
    normalised.update({
        "supplier_name": supplier_name.strip(),
        "invoice_number": invoice_number.strip(),
        "items": items,
        "subtotal": subtotal,
        "cgst_total": cgst_total,
        "sgst_total": sgst_total,
        "igst_total": igst_total,
        "cess_total": cess_total,
        "discount_total": discount_total,
        "round_off": round_off,
        "total_amount": calculated_total,
    })
    return normalised

def accept_supplier_invoice(db: Session, business_id: int, invoice_data: dict) -> PurchaseInvoice:
    """
    Transactional command to process and save a reviewed supplier invoice.
    
    1. Checks for idempotency/duplicates on (business_id, supplier_id, invoice_number).
    2. Resolves or creates Vendor.
    3. Resolves or creates catalog Products.
    4. Updates product cost prices and unit conversion configurations.
    5. Inserts PurchaseInvoice and PurchaseInvoiceLineItems.
    6. Records stock movements (quantity * conversion_factor) in append-only stock_ledger.
    """
    invoice_data = _normalise_purchase_draft(invoice_data)
    supplier_name = invoice_data["supplier_name"]
    invoice_number = invoice_data["invoice_number"]

    # 1. Resolve or create Vendor
    supplier_id = invoice_data.get("supplier_id")
    vendor = None
    if supplier_id:
        vendor = db.query(Vendor).filter(Vendor.id == supplier_id, Vendor.business_id == business_id).first()
    
    if not vendor:
        # Try finding vendor by name (case-insensitive)
        vendor = db.query(Vendor).filter(
            Vendor.name.ilike(supplier_name),
            Vendor.business_id == business_id
        ).first()
        
    if not vendor:
        # Create a new Vendor
        vendor = Vendor(
            name=supplier_name,
            business_id=business_id,
            is_active=True
        )
        db.add(vendor)
        db.flush() # Populate vendor ID
        
    supplier_id = vendor.id

    # 2. Check for duplicate/idempotency (business_id, supplier_id, invoice_number)
    duplicate = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.business_id == business_id,
        PurchaseInvoice.supplier_id == supplier_id,
        PurchaseInvoice.invoice_number == invoice_number
    ).first()
    
    if duplicate:
        raise ValueError(f"Purchase invoice '{invoice_number}' from supplier '{supplier_name}' has already been processed.")

    subtotal = invoice_data["subtotal"]
    cgst_total = invoice_data["cgst_total"]
    sgst_total = invoice_data["sgst_total"]
    igst_total = invoice_data["igst_total"]
    cess_total = invoice_data["cess_total"]
    total_amount = invoice_data["total_amount"]

    # 3. Create the PurchaseInvoice
    purchase_invoice = PurchaseInvoice(
        business_id=business_id,
        supplier_id=supplier_id,
        supplier_name=vendor.name,
        invoice_number=invoice_number,
        invoice_date=invoice_data.get("invoice_date"),
        due_date=invoice_data.get("due_date"),
        status=invoice_data.get("status", "Pending"),
        notes=invoice_data.get("notes"),
        file_id=invoice_data.get("file_id"),
        godown_id=invoice_data.get("godown_id"),
        
        # GST fields
        gstin_buyer=invoice_data.get("gstin_buyer"),
        place_of_supply=invoice_data.get("place_of_supply"),
        invoice_type=invoice_data.get("invoice_type"),
        subtotal=subtotal,
        cgst_total=cgst_total,
        sgst_total=sgst_total,
        igst_total=igst_total,
        cess_total=cess_total,
        total_amount=total_amount,
        reverse_charge=bool(invoice_data.get("reverse_charge") or False),
        is_tax_inclusive=bool(invoice_data.get("is_tax_inclusive") or False),
        discount_total=float(invoice_data.get("discount_total") or 0.0),
        round_off=float(invoice_data.get("round_off") or 0.0),
        irn=invoice_data.get("irn"),
        ack_no=invoice_data.get("ack_no"),
        ack_date=invoice_data.get("ack_date"),
        qr_code=invoice_data.get("qr_code")
    )
    db.add(purchase_invoice)
    db.flush() # Populate purchase_invoice.id

    # 4. Process line items
    for item in invoice_data.get("items", []):
        prod_name = item.get("product_name", "").strip()
        if not prod_name:
            continue
            
        product_id = item.get("product_id")
        product = None
        if product_id:
            product = db.query(Product).filter(Product.id == product_id, Product.business_id == business_id).first()
            
        if not product:
            # Check if product with this name already exists (case-insensitive)
            product = db.query(Product).filter(
                Product.name.ilike(prod_name),
                Product.business_id == business_id
            ).first()
            
        if not product:
            # Create new Product
            product = Product(
                name=prod_name,
                business_id=business_id,
                hsn_sac=item.get("hsn_sac"),
                unit=item.get("unit") or "Nos",
                purchase_unit=item.get("purchase_unit"),
                conversion_factor=float(item.get("conversion_factor") or 1.0),
                cost_price=float(item.get("unit_price") or 0.0),
                selling_price=float(item.get("unit_price") or 0.0) * 1.2, # default markup
                cgst_rate=float(item.get("cgst_rate") or 0.0),
                sgst_rate=float(item.get("sgst_rate") or 0.0),
                igst_rate=float(item.get("igst_rate") or 0.0),
                track_inventory=True,
                is_active=True
            )
            db.add(product)
            db.flush() # Populate product.id
        else:
            # Update existing Product's cost price
            product.cost_price = float(item.get("unit_price") or 0.0)
            if item.get("purchase_unit"):
                product.purchase_unit = item.get("purchase_unit")
            if item.get("conversion_factor") is not None:
                product.conversion_factor = float(item.get("conversion_factor") or 1.0)
            if item.get("hsn_sac"):
                product.hsn_sac = item.get("hsn_sac")
            db.flush()

        # Add new barcode if provided
        barcode = item.get("barcode")
        if barcode:
            try:
                from core.catalog.barcode import add_barcode
                add_barcode(db, business_id=business_id, product_id=product.id, code=barcode)
            except Exception as e:
                logger.warning(f"Failed to associate barcode '{barcode}' to product ID {product.id}: {e}")

        # Ensure Inventory row exists for the product cache (scoped by godown & batch)
        item_batch = item.get("batch")
        item_expiry = item.get("expiry")
        inv = db.query(Inventory).filter(
            Inventory.business_id == business_id,
            Inventory.product_id == product.id,
            Inventory.godown_id == purchase_invoice.godown_id,
            Inventory.batch_no == item_batch
        ).first()
        if not inv:
            inv = Inventory(
                business_id=business_id,
                product_id=product.id,
                product_name=product.name,
                stock=0,
                unit=product.unit,
                hsn_sac=product.hsn_sac,
                cost_price=item.get("cost_price") or product.cost_price,
                selling_price=item.get("selling_price") or product.selling_price,
                mrp=item.get("mrp") or product.mrp,
                supplier=vendor.name,
                vendor_id=vendor.id,
                godown_id=purchase_invoice.godown_id,
                batch_no=item_batch,
                expiry_date=item_expiry
            )
            db.add(inv)
            db.flush()
        else:
            # Keep vendor and prices in sync
            inv.cost_price = item.get("cost_price") or product.cost_price
            inv.selling_price = item.get("selling_price") or product.selling_price
            inv.mrp = item.get("mrp") or product.mrp
            inv.supplier = vendor.name
            inv.vendor_id = vendor.id
            if item_expiry:
                inv.expiry_date = item_expiry
            db.flush()

        # Create the PurchaseInvoiceLineItem
        line_item = PurchaseInvoiceLineItem(
            purchase_invoice_id=purchase_invoice.id,
            product_id=product.id,
            product_name=product.name,
            hsn_sac=item.get("hsn_sac"),
            unit=item.get("unit") or product.unit or "Nos",
            quantity=float(item.get("quantity") or 1.0),
            purchase_unit=item.get("purchase_unit") or product.purchase_unit,
            conversion_factor=float(item.get("conversion_factor") or 1.0),
            unit_price=float(item.get("unit_price") or 0.0),
            cgst_rate=float(item.get("cgst_rate") or 0.0),
            sgst_rate=float(item.get("sgst_rate") or 0.0),
            igst_rate=float(item.get("igst_rate") or 0.0),
            taxable_value=float(item.get("taxable_value") or 0.0),
            cgst_amount=float(item.get("cgst_amount") or 0.0),
            sgst_amount=float(item.get("sgst_amount") or 0.0),
            igst_amount=float(item.get("igst_amount") or 0.0),
            line_total=float(item.get("line_total") or 0.0),
            batch=item_batch,
            expiry=item_expiry,
            confidence_score=float(item.get("confidence_score") or 1.0),
            is_matched=bool(item.get("is_matched", True))
        )
        db.add(line_item)

        # Record stock movement (append-only ledger)
        qty_delta = line_item.quantity * line_item.conversion_factor
        
        SL.record_movement(
            db,
            business_id=business_id,
            movement_type=SL.PURCHASE,
            qty_delta=qty_delta,
            product_id=product.id,
            product_name=product.name,
            reference_type="purchase_invoice",
            reference_id=purchase_invoice.id,
            note=f"Purchase invoice #{invoice_number} from supplier {vendor.name}",
            godown_id=purchase_invoice.godown_id,
            batch_no=line_item.batch,
            expiry_date=line_item.expiry
        )

    # Post the balanced double-entry journal (audit trail) within this same txn.
    from core.accounting import posting
    posting.post_purchase(db, purchase_invoice)

    db.commit()
    return purchase_invoice


def create_debit_note(
    db: Session,
    business_id: int,
    original_purchase_id: int,
    lines: list,
    note: str = None,
    debit_note_no: str = None
) -> PurchaseInvoice:
    if not lines:
        raise ValueError("Debit note needs at least one line.")

    # 1. Fetch original purchase invoice
    orig = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.id == original_purchase_id,
        PurchaseInvoice.business_id == business_id
    ).first()
    
    if not orig:
        raise ValueError(f"Purchase invoice {original_purchase_id} not found.")

    # 2. Auto-generate debit note number
    dn_number = (debit_note_no or "").strip()
    if not dn_number:
        n = db.query(func.count(PurchaseInvoice.id)).filter(
            PurchaseInvoice.business_id == business_id,
            PurchaseInvoice.invoice_type == "debit_note"
        ).scalar() or 0
        dn_number = f"DN-{n + 1:04d}"

    # 3. Process line items
    dn_lines = []
    for ln in lines:
        pid = ln.get("product_id")
        qty = float(ln.get("quantity") or ln.get("qty") or 0)
        reason = ln.get("reason", "return")
        if qty <= 0:
            raise ValueError(f"Return quantity must be > 0 for product ID {pid}")

        # Find the original line item to get price and tax rates
        orig_line = None
        for li in orig.line_items:
            if li.product_id == pid:
                orig_line = li
                break
        
        if not orig_line:
            raise ValueError(f"Product ID {pid} was not found on the original purchase invoice.")

        unit_price = orig_line.unit_price or 0.0
        taxable = round(qty * unit_price, 2)
        cgst_r = orig_line.cgst_rate or 0.0
        sgst_r = orig_line.sgst_rate or 0.0
        igst_r = orig_line.igst_rate or 0.0
        
        cgst_a = round(taxable * cgst_r / 100.0, 2)
        sgst_a = round(taxable * sgst_r / 100.0, 2)
        igst_a = round(taxable * igst_r / 100.0, 2)
        line_total = round(taxable + cgst_a + sgst_a + igst_a, 2)

        # We also need conversion factor
        conv = orig_line.conversion_factor or 1.0

        dn_lines.append({
            "product_id": pid,
            "product_name": orig_line.product_name,
            "hsn_sac": orig_line.hsn_sac,
            "unit": orig_line.unit,
            "quantity": qty,
            "purchase_unit": orig_line.purchase_unit,
            "conversion_factor": conv,
            "unit_price": unit_price,
            "taxable_value": taxable,
            "cgst_rate": cgst_r,
            "sgst_rate": sgst_r,
            "igst_rate": igst_r,
            "cgst_amount": cgst_a,
            "sgst_amount": sgst_a,
            "igst_amount": igst_a,
            "line_total": line_total,
            "notes": reason,
            "expiry": orig_line.expiry,
            "batch": orig_line.batch
        })

    subtotal = round(sum(l["taxable_value"] for l in dn_lines), 2)
    cgst_t   = round(sum(l["cgst_amount"]   for l in dn_lines), 2)
    sgst_t   = round(sum(l["sgst_amount"]   for l in dn_lines), 2)
    igst_t   = round(sum(l["igst_amount"]   for l in dn_lines), 2)
    grand    = round(subtotal + cgst_t + sgst_t + igst_t, 2)

    # 4. Create the Debit Note header
    dn = PurchaseInvoice(
        business_id=business_id,
        supplier_id=orig.supplier_id,
        supplier_name=orig.supplier_name,
        invoice_number=dn_number,
        invoice_type="debit_note",
        invoice_date=datetime.today().strftime("%Y-%m-%d"),
        status="confirmed",
        total_amount=grand,
        subtotal=subtotal,
        cgst_total=cgst_t,
        sgst_total=sgst_t,
        igst_total=igst_t,
        notes=f"Debit note against purchase invoice #{orig.invoice_number}. {note or ''}".strip(),
    )
    db.add(dn)
    db.flush()

    # 5. Write line items + record RETURN_OUT stock movement (negative delta)
    for ln in dn_lines:
        line_item = PurchaseInvoiceLineItem(
            purchase_invoice_id=dn.id,
            product_id=ln["product_id"],
            product_name=ln["product_name"],
            hsn_sac=ln["hsn_sac"],
            unit=ln["unit"],
            quantity=ln["quantity"],
            purchase_unit=ln["purchase_unit"],
            conversion_factor=ln["conversion_factor"],
            unit_price=ln["unit_price"],
            cgst_rate=ln["cgst_rate"],
            sgst_rate=ln["sgst_rate"],
            igst_rate=ln["igst_rate"],
            taxable_value=ln["taxable_value"],
            cgst_amount=ln["cgst_amount"],
            sgst_amount=ln["sgst_amount"],
            igst_amount=ln["igst_amount"],
            line_total=ln["line_total"],
            expiry=ln["expiry"],
            batch=ln["batch"]
        )
        db.add(line_item)

        # Record stock reduction: quantity returned * conversion factor
        qty_delta = ln["quantity"] * ln["conversion_factor"]
        
        # Check if the product has track_inventory enabled
        product = db.query(Product).filter(
            Product.id == ln["product_id"],
            Product.business_id == business_id
        ).first()
        tracks = True if product is None else (product.track_inventory is not False)
        
        if tracks and qty_delta > 0:
            SL.record_movement(
                db,
                business_id=business_id,
                movement_type=SL.RETURN_OUT,
                qty_delta=-float(qty_delta), # negative for stock reduction!
                product_id=ln["product_id"],
                product_name=ln["product_name"],
                reference_type="purchase_invoice",
                reference_id=dn.id,
                note=f"Purchase return for invoice #{orig.invoice_number}"
            )

    # Post the reversal to the journal (Dr Cash/AP, Cr Purchases/GST Input).
    from core.accounting import posting
    posting.post_debit_note(db, dn)

    db.commit()
    logger.info("[PURCHASE] debit_note %s biz=%s orig=%s lines=%d total=%.2f",
                dn_number, business_id, orig.invoice_number, len(dn_lines), grand)
    db.refresh(dn)
    return dn
