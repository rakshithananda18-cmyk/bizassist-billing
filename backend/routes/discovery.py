"""
routes/discovery.py
====================
Local-backend discovery registry — lets cashier devices on the same LAN
auto-discover the owner's local backend IP without manual configuration.

Architecture:
  - When the local backend starts, it registers its LAN IP + port here.
  - Cashier devices (or any browser) query this endpoint to get the list of
    known local IPs for a given business, then probe them directly.
  - In-memory store: entries expire after 2 hours of no renewal.
  - No auth required for registration (local backend talks here on startup).
  - GET is public (no auth) so un-authed cashier apps can probe IPs before login.
  - Intentionally lightweight — no DB, no migrations, just a dict + timestamps.
"""
from __future__ import annotations
import logging
import time
from typing import Dict, List

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel

logger = logging.getLogger("bizassist.discovery")
router = APIRouter(tags=["discovery"])

# ── In-memory store ────────────────────────────────────────────────────────────
# { biz_id: [ {ip, port, registered_at, last_seen} ] }
_REGISTRY: Dict[str, List[dict]] = {}
_TTL_SECONDS = 2 * 60 * 60   # 2 hours


def _prune(biz_id: str) -> None:
    """Remove expired entries for a business."""
    now = time.time()
    entries = _REGISTRY.get(biz_id, [])
    _REGISTRY[biz_id] = [e for e in entries if now - e["last_seen"] < _TTL_SECONDS]


class DiscoverRegisterRequest(BaseModel):
    ip: str
    port: int = 8001
    biz_id: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/discover/register")
async def register_local_backend(req: DiscoverRegisterRequest, request: Request):
    """
    Called by the local backend on startup (and periodically) to announce its
    LAN IP + port.  No auth — the caller is always the local backend itself
    (loopback or LAN, never an untrusted internet client).

    Also accepts the IP from the request's origin as a fallback if the caller
    sends '0.0.0.0' or omits the IP.
    """
    ip = req.ip
    # If the caller sent a non-routable placeholder, fall back to the connection IP.
    if not ip or ip in ("0.0.0.0", "127.0.0.1", "localhost"):
        # request.client may be None in some test setups
        ip = (request.client.host if request.client else None) or req.ip

    biz_id = str(req.biz_id)
    _prune(biz_id)

    entries = _REGISTRY.setdefault(biz_id, [])
    now = time.time()

    # Update existing entry for this ip:port or add new one
    for entry in entries:
        if entry["ip"] == ip and entry["port"] == req.port:
            entry["last_seen"] = now
            logger.info("[DISCOVER] Renewed registration %s:%d for biz %s", ip, req.port, biz_id)
            return {"status": "renewed", "ip": ip, "port": req.port}

    entries.append({"ip": ip, "port": req.port, "registered_at": now, "last_seen": now})
    logger.info("[DISCOVER] Registered %s:%d for biz %s", ip, req.port, biz_id)
    return {"status": "registered", "ip": ip, "port": req.port}


@router.delete("/discover/register")
async def unregister_local_backend(req: DiscoverRegisterRequest):
    """Called by the local backend on clean shutdown to remove its entry."""
    biz_id = str(req.biz_id)
    entries = _REGISTRY.get(biz_id, [])
    before = len(entries)
    _REGISTRY[biz_id] = [e for e in entries if not (e["ip"] == req.ip and e["port"] == req.port)]
    removed = before - len(_REGISTRY[biz_id])
    logger.info("[DISCOVER] Unregistered %s:%d for biz %s (removed %d)", req.ip, req.port, biz_id, removed)
    return {"status": "ok", "removed": removed}


@router.get("/discover/{biz_id}")
async def get_local_backends(biz_id: str):
    """
    Returns all known local backend IPs for a given business.
    Cashier devices call this to find the owner's local backend on the same LAN.
    No auth — called before login when the device doesn't have a token yet.
    """
    _prune(biz_id)
    entries = _REGISTRY.get(str(biz_id), [])
    # Return sorted newest-first so the freshest entry is tried first
    sorted_entries = sorted(entries, key=lambda e: e["last_seen"], reverse=True)
    return {
        "biz_id": biz_id,
        "backends": [
            {
                "ip": e["ip"],
                "port": e["port"],
                "url": f"http://{e['ip']}:{e['port']}",
                "last_seen_ago_s": round(time.time() - e["last_seen"]),
            }
            for e in sorted_entries
        ]
    }
