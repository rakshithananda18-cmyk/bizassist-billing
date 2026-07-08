"""
core/api/realtime.py
====================
FastAPI routes for Server-Sent Events (SSE) and POS Real-time synchronization.
"""
import json
import asyncio
import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from database.db import get_db
from services.auth import get_active_user, restrict_cashier_or_ticket, get_active_user_or_ticket
from services.realtime import realtime_manager

router = APIRouter(tags=["realtime"])
logger = logging.getLogger("bizassist.core.api.realtime")


@router.post("/realtime/ticket")
def generate_sse_ticket(current_user: dict = Depends(get_active_user)):
    """
    Generate a short-lived single-use SSE ticket for authentication.
    """
    from services.auth import create_sse_ticket
    ticket = create_sse_ticket(current_user)
    return {"ticket": ticket, "expires_in": 30}


@router.get("/realtime/events")
async def sse_realtime_feed(request: Request, current_user: dict = Depends(get_active_user_or_ticket)):
    """
    Server-Sent Events stream for real-time notifications, scoped to the business.
    """
    bid = current_user.get("parent_business_id") or current_user.get("id")
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
                    if event.get("type") == "shutdown":
                        break
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
    bid = current_user.get("parent_business_id") or current_user.get("id")
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
    so the owner's Live Counters view can watch each till live."""
    bid = current_user.get("parent_business_id") or current_user.get("id")
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
            "network_mode": req.get("network_mode"),       # "local" | "cloud"
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
    bid = current_user.get("parent_business_id") or current_user.get("id")
    msg_type = req.get("type", "unknown")
    logger.info(f"[REALTIME] Broadcast message received for business {bid}, type: {msg_type}")
    await realtime_manager.broadcast(bid, req)
    return {"status": "broadcasted"}
