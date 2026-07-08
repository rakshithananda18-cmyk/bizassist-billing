import asyncio
import logging
import os
from typing import Dict, Set, Any, Optional
from fastapi import HTTPException

logger = logging.getLogger("bizassist.realtime")

# ── Cross-network relay config ─────────────────────────────────────────────────
# Local (SQLite) backend only: relay pos.* events to the cloud so cashiers
# on different networks receive them in real time via cloud SSE.
_CLOUD_URL = os.getenv("CLOUD_URL", "https://rakshit-dev-bizassist.hf.space")
_DATABASE_URL = os.getenv("DATABASE_URL", "")
_IS_LOCAL_BACKEND = not _DATABASE_URL.startswith("postgresql")

# Relay events only for these type prefixes — never relay relay events themselves
_RELAY_PREFIXES = ("pos.",)


def delta_event(
    entity: str,
    op: str = "upsert",
    payload: Optional[dict] = None,
    *,
    kind: Optional[str] = None,
    rid: Optional[Any] = None,
    uid: Optional[str] = None,
) -> Dict[str, Any]:
    """(Sync Robustness Phase 1) Build an SSE event that carries the *changed
    record* so clients can patch their cache instead of refetching the whole list.

    Backward compatible: keeps ``type="sync.trigger"`` + ``entity`` so older
    frontends and un-migrated pages keep treating it as a plain refetch nudge.
    The new fields are purely additive:

      - ``op``      "upsert" | "delete"
      - ``payload`` the record in the SAME shape the page's list uses (a DTO,
                    not the raw ORM row), so a client can splice it in directly.
                    Omit it to fall back to a pure trigger (client refetches).
      - ``kind``    optional sub-type when one ``entity`` channel carries
                    multiple list kinds (e.g. "party" -> "customer"/"vendor").
      - ``rid``     the row id (stable within a single DB -> fine for cloud mode,
                    where every client reads the same cloud DB).
      - ``uid``     the durable cross-DB key (forward-compat for Phase 2+).

    A client that doesn't understand ``payload`` just refetches as before; one
    that does patches by ``rid`` (or ``uid``) and skips the network round-trip.
    """
    event: Dict[str, Any] = {"type": "sync.trigger", "entity": entity, "op": op}
    if kind is not None:
        event["kind"] = kind
    if rid is not None:
        event["rid"] = rid
    if uid is not None:
        event["uid"] = uid
    if payload is not None:
        event["payload"] = payload
    return event


