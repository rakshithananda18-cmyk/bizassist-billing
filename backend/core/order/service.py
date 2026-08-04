"""
core/order/service.py
=====================
Domain service logic for B2B Ordering and Catalog visibility.
"""
import logging
import uuid
from services.dates import utc_now
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from core.models import B2BConnection, B2BOrder, B2BOrderLineItem
from core.billing import sequence as SEQ
from database.models import (
    Customer, Invoice, Product, Inventory, PurchaseInvoice,
    PurchaseInvoiceLineItem, User, Vendor,
)

logger = logging.getLogger("bizassist.order")


def _next_order_number(db: Session) -> str:
    """Allocate the next B2B order number: ``ORD-YYYYMMDD-NNNN``.

    REPLACES AN UNBOUNDED RANDOM-RETRY LOOP (review finding M-4)
    -----------------------------------------------------------
    The old implementation span ``while True`` generating a 4-character suffix
    from a 32-character alphabet and re-querying until it found a free one.
    Three problems, all of which get worse exactly as the product succeeds:

      · **Birthday collisions.** 32^4 ≈ 1.05M values, but collision probability
        follows the birthday bound — around 1,000 orders in a day it is already
        ~50% likely that two draws collide, and every collision costs another
        round trip.
      · **No attempt cap.** ``while True`` with a shrinking pool of free values
        is an unbounded loop inside a request. As a day fills up it degrades
        from "one extra query" to "hangs".
      · **Check-then-insert is not atomic.** Two concurrent orders can both see
        the number as free; ``B2BOrder.order_number`` is ``unique=True``, so one
        of them dies with a 500 on insert — after the caller already believed
        the order was placed.

    All three are properties of *guessing*. Counting instead removes them: the
    number is reserved with a single atomic UPDATE, bounded, and collision-free
    by construction.

    SCOPE is ``SEQ.SYSTEM_SCOPE``, not a business. ``order_number`` is globally
    unique because an order is a shared record two tenants both quote, so a
    per-buyer counter would have every buyer minting ...-0001 on the same
    morning and all but one failing the constraint. Safe because B2B is
    cloud-authoritative (architecture rule 2) — order creation only ever runs
    against the one cloud database.

    The series is date-scoped, so numbering restarts at 0001 each day and the
    date in the reference stays meaningful.
    """
    series = f"ORD-{utc_now().strftime('%Y%m%d')}"
    return SEQ.next_number(
        db, SEQ.SYSTEM_SCOPE, series,
        # Bounded to one day's orders, and only consulted when the counter is
        # brand new or has fallen behind — never on the hot path.
        scan_max=lambda: SEQ.max_suffix(
            (r[0] for r in db.query(B2BOrder.order_number)
             .filter(B2BOrder.order_number.like(SEQ.like_prefix(series), escape="\\"))
             .all()),
            series,
        ),
        # The uniqueness constraint is global, so the probe must be too — no
        # business_id filter here, deliberately.
        is_taken=lambda num: db.query(B2BOrder.id).filter(
            B2BOrder.order_number == num).first() is not None,
    )

