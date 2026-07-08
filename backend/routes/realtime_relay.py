"""
routes/realtime_relay.py
========================
Cross-network SSE relay endpoint.

When the local backend sends a pos.* event (cart sync, presence, edit request),
it also POSTs the event here so cloud-connected clients (on different networks)
receive it in real time — bridging the local SSE hub with the cloud SSE hub.

Echo-loop prevention: events tagged relay_source='local' are NOT re-relayed
by cloud→local listeners, so we never create an infinite broadcast loop.

The local backend calls this using its stored cloud token (the same token the
sync worker uses).  Unauthenticated callers are rejected.
"""
from __future__ import annotations
import logging

from fastapi import APIRouter, Depends
from services.auth import get_active_user
from services.realtime import realtime_manager

logger = logging.getLogger("bizassist.realtime_relay")
router = APIRouter(tags=["realtime"])


@router.post("/realtime/relay")
async def relay_from_local(
    req: dict,
    current_user: dict = Depends(get_active_user),
):
    """
    Accepts a pos.* event from a local backend and fans it out to all
    cloud-connected SSE subscribers for the same business.

    The event MUST include relay_source='local' so cloud-side listeners can
    skip re-relaying it back to local (preventing echo loops).

    The local backend authenticates via its cloud-scoped token (same as
    the sync worker's cloud token — stored in /api/sync/cloud-token).
    """
    bid = current_user.get("parent_business_id") or current_user.get("id")
    event_type = req.get("type", "unknown")

    # Safety: ensure relay_source is always set so clients can filter echo loops
    relay_event = dict(req)
    relay_event["relay_source"] = "local"

    # Only relay pos.* events and sync.trigger — never relay relay events themselves
    allowed_prefixes = ("pos.", "sync.")
    if not any(event_type.startswith(p) for p in allowed_prefixes):
        logger.warning("[RELAY] Rejected relay for non-pos/sync event type: %s", event_type)
        return {"status": "ignored", "reason": "only pos.* and sync.* events are relayed"}

    logger.info("[RELAY] Relaying %s to cloud SSE for business %s", event_type, bid)
    await realtime_manager.broadcast(bid, relay_event)
    return {"status": "relayed", "type": event_type}
