import asyncio
import logging
from typing import Dict, Set, Any
from fastapi import HTTPException

logger = logging.getLogger("bizassist.realtime")

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
        logger.info(f"[REALTIME] Business {business_id} subscribed. Active connections: {len(self.connections[business_id])}")
        return q

    def unsubscribe(self, business_id: int, q: asyncio.Queue):
        """Unsubscribe a client queue."""
        if business_id in self.connections:
            self.connections[business_id].discard(q)
            if not self.connections[business_id]:
                del self.connections[business_id]
            logger.info(f"[REALTIME] Business {business_id} unsubscribed.")

    async def broadcast(self, business_id: int, event: Dict[str, Any]):
        """Broadcast an event to all connected queues for a business_id."""
        if business_id not in self.connections:
            return
            
        logger.info(f"[REALTIME] Broadcasting to Business {business_id}: {event.get('type')}")
        
        # Gather active queues to write
        queues = list(self.connections[business_id])
        for q in queues:
            # Event deduplication / backpressure for rapid duplicate events
            if event.get("type") == "sync.trigger":
                duplicate = False
                for item in list(q._queue):
                    if isinstance(item, dict) and item.get("type") == "sync.trigger" and item.get("entity") == event.get("entity"):
                        duplicate = True
                        break
                if duplicate:
                    logger.debug(f"[REALTIME] Skipping duplicate event {event.get('type')} for entity {event.get('entity')} (already queued)")
                    continue

            try:
                # Add to queue without blocking if space available
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Discard slow reader
                logger.warning(f"[REALTIME] Queue full for Business {business_id}, dropping connection.")
                self.unsubscribe(business_id, q)

realtime_manager = RealtimeManager()