def get_supplier_catalog(db: Session, buyer_business_id: int, seller_business_id: int) -> List[Dict[str, Any]]:
    """
    Get the seller's catalog filtered and priced according to the B2BConnection policy.
    """
    conn = db.query(B2BConnection).filter(
        B2BConnection.seller_business_id == seller_business_id,
        B2BConnection.buyer_business_id == buyer_business_id,
        B2BConnection.status == "accepted"
    ).first()
    
    if not conn:
        raise PermissionError("No active connection with this supplier")
        
    query = db.query(Product).filter(
        Product.business_id == seller_business_id,
        Product.is_active == True
    )
    
    if conn.catalog_category:
        query = query.filter(Product.category == conn.catalog_category)
        
    products = query.order_by(Product.name.asc()).all()
    product_ids = [p.id for p in products]

    # ── Barcodes, resolved in ONE query for the whole catalogue ──────────────
    # Barcodes travel with the catalogue so the buyer can SCAN to order: a GTIN
    # is identical in both businesses' systems, so the buyer's existing counter
    # scanner works against the supplier's list with zero setup.
    # Batched deliberately — a per-product lookup would be an N+1 over a list
    # that can run to thousands of SKUs.
    barcodes_by_product = {}
    if product_ids:
        try:
            from database.models import ProductBarcode
            rows = (
                db.query(ProductBarcode.product_id, ProductBarcode.barcode)
                .filter(
                    ProductBarcode.business_id == seller_business_id,
                    ProductBarcode.product_id.in_(product_ids),
                    ProductBarcode.active == True,  # noqa: E712
                )
                .all()
            )
            for pid, code in rows:
                if code:
                    barcodes_by_product.setdefault(pid, []).append(code)
        except Exception as e:
            # Barcodes are an ordering convenience, never a correctness
            # requirement — a failure here must not take the catalogue down.
            logger.warning("Catalogue barcode lookup failed: %s", e)

    # Inventory, also batched (was one query per product).
    stock_by_product = {}
    if product_ids:
        for pid, qty in (
            db.query(Inventory.product_id, Inventory.stock)
            .filter(Inventory.business_id == seller_business_id,
                    Inventory.product_id.in_(product_ids))
            .all()
        ):
            stock_by_product[pid] = qty

    catalog = []
    for p in products:
        # Resolve base price based on price tier
        base_price = p.selling_price
        if conn.price_tier == "wholesale":
            base_price = p.wholesale_price if (p.wholesale_price and p.wholesale_price > 0.0) else p.selling_price
        elif conn.price_tier == "distributor":
            base_price = p.distributor_price if (p.distributor_price and p.distributor_price > 0.0) else (p.wholesale_price if (p.wholesale_price and p.wholesale_price > 0.0) else p.selling_price)

        # Resolve price based on discount
        discount_factor = 1.0 - (conn.discount_pct / 100.0)
        custom_price = base_price * discount_factor
        
        # Get stock level (pre-resolved above)
        raw_stock = stock_by_product.get(p.id, 0) or 0
        
        # Apply stock visibility policy
        if conn.stock_visibility == "exact":
            stock_display = raw_stock
        elif conn.stock_visibility == "band":
            if raw_stock > 10:
                stock_display = "In Stock"
            elif raw_stock > 0:
                stock_display = "Low Stock"
            else:
                stock_display = "Out of Stock"
        else:
            stock_display = None
            
        # `barcode` is the primary/display code; `barcodes` carries every active
        # packaging-revision code (a product accumulates many over its life).
        alt_codes = barcodes_by_product.get(p.id, [])

        catalog.append({
            "product_id": p.id,
            "name": p.name,
            "description": p.description,
            "sku": p.sku,
            "barcode": p.barcode,
            "barcodes": sorted(set(alt_codes + ([p.barcode] if p.barcode else []))),
            "hsn_sac": p.hsn_sac,
            "unit": p.unit or "Nos",
            "original_selling_price": p.selling_price,
            "selling_price": custom_price,
            "discount_pct": conn.discount_pct,
            "mrp": p.mrp,
            "cgst_rate": p.cgst_rate or 0.0,
            "sgst_rate": p.sgst_rate or 0.0,
            "igst_rate": p.igst_rate or 0.0,
            "stock": stock_display,
            "category": p.category,
            "brand": p.brand
        })
        
    return catalog

