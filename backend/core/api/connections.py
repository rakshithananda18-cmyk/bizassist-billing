"""
core/api/connections.py
========================
FastAPI routes for BizIDs and B2B Connections.
"""
import json
import asyncio
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from database.db import get_db
from database.models import User
from core.models import B2BConnection, BusinessSettings
from services.auth import get_active_user, restrict_cashier, restrict_cashier_or_ticket, get_active_user_or_ticket
from services.realtime import realtime_manager
from core.connection import service as conn_service

router = APIRouter(tags=["connections"])
logger = logging.getLogger("bizassist.core.api.connections")

# ── Schemas ──────────────────────────────────────────────────────────────────


class PolicyRequest(BaseModel):
    price_tier: str = Field(..., description="standard | wholesale | distributor")
    discount_pct: float = Field(0.0, ge=0.0, le=100.0)
    credit_limit: float = Field(0.0, ge=0.0)
    stock_visibility: str = Field(..., description="exact | band | hidden")
    catalog_category: Optional[str] = None

class RedeemRequest(BaseModel):
    code: str

class ConnectRequest(BaseModel):
    bizid: str
    connect_as: str = Field(..., description="buyer | seller")

# ── Helper Serializers ────────────────────────────────────────────────────────

def _conn_out(conn: B2BConnection, db: Session) -> dict:
    seller = db.query(User).filter(User.id == conn.seller_business_id).first()
    buyer = db.query(User).filter(User.id == conn.buyer_business_id).first()
    
    return {
        "id": conn.id,
        "seller_business_id": conn.seller_business_id,
        "buyer_business_id": conn.buyer_business_id,
        "seller_name": seller.business_name if seller else "Unknown Seller",
        "seller_bizid": seller.public_id if seller else "",
        "buyer_name": buyer.business_name if buyer else "Unknown Buyer",
        "buyer_bizid": buyer.public_id if buyer else "",
        "price_tier": conn.price_tier,
        "discount_pct": conn.discount_pct,
        "credit_limit": conn.credit_limit,
        "outstanding_balance": conn.outstanding_balance,
        "stock_visibility": conn.stock_visibility,
        "catalog_category": conn.catalog_category,
        "status": conn.status,
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
    }

# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/bizid")
def get_my_bizid(current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Get the logged-in user's own public BizID."""
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"public_id": user.public_id}

