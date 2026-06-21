import logging
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from database.models import PurchaseInvoice, PurchaseInvoiceLineItem, Product, Vendor, Inventory
from core.stock import ledger as SL

logger = logging.getLogger("bizassist.purchase")

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
    supplier_name = invoice_data.get("supplier_name", "").strip()
    invoice_number = invoice_data.get("invoice_number", "").strip()
    
    if not supplier_name:
        raise ValueError("Supplier name is required.")
    if not invoice_number:
        raise ValueError("Invoice number is required.")

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

    subtotal = float(invoice_data.get("subtotal") or 0.0)
    cgst_total = float(invoice_data.get("cgst_total") or 0.0)
    sgst_total = float(invoice_data.get("sgst_total") or 0.0)
    igst_total = float(invoice_data.get("igst_total") or 0.0)
    cess_total = float(invoice_data.get("cess_total") or 0.0)
    total_amount = float(invoice_data.get("total_amount") or 0.0)

    items = invoice_data.get("items", [])
    if subtotal == 0.0 and items:
        subtotal = sum(float(item.get("taxable_value") or 0.0) for item in items)
    if cgst_total == 0.0 and items:
        cgst_total = sum(float(item.get("cgst_amount") or 0.0) for item in items)
    if sgst_total == 0.0 and items:
        sgst_total = sum(float(item.get("sgst_amount") or 0.0) for item in items)
    if igst_total == 0.0 and items:
        igst_total = sum(float(item.get("igst_amount") or 0.0) for item in items)
    if cess_total == 0.0 and items:
        cess_total = sum(float(item.get("cess_amount") or 0.0) for item in items)
    if total_amount == 0.0 and items:
        total_amount = sum(float(item.get("line_total") or 0.0) for item in items)

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