def create_order(
    db: Session,
    buyer_business_id: int,
    seller_business_id: int,
    items: List[Dict[str, Any]],
    notes: str = None
) -> B2BOrder:
    """
    Create a new B2BOrder and calculate taxes / totals.
    """
    conn = db.query(B2BConnection).filter(
        B2BConnection.seller_business_id == seller_business_id,
        B2BConnection.buyer_business_id == buyer_business_id,
        B2BConnection.status == "accepted"
    ).first()
    
    if not conn:
        raise PermissionError("No active connection with this supplier")
        
    if not items:
        raise ValueError("Order must contain at least one item")
        
    order_num = _next_order_number(db)


    # Calculate tax totals
    subtotal = 0.0
    cgst_total = 0.0
    sgst_total = 0.0
    igst_total = 0.0
    
    order_items = []
    for item in items:
        prod_id = item["product_id"]
        qty = float(item["quantity"])
        if qty <= 0:
            raise ValueError("Quantity must be greater than zero")
            
        p = db.query(Product).filter(
            Product.id == prod_id,
            Product.business_id == seller_business_id,
            Product.is_active == True
        ).first()
        
        if not p:
            raise ValueError(f"Product ID {prod_id} not found in supplier catalogue")
            
        # Resolve base price based on price tier
        base_price = p.selling_price
        if conn.price_tier == "wholesale":
            base_price = p.wholesale_price if (p.wholesale_price and p.wholesale_price > 0.0) else p.selling_price
        elif conn.price_tier == "distributor":
            base_price = p.distributor_price if (p.distributor_price and p.distributor_price > 0.0) else (p.wholesale_price if (p.wholesale_price and p.wholesale_price > 0.0) else p.selling_price)

        # Apply connection discount policy
        discount_factor = 1.0 - (conn.discount_pct / 100.0)
        unit_price = base_price * discount_factor
        
        line_total = unit_price * qty
        subtotal += line_total
        
        # Calculate line GST (simple split)
        cgst_rate = p.cgst_rate or 0.0
        sgst_rate = p.sgst_rate or 0.0
        igst_rate = p.igst_rate or 0.0
        
        cgst_amount = line_total * (cgst_rate / 100.0)
        sgst_amount = line_total * (sgst_rate / 100.0)
        igst_amount = line_total * (igst_rate / 100.0)
        
        cgst_total += cgst_amount
        sgst_total += sgst_amount
        igst_total += igst_amount
        
        line_item = B2BOrderLineItem(
            product_id=p.id,
            product_name=p.name,
            hsn_sac=p.hsn_sac,
            unit=p.unit or "Nos",
            quantity=qty,
            unit_price=unit_price,
            cgst_rate=cgst_rate,
            sgst_rate=sgst_rate,
            igst_rate=igst_rate,
            line_total=line_total + cgst_amount + sgst_amount + igst_amount
        )
        order_items.append(line_item)
        
    total_amount = subtotal + cgst_total + sgst_total + igst_total
    
    order = B2BOrder(
        buyer_business_id=buyer_business_id,
        seller_business_id=seller_business_id,
        order_number=order_num,
        order_date=utc_now().strftime("%Y-%m-%d"),
        status="pending",
        subtotal=subtotal,
        cgst_total=cgst_total,
        sgst_total=sgst_total,
        igst_total=igst_total,
        total_amount=total_amount,
        notes=notes,
        line_items=order_items
    )
    
    db.add(order)
    db.commit()
    db.refresh(order)
    logger.info(
        "[ORDER] created %s buyer=%s seller=%s tier=%s discount=%.1f%% lines=%d total=%.2f",
        order.order_number, buyer_business_id, seller_business_id,
        conn.price_tier, conn.discount_pct, len(order_items), total_amount,
    )
    return order

def transition_order_status(db: Session, business_id: int, order_id: int, new_status: str) -> B2BOrder:
    """
    Transition order state. Verifies user roles and state machine validity.
    """
    order = db.query(B2BOrder).filter(B2BOrder.id == order_id).with_for_update().first()
    if not order:
        raise ValueError("Order not found")
        
    if business_id not in [order.buyer_business_id, order.seller_business_id]:
        raise PermissionError("Not authorized to manage this order")
        
    valid_statuses = ["pending", "accepted", "packed", "dispatched", "completed", "cancelled", "rejected"]
    if new_status not in valid_statuses:
        raise ValueError("Invalid order status")
        
    # Buyer permissions
    if business_id == order.buyer_business_id:
        if new_status != "cancelled":
            raise PermissionError("Buyers can only cancel pending orders")
        if order.status not in ["pending", "accepted"]:
            raise ValueError("Cannot cancel order after it is packed or shipped")
            
    # Seller permissions
    if business_id == order.seller_business_id:
        if new_status == "cancelled":
            raise PermissionError("Sellers reject orders; buyers cancel them")
            
    order.status = new_status
    order.updated_at = utc_now()

    # Complete all financial effects before the order becomes durable as
    # completed. A partial bilateral posting is worse than a retriable failure.
    if new_status == "completed":
        with db.begin_nested():
            sync_completed_order(db, order)

    db.commit()
    db.refresh(order)

    return order


def b2b_purchase_invoice_uid(order: B2BOrder) -> str:
    """Return the stable cross-database identity of a B2B purchase bill.

    Local and cloud integer IDs differ.  A deterministic UID is the only safe
    key for retrying or reconciling this buyer document across databases.
    """
    identity = str(order.uid or f"order-number:{order.order_number}")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bizassist:b2b-purchase:{identity}"))