@router.get("/bizid/{code}")
def lookup_bizid(code: str, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """
    Public lookup for a BizID. Returns ONLY safe public profile data.
    Leaks NO transactional data or cost margins.
    """
    target = db.query(User).filter(User.public_id == code).first()
    if not target:
        raise HTTPException(status_code=404, detail="BizID not found")

    # Find business type
    settings = db.query(BusinessSettings).filter(BusinessSettings.business_id == target.id).first()
    biz_type = settings.template_key if settings else "general"

    # Privacy gate: contact details (phone/email/address) are revealed only once an
    # ACCEPTED connection exists between the two businesses (either direction), or
    # when looking up one's own BizID. Discovery before connecting shows just the
    # public identity (name, type, state) so a BizID can't be used to scrape
    # contact lists of businesses you have no relationship with.
    me = current_user["id"]
    connected = me == target.id or (
        db.query(B2BConnection)
        .filter(
            B2BConnection.status == "accepted",
            ((B2BConnection.seller_business_id == target.id) & (B2BConnection.buyer_business_id == me))
            | ((B2BConnection.seller_business_id == me) & (B2BConnection.buyer_business_id == target.id)),
        )
        .first()
        is not None
    )

    out = {
        "public_id": target.public_id,
        "business_name": target.business_name,
        "business_type": biz_type,
        "state_code": target.state_code,
        "accepts_orders": True,
        "connected": connected,
    }
    if connected:
        out.update({"address": target.address, "phone": target.phone, "email": target.email})
    else:
        out.update({"address": None, "phone": None, "email": None})
    logger.info("[CONN] bizid lookup biz=%s target=%s connected=%s", me, target.id, connected)
    return out

@router.post("/connections/code")
def generate_join_code(current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Generate a single-use expiring connection code (Seller flow)."""
    try:
        code_obj = conn_service.create_connection_code(db, seller_business_id=current_user["id"])
        return {
            "code": code_obj.code,
            "expires_at": code_obj.expires_at.isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to generate connection code: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not generate connection code")

@router.post("/connections/redeem")
def redeem_join_code(req: RedeemRequest, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Redeem a connection code to link to a seller (Buyer flow)."""
    try:
        conn = conn_service.redeem_connection_code(db, buyer_business_id=current_user["id"], code=req.code)
        return _conn_out(conn, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to redeem connection code: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not redeem connection code")

@router.post("/connections/connect")
def connect_via_bizid(req: ConnectRequest, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Connect directly to a business using their BizID."""
    try:
        conn = conn_service.create_direct_connection(
            db,
            initiator_id=current_user["id"],
            target_bizid=req.bizid.strip().upper(),
            connect_as=req.connect_as
        )
        return _conn_out(conn, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to connect via BizID: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not establish connection")

@router.get("/connections")
def list_connections(current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """List connections where the user acts as either buyer or seller."""
    bid = current_user["id"]
    conns_as_seller = db.query(B2BConnection).filter(B2BConnection.seller_business_id == bid).all()
    conns_as_buyer = db.query(B2BConnection).filter(B2BConnection.buyer_business_id == bid).all()
    
    return {
        "as_seller": [_conn_out(c, db) for c in conns_as_seller],
        "as_buyer": [_conn_out(c, db) for c in conns_as_buyer]
    }

@router.post("/connections/{id}/policy")
def set_connection_policy(id: int, req: PolicyRequest, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Update connection pricing and visibility parameters (Seller flow)."""
    try:
        conn = conn_service.update_connection_policy(
            db,
            seller_business_id=current_user["id"],
            connection_id=id,
            price_tier=req.price_tier,
            discount_pct=req.discount_pct,
            credit_limit=req.credit_limit,
            stock_visibility=req.stock_visibility,
            catalog_category=req.catalog_category
        )
        return _conn_out(conn, db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        logger.error(f"Failed to set connection policy: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not update connection policy")

@router.post("/connections/{id}/revoke")
def revoke_partnership(id: int, current_user: dict = Depends(restrict_cashier), db: Session = Depends(get_db)):
    """Revoke partnership (either buyer or seller can trigger)."""
    try:
        conn = conn_service.revoke_connection(db, business_id=current_user["id"], connection_id=id)
        return _conn_out(conn, db)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to revoke partnership: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not revoke partnership")

@router.post("/realtime/ticket")
def generate_sse_ticket(current_user: dict = Depends(get_active_user)):
    """
    Generate a short-lived single-use SSE ticket for authentication.

    Any authenticated user (owner OR cashier) may open the realtime stream —
    cashiers need it to receive sync deltas and to power the owner's Live Counters
    view. (Previously this required owner-only `restrict_cashier`, which 403'd
    cashiers and tripped the SSE auto-disable breaker — `/realtime/events` already
    allows cashiers via `restrict_cashier_or_ticket`, so the ticket gate was the
    inconsistent one.)
    """
    from services.auth import create_sse_ticket
    ticket = create_sse_ticket(current_user)
    return {"ticket": ticket, "expires_in": 30}

@router.get("/realtime/events")
async def sse_realtime_feed(request: Request, current_user: dict = Depends(get_active_user_or_ticket)):
    """
    Server-Sent Events stream for real-time notifications, scoped to the business.

    Any authenticated user of the business (owner OR cashier), via token or a
    short-lived SSE ticket, may subscribe — cashiers need the stream to receive
    sync deltas and to power the owner's Live Counters view. (Was
    `restrict_cashier_or_ticket`, which authenticates via ticket/token but STILL
    403'd cashiers — the role block was wrong for realtime.)
    """
    bid = current_user["id"]
    q = realtime_manager.subscribe(bid)
    
    async def event_generator():
        try:
            # Yield initial retry hint to EventSource
            yield "retry: 5000\n\n"
            while True:
                if await request.is_disconnected():
                    logger.info(f"[REALTIME] Client disconnected for Business {bid}")
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Periodically yield keep-alive comment to prevent proxy timeouts
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            # Client disconnected
            pass
        finally:
            realtime_manager.unsubscribe(bid, q)
            
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

@router.post("/realtime/sync-cart")
async def pos_cart_sync(
    req: dict,
    current_user: dict = Depends(get_active_user)
):
    bid = current_user["id"]
    await realtime_manager.broadcast(
        bid,
        {
            "type": "pos.cart_sync",
            "client_id": req.get("client_id"),
            "user_id": req.get("user_id") or current_user.get("user_id") or current_user.get("id"),
            "tabs": req.get("tabs"),
            "active_tab_id": req.get("active_tab_id"),
            "timestamp": req.get("timestamp")
        }
    )
    return {"status": "broadcasted"}


@router.post("/realtime/presence")
async def pos_presence(
    req: dict,
    current_user: dict = Depends(get_active_user)
):
    """(Live Counters, plan §9.2 Stage 1) A POS session publishes a lightweight
    READ-ONLY snapshot of its activity — which counter, who, current cart total —
    so the owner's Live Counters view can watch each till live. This is NOT cart
    sync (no cart contents applied anywhere): just presence/metrics, broadcast to
    the business. Cashiers publish; the owner consumes."""
    bid = current_user["id"]
    await realtime_manager.broadcast(
        bid,
        {
            "type": "pos.presence",
            "client_id": req.get("client_id"),
            "counter": req.get("counter"),                 # e.g. "C1" / "OW"
            "username": current_user.get("username"),
            "role": current_user.get("role"),
            "user_id": current_user.get("user_id") or current_user.get("id"),
            "item_count": req.get("item_count"),
            "cart_total": req.get("cart_total"),
            "active_bill": req.get("active_bill"),         # current invoice no on screen
            "status": req.get("status", "active"),         # "active" | "idle" | "closed"
            "timestamp": req.get("timestamp"),
        }
    )
    return {"status": "broadcasted"}


@router.post("/realtime/broadcast")
async def broadcast_message(
    req: dict,
    current_user: dict = Depends(get_active_user)
):
    """Broadcast any generic realtime synchronization or handshake message to all active sessions of this business."""
    bid = current_user["id"]
    await realtime_manager.broadcast(bid, req)
    return {"status": "broadcasted"}



