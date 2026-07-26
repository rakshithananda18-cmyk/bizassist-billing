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

import ipaddress

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("bizassist.discovery")
router = APIRouter(tags=["discovery"])

# Max advertised backends per business. A real deployment has one local backend,
# occasionally two during a machine swap. The cap stops an attacker burying the
# genuine entry under decoys in the newest-first list the client probes. (S-2)
_MAX_ENTRIES_PER_BIZ = 8


def _is_private_address(value: str) -> bool:
    """True only for addresses reachable inside a LAN.

    The security property this endpoint rests on (S-2): a local backend always
    lives at an RFC1918 / loopback / link-local address, so anything routable on
    the public internet is never a legitimate registration — and refusing them
    means a remote attacker cannot advertise itself as somebody's local backend.

    Pure and unit-tested: this single predicate is what stands between a public
    BizID and a credential-harvesting redirect.
    """
    if not value:
        return False
    host = str(value).strip()
    if host.lower() in ("localhost",):
        return True
    # Tolerate a bracketed IPv6 literal.
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP literal at all (a hostname). We cannot verify where it
        # resolves, and it could resolve anywhere — refuse.
        return False
    # `is_global` is exactly the question being asked: "can a host on the public
    # internet receive traffic at this address?" Everything else — RFC1918,
    # loopback, link-local, CGNAT, and the RFC5737 documentation ranges — is
    # unroutable from outside, so an attacker cannot be reached there even if
    # they register it. Stated as the negation of `is_global` rather than a
    # hand-rolled list of private ranges so new reserved allocations are covered
    # without this predicate having to be revisited.
    return not addr.is_global

# ── In-memory store ────────────────────────────────────────────────────────────
# { biz_id: [ {ip, port, registered_at, last_seen} ] }
_REGISTRY: Dict[str, List[dict]] = {}
_TTL_SECONDS = 2 * 60 * 60   # 2 hours
TTL_SECONDS = _TTL_SECONDS   # Public alias for tests


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
    LAN IP + port. No auth — a local backend has no cloud session at boot.

    THREAT MODEL (review finding S-2)
    ---------------------------------
    This used to be documented as "the caller is always the local backend itself
    (loopback or LAN, never an untrusted internet client)". **That was not
    true.** `main_groq.py` mounts this router unconditionally, and the local
    backend's `_discovery_registration_loop` registers with the CLOUD every 30
    minutes — so on the cloud deployment this endpoint is internet-reachable.

    Combined with `GET /discover/{biz_id}` being public and BizID being a
    *deliberately public* identifier, the attack was:

        attacker POSTs {biz_id: <victim's public BizID>, ip: <attacker host>}
          → cashier device calls GET /discover/<biz_id> BEFORE login
          → results are sorted newest-first, so the attacker's entry is tried first
          → the cashier app sends the owner's credentials to the attacker

    i.e. credential harvesting off a public identifier — structurally the same
    defect as F-1, on a different surface.

    MITIGATION: only PRIVATE addresses may be registered. A local backend's LAN
    address is by definition RFC1918 / loopback / link-local, so rejecting public
    IPs costs nothing legitimate and removes the remote attacker entirely — an
    internet host cannot point a victim at itself using an address that is only
    routable inside the victim's own network. The number of entries per BizID is
    also capped so the list cannot be flooded.

    RESIDUAL RISK, stated plainly: a device ALREADY on the same LAN can still
    register a competing address. LAN discovery inherently trusts the LAN, and
    closing that needs the registrant to prove it holds the BizID (a signed
    token), which a backend does not have before login. Tracked as future work;
    the remote attack is what mattered and is closed.
    """
    ip = req.ip
    # If the caller sent a non-routable placeholder, fall back to the connection IP.
    if not ip or ip in ("0.0.0.0", "127.0.0.1", "localhost"):
        # request.client may be None in some test setups
        ip = (request.client.host if request.client else None) or req.ip

    if not _is_private_address(ip):
        logger.warning(
            "[DISCOVER] REJECTED registration of non-private address %s for biz %s "
            "— only LAN addresses may be advertised (S-2)", ip, req.biz_id,
        )
        raise HTTPException(
            status_code=422,
            detail="Only private (LAN) addresses can be registered for discovery.",
        )

    if not (0 < int(req.port) < 65536):
        raise HTTPException(status_code=422, detail="Invalid port.")

    biz_id = str(req.biz_id)
    _prune(biz_id)

    entries = _REGISTRY.setdefault(biz_id, [])
    now = time.time()

    # Cap the list so it cannot be flooded with decoys that push the real backend
    # down the newest-first ordering the client probes in.
    if len(entries) >= _MAX_ENTRIES_PER_BIZ and not any(
        e["ip"] == ip and e["port"] == req.port for e in entries
    ):
        logger.warning(
            "[DISCOVER] REJECTED registration for biz %s — %d entries already "
            "registered (cap %d). Possible flooding.",
            biz_id, len(entries), _MAX_ENTRIES_PER_BIZ,
        )
        raise HTTPException(
            status_code=429,
            detail="Too many backends registered for this business.",
        )

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
    logger.debug("[DISCOVER] Query biz %s → %d active backend(s)", biz_id, len(entries))
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