def _buyer_product_for_line(db: Session, *, order: B2BOrder, line) -> Product:
    """Resolve one buyer product for both its stock receipt and purchase bill."""
    product = db.query(Product).filter(
        Product.business_id == order.buyer_business_id,
        Product.name == line.product_name,
    ).first()
    if product is None:
        product = Product(
            business_id=order.buyer_business_id,
            name=line.product_name,
            hsn_sac=line.hsn_sac,
            unit=line.unit or "Nos",
            cost_price=float(line.unit_price or 0.0),
            selling_price=float(line.unit_price or 0.0),
            cgst_rate=float(line.cgst_rate or 0.0),
            sgst_rate=float(line.sgst_rate or 0.0),
            igst_rate=float(line.igst_rate or 0.0),
            track_inventory=True,
            is_active=True,
        )
        db.add(product)
        db.flush()
    else:
        # The completed supplier bill is the buyer's actual cost. Selling price
        # remains buyer-controlled.
        product.cost_price = float(line.unit_price or 0.0)
    return product


def _buyer_vendor_for_order(db: Session, *, order: B2BOrder, seller: User) -> Vendor:
    """Find/create the buyer-owned vendor row for this connected seller."""
    vendor = None
    if seller.gstin:
        vendor = db.query(Vendor).filter(
            Vendor.business_id == order.buyer_business_id,
            Vendor.gstin == seller.gstin,
        ).first()
    if vendor is None and not seller.gstin:
        vendor = db.query(Vendor).filter(
            Vendor.business_id == order.buyer_business_id,
            Vendor.name == seller.business_name,
        ).first()
    if vendor is None:
        vendor = Vendor(
            business_id=order.buyer_business_id,
            name=seller.business_name,
            gstin=seller.gstin,
            phone=seller.phone,
            email=seller.email,
            address=seller.address,
            state_code=seller.state_code,
            pan=seller.pan,
            is_active=True,
        )
        db.add(vendor)
        db.flush()
    return vendor


def _seller_customer_for_order(db: Session, *, order: B2BOrder, buyer: User) -> Customer:
    """Find/create the seller-owned customer row for this connected buyer.

    The exact mirror of :func:`_buyer_vendor_for_order`. The buyer side has
    always linked its purchase bill to a Vendor; the seller side recorded only
    ``customer=<business name>`` with a NULL ``customer_id``, so every B2B sale
    landed in "Other Invoices" and never reached the buyer's ledger. A B2B
    counterparty is a customer to the seller exactly as it is a vendor to the
    buyer — both halves now say so.
    """
    customer = None
    if buyer.gstin:
        customer = db.query(Customer).filter(
            Customer.business_id == order.seller_business_id,
            Customer.gstin == buyer.gstin,
        ).first()
    if customer is None and not buyer.gstin:
        customer = db.query(Customer).filter(
            Customer.business_id == order.seller_business_id,
            Customer.name == buyer.business_name,
        ).first()
    if customer is None:
        customer = Customer(
            business_id=order.seller_business_id,
            name=buyer.business_name,
            gstin=buyer.gstin,
            phone=buyer.phone,
            email=buyer.email,
            address=buyer.address,
            state_code=buyer.state_code,
            pan=buyer.pan,
            is_active=True,
        )
        db.add(customer)
        db.flush()
    return customer


