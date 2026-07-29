"""
core/api/orders.py
==================
FastAPI routes for B2B Ordering and Supplier Catalogue browsing.
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database.db import get_db
from database.models import PurchaseInvoice, User
from core.models import B2BOrder, B2BOrderLineItem, StockLedger
from services.auth import get_active_user, restrict_cashier
from services.realtime import realtime_manager
from core.order import service as order_service

router = APIRouter(tags=["orders"])
logger = logging.getLogger("bizassist.core.api.orders")

# ── Schemas ──────────────────────────────────────────────────────────────────

class OrderItemInput(BaseModel):
    product_id: int
    quantity: float

class OrderRequest(BaseModel):
    seller_bizid: str
    items: List[OrderItemInput]
    notes: Optional[str] = None

class StatusRequest(BaseModel):
    status: str

# ── Serializers ──────────────────────────────────────────────────────────────

def _line_out(li: B2BOrderLineItem) -> dict:
    return {
        "id": li.id,
        "product_id": li.product_id,
        "product_name": li.product_name,
        "hsn_sac": li.hsn_sac,
        "unit": li.unit,
        "quantity": li.quantity,
        "unit_price": li.unit_price,
        "cgst_rate": li.cgst_rate,
        "sgst_rate": li.sgst_rate,
        "igst_rate": li.igst_rate,
        "line_total": li.line_total
    }

def _business_map(db: Session, orders) -> dict:
    """One query resolving every buyer/seller referenced by ``orders``.

    Review finding F-5: ``_order_out`` used to issue two ``User`` lookups per
    order, so a 300-order history cost 600 extra round-trips per page load.
    """
    ids = set()
    for o in orders:
        ids.add(o.buyer_business_id)
        ids.add(o.seller_business_id)
    ids.discard(None)
    if not ids:
        return {}
    rows = db.query(User.id, User.business_name, User.public_id).filter(User.id.in_(ids)).all()
    return {r.id: r for r in rows}


def _purchase_bill_map(db: Session, orders) -> dict:
    """Batch-resolve buyer purchase bills by cross-database-safe document UID."""
    keys = {
        (order.buyer_business_id, order_service.b2b_purchase_invoice_uid(order))
        for order in orders
        if order.buyer_business_id
    }
    if not keys:
        return {}
    buyer_ids = {business_id for business_id, _ in keys}
    uids = {uid for _, uid in keys}
    rows = db.query(
        PurchaseInvoice.business_id,
        PurchaseInvoice.uid,
        PurchaseInvoice.id,
        PurchaseInvoice.invoice_number,
    ).filter(
        PurchaseInvoice.business_id.in_(buyer_ids),
        PurchaseInvoice.uid.in_(uids),
    ).all()
    return {(row.business_id, row.uid): row for row in rows}


def _stock_receipt_map(db: Session, orders) -> set:
    """Return buyer/order pairs with a durable B2B stock receipt.

    A seller invoice proves the supplier document exists; it does not prove that
    this buyer's stock receipt was recorded. Keep those facts separate so the UI
    cannot claim stock was received merely because an order was completed.
    """
    pairs = {
        (order.buyer_business_id, order.id)
        for order in orders
        if order.buyer_business_id and order.id is not None
    }
    if not pairs:
        return set()
    buyer_ids = {buyer_id for buyer_id, _ in pairs}
    order_ids = {order_id for _, order_id in pairs}
    rows = db.query(StockLedger.business_id, StockLedger.reference_id).filter(
        StockLedger.business_id.in_(buyer_ids),
        StockLedger.reference_type == "b2b_order",
        StockLedger.reference_id.in_(order_ids),
    ).all()
    return {(row.business_id, row.reference_id) for row in rows}


def _order_out(order: B2BOrder, db: Session, businesses: dict = None,
               purchase_bills: dict = None, stock_receipts: set = None,
               viewer_business_id: int = None) -> dict:
    if businesses is None:
        businesses = _business_map(db, [order])
    buyer = businesses.get(order.buyer_business_id)
    seller = businesses.get(order.seller_business_id)

    out = {
        "id": order.id,
        "order_number": order.order_number,
        "buyer_business_id": order.buyer_business_id,
        "buyer_name": buyer.business_name if buyer else "Unknown Buyer",
        "buyer_bizid": buyer.public_id if buyer else "",
        "seller_business_id": order.seller_business_id,
        "seller_name": seller.business_name if seller else "Unknown Supplier",
        "seller_bizid": seller.public_id if seller else "",
        "order_date": order.order_date,
        "status": order.status,
        "subtotal": order.subtotal,
        "cgst_total": order.cgst_total,
        "sgst_total": order.sgst_total,
        "igst_total": order.igst_total,
        "total_amount": order.total_amount,
        "notes": order.notes,
        # The seller owns this database-local invoice ID. The buyer only needs
        # proof that the document was posted; returning the seller's integer ID
        # across the tenant boundary is both unnecessary and unsafe.
        "seller_invoice_id": (
            order.seller_invoice_id
            if viewer_business_id == order.seller_business_id else None
        ),
        "seller_invoice_posted": bool(order.seller_invoice_id),
        "items": [_line_out(li) for li in order.line_items],
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }
    # Do not expose the buyer's private database-local document ID to the seller.
    # The purchase document is returned only to its owning buyer and is resolved
    # from a durable UID rather than stored as a cross-database raw foreign key.
    if viewer_business_id == order.buyer_business_id:
        if purchase_bills is None:
            purchase_bills = _purchase_bill_map(db, [order])
        purchase = purchase_bills.get((
            order.buyer_business_id,
            order_service.b2b_purchase_invoice_uid(order),
        ))
        out["buyer_purchase_invoice_id"] = purchase.id if purchase else None
        out["buyer_purchase_invoice_number"] = purchase.invoice_number if purchase else None
        if stock_receipts is None:
            stock_receipts = _stock_receipt_map(db, [order])
        out["buyer_stock_received"] = (
            order.buyer_business_id,
            order.id,
        ) in stock_receipts
    return out

# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/orders")
async def place_order(req: OrderRequest, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Place a B2B order (Buyer flow). Triggers real-time alert to Seller."""
    seller = db.query(User).filter(User.public_id == req.seller_bizid).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Supplier BizID not found")
        
    try:
        items_dict = [it.model_dump() for it in req.items]
        order = order_service.create_order(
            db,
            buyer_business_id=current_user["id"],
            seller_business_id=seller.id,
            items=items_dict,
            notes=req.notes
        )
        
        # Real-time SSE alert to Seller
        await realtime_manager.broadcast(seller.id, {
            "type": "order.created",
            "order_id": order.id,
            "order_number": order.order_number,
            "buyer_name": current_user["business_name"],
            "total_amount": order.total_amount
        })
        
        # Broadcast sync trigger to self's active sessions
        await realtime_manager.broadcast(current_user["id"], {"type": "sync.trigger", "entity": "order"})
        
        return _order_out(order, db, viewer_business_id=current_user["id"])
    except ValueError as ve:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except PermissionError as pe:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        db.rollback()
        logger.error(f"Order placement failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not place order")

