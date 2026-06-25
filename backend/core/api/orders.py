"""
core/api/orders.py
==================
FastAPI routes for B2B Ordering and Supplier Catalogue browsing.
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database.db import get_db
from database.models import User
from core.models import B2BOrder, B2BOrderLineItem
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

def _order_out(order: B2BOrder, db: Session) -> dict:
    buyer = db.query(User).filter(User.id == order.buyer_business_id).first()
    seller = db.query(User).filter(User.id == order.seller_business_id).first()
    
    return {
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
        "seller_invoice_id": order.seller_invoice_id,
        "items": [_line_out(li) for li in order.line_items],
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }

# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/catalog/{seller_bizid}")
def get_catalog(seller_bizid: str, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Buyer browses connected supplier's catalog (scoped by connection policies)."""
    seller = db.query(User).filter(User.public_id == seller_bizid).first()
    if not seller:
        raise HTTPException(status_code=404, detail="Supplier BizID not found")
        
    try:
        catalog = order_service.get_supplier_catalog(
            db,
            buyer_business_id=current_user["id"],
            seller_business_id=seller.id
        )
        return {"items": catalog}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        logger.error(f"Catalog retrieval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not retrieve catalogue")

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
        
        return _order_out(order, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        logger.error(f"Order placement failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not place order")

@router.get("/orders")
def list_orders(role: str = Query(..., description="buyer | seller"), current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """List incoming or outgoing orders for the logged-in user."""
    bid = current_user["id"]
    if role == "buyer":
        orders = db.query(B2BOrder).filter(B2BOrder.buyer_business_id == bid).order_by(B2BOrder.id.desc()).all()
    elif role == "seller":
        orders = db.query(B2BOrder).filter(B2BOrder.seller_business_id == bid).order_by(B2BOrder.id.desc()).all()
    else:
        raise HTTPException(status_code=400, detail="Invalid role. Must be 'buyer' or 'seller'.")
        
    return [_order_out(o, db) for o in orders]

@router.get("/orders/{id}")
def get_order_details(id: int, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Get detailed view of a single B2B order."""
    order = db.query(B2BOrder).filter(B2BOrder.id == id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if current_user["id"] not in [order.buyer_business_id, order.seller_business_id]:
        raise HTTPException(status_code=403, detail="Not authorized to view this order")
        
    return _order_out(order, db)

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
                "seller_invoice_id": order.seller_invoice_id
            })

        # Broadcast sync trigger to self's active sessions
        await realtime_manager.broadcast(current_user["id"], {"type": "sync.trigger", "entity": "order"})

        return _order_out(order, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        logger.error(f"Order status transition failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not update order status")