def _ensure_buyer_purchase_invoice(db: Session, *, order: B2BOrder, buyer: User,
                                   seller: User, sale_invoice: Invoice) -> PurchaseInvoice:
    """Create the buyer's bill/payable, deliberately without a second stock move."""
    purchase_uid = b2b_purchase_invoice_uid(order)
    purchase = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.business_id == order.buyer_business_id,
        PurchaseInvoice.uid == purchase_uid,
    ).first()
    if purchase is not None:
        # Never silently change an existing financial document if its identity
        # was somehow attached to a different amount.
        if (purchase.invoice_number != f"B2B-{order.order_number}" or
                abs(float(purchase.total_amount or 0.0) - float(sale_invoice.total_amount or 0.0)) > 0.01 or
                len(purchase.line_items) != len(sale_invoice.line_items)):
            raise ValueError("Existing B2B purchase bill does not match the completed order")
        from core.accounting import posting
        posting.post_purchase(db, purchase)
        return purchase

    vendor = _buyer_vendor_for_order(db, order=order, seller=seller)
    purchase = PurchaseInvoice(
        business_id=order.buyer_business_id,
        uid=purchase_uid,
        supplier_id=vendor.id,
        supplier_name=vendor.name,
        invoice_number=f"B2B-{order.order_number}",
        invoice_date=sale_invoice.invoice_date,
        due_date=sale_invoice.due_date,
        status="Pending",
        notes=f"Automatically generated from completed B2B order {order.order_number}",
        gstin_buyer=buyer.gstin,
        place_of_supply=sale_invoice.place_of_supply,
        invoice_type="B2B",
        subtotal=float(sale_invoice.subtotal or 0.0),
        cgst_total=float(sale_invoice.cgst_total or 0.0),
        sgst_total=float(sale_invoice.sgst_total or 0.0),
        igst_total=float(sale_invoice.igst_total or 0.0),
        cess_total=float(sale_invoice.cess_total or 0.0),
        total_amount=float(sale_invoice.total_amount or 0.0),
        reverse_charge=bool(sale_invoice.reverse_charge),
        is_tax_inclusive=bool(sale_invoice.is_tax_inclusive),
        discount_total=float(sale_invoice.discount_total or 0.0),
        round_off=float(sale_invoice.round_off or 0.0),
    )
    db.add(purchase)
    db.flush()

    # Copy the final sale invoice values: that is the source of truth after
    # GST destination rules, rounding and discount allocation are applied.
    for index, line in enumerate(sale_invoice.line_items):
        buyer_product = _buyer_product_for_line(db, order=order, line=line)
        db.add(PurchaseInvoiceLineItem(
            uid=str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"bizassist:b2b-purchase-line:{purchase_uid}:{index}",
            )),
            purchase_invoice_id=purchase.id,
            product_id=buyer_product.id,
            product_name=buyer_product.name,
            hsn_sac=line.hsn_sac,
            unit=line.unit or buyer_product.unit or "Nos",
            quantity=float(line.quantity or 0.0),
            conversion_factor=1.0,
            unit_price=float(line.unit_price or 0.0),
            cgst_rate=float(line.cgst_rate or 0.0),
            sgst_rate=float(line.sgst_rate or 0.0),
            igst_rate=float(line.igst_rate or 0.0),
            taxable_value=float(line.taxable_value or 0.0),
            cgst_amount=float(line.cgst_amount or 0.0),
            sgst_amount=float(line.sgst_amount or 0.0),
            igst_amount=float(line.igst_amount or 0.0),
            line_total=float(line.line_total or 0.0),
            confidence_score=1.0,
            is_matched=True,
        ))

    from core.accounting import posting
    posting.post_purchase(db, purchase)
    return purchase


def _ensure_buyer_stock_in(db: Session, order: B2BOrder, seller: User):
    from core.stock import ledger as SL
    from core.models import StockLedger

    line_items = list(order.line_items or [])
    already = db.query(StockLedger).filter(
        StockLedger.business_id == order.buyer_business_id,
        StockLedger.reference_type == "b2b_order",
        StockLedger.reference_id == order.id,
    ).first()
    if not already:
        for li in line_items:
            bp = _buyer_product_for_line(db, order=order, line=li)
            SL.record_movement(
                db,
                business_id=order.buyer_business_id,
                movement_type=SL.PURCHASE,
                qty_delta=float(li.quantity or 0),
                product_id=bp.id,
                product_name=bp.name,
                reference_type="b2b_order",
                reference_id=order.id,
                note=f"B2B purchase from {seller.business_name or seller.username}",
            )


def reconcile_buyer_purchase_bill(db: Session, order: B2BOrder, receive_stock: bool = False) -> PurchaseInvoice:
    """Create a missing buyer Purchase Bill for a legacy completed B2B order."""
    if order.status != "completed":
        raise ValueError("Only completed B2B orders can have a purchase bill")
    if not order.seller_invoice_id:
        raise ValueError("The supplier sale invoice is missing; this order needs financial reconciliation")

    buyer = db.query(User).filter(User.id == order.buyer_business_id).first()
    seller = db.query(User).filter(User.id == order.seller_business_id).first()
    sale_invoice = db.query(Invoice).filter(
        Invoice.id == order.seller_invoice_id,
        Invoice.business_id == order.seller_business_id,
    ).first()
    if not buyer or not seller or not sale_invoice:
        raise ValueError("The completed order has an invalid business or supplier invoice link")
    purchase_uid = b2b_purchase_invoice_uid(order)
    existing_purchase = db.query(PurchaseInvoice).filter(
        PurchaseInvoice.business_id == order.buyer_business_id,
        PurchaseInvoice.uid == purchase_uid,
    ).first()

    purchase = _ensure_buyer_purchase_invoice(
        db, order=order, buyer=buyer, seller=seller, sale_invoice=sale_invoice,
    )
    if receive_stock or (existing_purchase is not None):
        _ensure_buyer_stock_in(db, order=order, seller=seller)
    return purchase