@router.get("/orders")
def list_orders(
    role: str = Query(..., description="buyer | seller"),
    status: Optional[str] = Query(None, description="Filter by order status"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(restrict_cashier),
    db: Session = Depends(get_db),
):
    """List incoming (role=seller) or outgoing (role=buyer) orders.

    Returns a bare JSON array for backward compatibility with existing clients;
    pagination metadata travels in the ``X-Total-Count`` / ``X-Limit`` /
    ``X-Offset`` response headers so no caller has to change to keep working.
    """
    bid = current_user["id"]
    if role == "buyer":
        q = db.query(B2BOrder).filter(B2BOrder.buyer_business_id == bid)
    elif role == "seller":
        q = db.query(B2BOrder).filter(B2BOrder.seller_business_id == bid)
    else:
        raise HTTPException(status_code=400, detail="Invalid role. Must be 'buyer' or 'seller'.")

    if status:
        q = q.filter(B2BOrder.status == status)

    total = q.count()
    orders = q.order_by(B2BOrder.id.desc()).offset(offset).limit(limit).all()
    businesses = _business_map(db, orders)
    purchase_bills = _purchase_bill_map(db, orders)
    stock_receipts = _stock_receipt_map(db, orders)

    return JSONResponse(
        content=[_order_out(o, db, businesses, purchase_bills, stock_receipts, bid) for o in orders],
        headers={
            "X-Total-Count": str(total),
            "X-Limit": str(limit),
            "X-Offset": str(offset),
            "Access-Control-Expose-Headers": "X-Total-Count, X-Limit, X-Offset",
        },
    )

@router.get("/orders/{id}")
def get_order_details(id: int, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Get detailed view of a single B2B order."""
    order = db.query(B2BOrder).filter(B2BOrder.id == id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if current_user["id"] not in [order.buyer_business_id, order.seller_business_id]:
        raise HTTPException(status_code=403, detail="Not authorized to view this order")
        
    return _order_out(order, db, viewer_business_id=current_user["id"])

@router.post("/orders/{id}/status")
async def update_order_status(id: int, req: StatusRequest, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Accept, Reject, Cancel, or Ship B2B order. Triggers real-time status update."""
    try:
        order = order_service.transition_order_status(
            db,
            business_id=current_user["id"],
            order_id=id,
            new_status=req.status
        )
        
        # Broadcast SSE status update to the other party
        target_notify_id = order.buyer_business_id if current_user["id"] == order.seller_business_id else order.seller_business_id
        await realtime_manager.broadcast(target_notify_id, {
            "type": "order.status",
            "order_id": order.id,
            "order_number": order.order_number,
            "status": order.status
        })

        # Phase 4: completing the order posted it both sides — tell the buyer
        # their stock-in landed (and which seller invoice it came from).
        if order.status == "completed" and order.seller_invoice_id:
            await realtime_manager.broadcast(order.buyer_business_id, {
                "type": "order.invoiced",
                "order_id": order.id,
                "order_number": order.order_number,
                "seller_invoice_posted": True,
            })

        # Broadcast sync trigger to self's active sessions
        await realtime_manager.broadcast(current_user["id"], {"type": "sync.trigger", "entity": "order"})

        return _order_out(order, db, viewer_business_id=current_user["id"])
    except ValueError as ve:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except PermissionError as pe:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        db.rollback()
        logger.error(f"Order status transition failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not update order status")


@router.post("/orders/{id}/purchase-bill/reconcile")
async def reconcile_purchase_bill(id: int, current_user: dict = Depends(restrict_cashier),
                                  db: Session = Depends(get_db)):
    """Repair a missing buyer bill for a legacy completed B2B order.

    This endpoint is intentionally buyer-owner only. It never receives stock,
    including when a historical order lacks a linked stock receipt, and cannot
    create a document for another business: both the order and every generated
    record are scoped to the authenticated buyer business.
    """
    order = db.query(B2BOrder).filter(B2BOrder.id == id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if current_user["id"] != order.buyer_business_id:
        raise HTTPException(status_code=403, detail="Only the buyer can reconcile this purchase bill")

    try:
        order_service.reconcile_buyer_purchase_bill(db, order)
        db.commit()
        db.refresh(order)
        await realtime_manager.broadcast(
            current_user["id"], {"type": "sync.trigger", "entity": "purchase"},
        )
        return _order_out(order, db, viewer_business_id=current_user["id"])
    except ValueError as ve:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        db.rollback()
        logger.error("B2B purchase bill reconciliation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not reconcile the B2B purchase bill")
