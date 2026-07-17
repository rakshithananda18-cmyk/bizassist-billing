"""
core/order/service.py
=====================
Domain service logic for B2B Ordering and Catalog visibility.
"""
from services.dates import utc_now
import logging
import random
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from core.models import B2BConnection, B2BOrder, B2BOrderLineItem
from database.models import Product, Inventory, User

logger = logging.getLogger("bizassist.order")

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
        
        # Get stock level
        stock_row = db.query(Inventory).filter(
            Inventory.product_id == p.id,
            Inventory.business_id == seller_business_id
        ).first()
        raw_stock = stock_row.stock if stock_row else 0
        
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
            
        catalog.append({
            "product_id": p.id,
            "name": p.name,
            "description": p.description,
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
        
    # Generate unique order number (e.g. ORD-20260616-XXXX)
    date_str = utc_now().strftime("%Y%m%d")
    chars = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    while True:
        suffix = "".join(random.choice(chars) for _ in range(4))
        order_num = f"ORD-{date_str}-{suffix}"
        exists = db.query(B2BOrder).filter(B2BOrder.order_number == order_num).first()
        if not exists:
            break
            
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
    order = db.query(B2BOrder).filter(B2BOrder.id == order_id).first()
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
    db.commit()
    db.refresh(order)

    # Phase 4 sync: completing an order posts it to BOTH sides (seller sale
    # invoice + buyer auto stock-in), exactly-once.
    if new_status == "completed":
        sync_completed_order(db, order)
        db.refresh(order)

    return order


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
    if order.seller_invoice_id:
        return None  # already synced

    # Lazy imports avoid any import-time cycle with the billing/stock commands.
    from core.billing import commands as billing
    from core.stock import ledger as SL
    from core.models import StockLedger

    line_items = list(order.line_items or [])
    if not line_items:
        return None

    buyer = db.query(User).filter(User.id == order.buyer_business_id).first()
    seller = db.query(User).filter(User.id == order.seller_business_id).first()

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

    inv = billing.create_sale_invoice(
        db,
        business_id=order.seller_business_id,
        customer=(buyer.business_name if buyer else None),
        invoice_no=f"B2B-{order.order_number}",
        invoice_type="B2B",
        place_of_supply=(buyer.state_code if buyer and buyer.state_code else None),
        lines=lines,
    )

    # 2) Buyer auto stock-in — idempotent on (buyer, b2b_order, order.id).
    already = db.query(StockLedger).filter(
        StockLedger.business_id == order.buyer_business_id,
        StockLedger.reference_type == "b2b_order",
        StockLedger.reference_id == order.id,
    ).first()
    if not already:
        for li in line_items:
            bp = db.query(Product).filter(
                Product.business_id == order.buyer_business_id,
                Product.name == li.product_name,
            ).first()
            if not bp:
                bp = Product(
                    business_id=order.buyer_business_id,
                    name=li.product_name,
                    hsn_sac=li.hsn_sac,
                    unit=li.unit or "Nos",
                    cost_price=li.unit_price,
                    selling_price=li.unit_price,
                    cgst_rate=li.cgst_rate,
                    sgst_rate=li.sgst_rate,
                    igst_rate=li.igst_rate,
                    track_inventory=True,
                    is_active=True,
                )
                db.add(bp)
                db.flush()
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
    order.seller_invoice_id = inv.id
    db.commit()
    db.refresh(order)
    logger.info("[ORDER] synced order %s → seller invoice %s + buyer stock-in (buyer=%s, seller=%s)",
                order.order_number, inv.id, order.buyer_business_id, order.seller_business_id)
    return inv