class RealtimeManager:
    def __init__(self):
        # Maps business_id -> Set of asyncio.Queue
        self.connections: Dict[int, Set[asyncio.Queue]] = {}
        # The main server event loop. Subscriber queues are bound to it, so any
        # broadcast that originates off-loop (e.g. the APScheduler sync worker
        # thread) MUST be marshalled back onto this loop — see broadcast_threadsafe.
        self._loop: "asyncio.AbstractEventLoop | None" = None

    def set_loop(self, loop: "asyncio.AbstractEventLoop") -> None:
        """Record the main event loop. Called once from the app lifespan startup."""
        self._loop = loop
        logger.info("[REALTIME] Main event loop registered for cross-thread broadcasts.")

    def broadcast_threadsafe(self, business_id: int, event: Dict[str, Any]) -> bool:
        """
        (R-1) Schedule a broadcast onto the main loop from ANY thread.

        The background sync worker runs in an APScheduler thread; calling
        asyncio.run() there spins up a *different* loop whose put_nowait never
        wakes the main-loop SSE consumers, so pull events were silently lost.
        run_coroutine_threadsafe hands the coroutine to the real loop instead.

        Returns True if the broadcast was scheduled, False if no loop is ready.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            logger.warning("[REALTIME] No running main loop — dropping %s broadcast for business %s",
                           event.get("type"), business_id)
            return False
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(business_id, event), loop)
            return True
        except Exception as e:
            logger.warning("[REALTIME] threadsafe broadcast failed for business %s: %s", business_id, e)
            return False

    def subscribe(self, business_id: int) -> asyncio.Queue:
        """Subscribe a new client queue for a business_id."""
        active_conns = len(self.connections.get(business_id, set()))
        if active_conns >= 20:
            logger.warning(f"[REALTIME] Rejecting subscription for Business {business_id}: too many connections ({active_conns})")
            raise HTTPException(status_code=429, detail="Too many SSE connections for this business")

        q = asyncio.Queue(maxsize=100)  # Bound the queue size to prevent leak memory
        if business_id not in self.connections:
            self.connections[business_id] = set()
        self.connections[business_id].add(q)
        conn_type = "LAN" if _IS_LOCAL_BACKEND else "Cloud"
        logger.info(f"[REALTIME][{conn_type}] Business {business_id} subscribed. Active connections: {len(self.connections[business_id])}")
        return q

    def unsubscribe(self, business_id: int, q: asyncio.Queue):
        """Unsubscribe a client queue."""
        if business_id in self.connections:
            self.connections[business_id].discard(q)
            if not self.connections[business_id]:
                del self.connections[business_id]
            conn_type = "LAN" if _IS_LOCAL_BACKEND else "Cloud"
            logger.info(f"[REALTIME][{conn_type}] Business {business_id} unsubscribed.")

    async def broadcast(self, business_id: int, event: Dict[str, Any]):
        """Broadcast an event to all connected queues for a business_id."""
        event_type = event.get('type')
        if event_type == 'pos.presence':
            logger.debug(f"[REALTIME] Broadcasting to Business {business_id}: {event_type}")
        else:
            logger.info(f"[REALTIME] Broadcasting to Business {business_id}: {event_type}")

        # Cross-network relay: mirror pos.* events to cloud SSE (fire-and-forget).
        # Only fires on local backends; cloud-connected clients receive the event
        # via cloud SSE even when on a different network than the owner.
        if any(event_type.startswith(p) for p in _RELAY_PREFIXES):
            asyncio.ensure_future(self._relay_to_cloud(business_id, event))

        if business_id not in self.connections:
            return
        
        # Gather active queues to write
        queues = list(self.connections[business_id])
        for q in queues:
            # Event deduplication / backpressure for rapid duplicate events.
            # IMPORTANT (Phase 1): only coalesce *pure* triggers (no payload).
            # A delta carries the actual changed record, so two deltas on the
            # same entity are distinct rows — coalescing them would silently drop
            # a real change. We therefore dedupe a trigger only against another
            # payload-less trigger for the same entity.
            if event.get("type") == "sync.trigger" and "payload" not in event:
                duplicate = False
                for item in list(q._queue):
                    if (isinstance(item, dict)
                            and item.get("type") == "sync.trigger"
                            and "payload" not in item
                            and item.get("entity") == event.get("entity")):
                        duplicate = True
                        break
                if duplicate:
                    logger.debug(f"[REALTIME] Skipping duplicate trigger for entity {event.get('entity')} (already queued)")
                    continue

            try:
                # Add to queue without blocking if space available
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Discard slow reader
                logger.warning(f"[REALTIME] Queue full for Business {business_id}, dropping connection.")
                self.unsubscribe(business_id, q)

    async def _relay_to_cloud(self, business_id: int, event: Dict[str, Any]) -> None:
        """Fire-and-forget relay of a local pos.* event to the cloud SSE hub.

        Only runs on the local (SQLite) backend. Skips events that already came
        from the cloud (relay_source='local') to prevent echo loops.
        """
        if not _IS_LOCAL_BACKEND:
            return   # we ARE the cloud — no relay needed
        if event.get("relay_source") == "local":
            return   # already relayed — don't echo back
        event_type = event.get("type", "")
        if not any(event_type.startswith(p) for p in _RELAY_PREFIXES):
            return   # only relay pos.* events

        try:
            # Import here to avoid circular deps and keep startup fast
            import httpx
            from services.sync_worker import _get_cloud_token
            cloud_token = _get_cloud_token(business_id)
            if not cloud_token:
                return   # no cloud token — hybrid not configured

            relay_payload = dict(event)
            relay_payload["relay_source"] = "local"

            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.post(
                    f"{_CLOUD_URL}/realtime/relay",
                    json=relay_payload,
                    headers={"Authorization": f"Bearer {cloud_token}"},
                )
        except Exception as e:
            # Best-effort — never break local SSE if relay fails
            logger.debug("[REALTIME] Cloud relay failed for %s: %s", event_type, e)

    def shutdown(self):
        """Push a shutdown event to all queues to unblock SSE responses during server restart."""
        for queues in self.connections.values():
            for q in list(queues):
                try:
                    q.put_nowait({"type": "shutdown"})
                except asyncio.QueueFull:
                    pass

realtime_manager = RealtimeManager()