def sync_completed_order(db: Session, order: B2BOrder):
    """
    Post a completed B2B order to both businesses, EXACTLY ONCE:
      • seller — a sale invoice (deducts the seller's stock via the ledger),
      • buyer  — an auto stock-in (find/create the buyer's product + a PURCHASE
                 ledger movement that adds the goods to the buyer's inventory).

    Idempotency: the seller invoice number is deterministic (`B2B-<order_no>`, so
    `create_sale_invoice` is idempotent on it), the buyer stock-in is guarded on
    an existing `b2b_order` ledger reference, and `order.seller_invoice_id` short-
    circuits the whole thing once done. Returns the seller Invoice (or None).
    """
    # Lazy imports avoid any import-time cycle with the billing/stock commands.
    from core.billing import commands as billing
    from core.stock import ledger as SL
    from core.models import StockLedger

    line_items = list(order.line_items or [])
    if not line_items:
        raise ValueError("Cannot complete a B2B order without line items")

    buyer = db.query(User).filter(User.id == order.buyer_business_id).first()
    seller = db.query(User).filter(User.id == order.seller_business_id).first()
    if not buyer or not seller:
        raise ValueError("B2B order references a missing buyer or seller")

    # 1) Seller sale invoice — deterministic number ⇒ idempotent; deducts seller stock.
    lines = [{
        "product_id":   li.product_id,
        "product_name": li.product_name,
        "quantity":     li.quantity,
        "unit_price":   li.unit_price,
        "cgst_rate":    li.cgst_rate,
        "sgst_rate":    li.sgst_rate,
        "igst_rate":    li.igst_rate,
        "hsn_sac":      li.hsn_sac,
        "unit":         li.unit,
    } for li in line_items]

    if order.seller_invoice_id:
        inv = db.query(Invoice).filter(
            Invoice.id == order.seller_invoice_id,
            Invoice.business_id == order.seller_business_id,
        ).first()
        if inv is None:
            raise ValueError("B2B order points to a supplier invoice outside the seller business")
    else:
        seller_customer = _seller_customer_for_order(db, order=order, buyer=buyer)
        inv = billing.create_sale_invoice(
            db,
            business_id=order.seller_business_id,
            customer=buyer.business_name,
            customer_id=seller_customer.id,
            invoice_no=f"B2B-{order.order_number}",
            invoice_type="B2B",
            place_of_supply=buyer.state_code or None,
            lines=lines,
            commit=False,
        )

    # 2) Buyer auto stock-in — idempotent on (buyer, b2b_order, order.id).
    already = db.query(StockLedger).filter(
        StockLedger.business_id == order.buyer_business_id,
        StockLedger.reference_type == "b2b_order",
        StockLedger.reference_id == order.id,
    ).first()
    if not already:
        for li in line_items:
            bp = _buyer_product_for_line(db, order=order, line=li)
            SL.record_movement(
                db,
                business_id=order.buyer_business_id,
                movement_type=SL.PURCHASE,
                qty_delta=float(li.quantity or 0),
                product_id=bp.id,
                product_name=bp.name,
                reference_type="b2b_order",
                reference_id=order.id,
                note=f"Auto stock-in from B2B order {order.order_number}"
                     f" ({seller.business_name if seller else 'supplier'})",
            )

    # 3) Link the order to the seller invoice (exactly-once guard) + commit.
    _ensure_buyer_purchase_invoice(
        db, order=order, buyer=buyer, seller=seller, sale_invoice=inv,
    )
    order.seller_invoice_id = inv.id
    logger.info("[ORDER] synced order %s → seller invoice %s + buyer stock-in (buyer=%s, seller=%s)",
                order.order_number, inv.id, order.buyer_business_id, order.seller_business_id)
    return inv
