"""
services/realtime.py
====================
In-memory Server-Sent Events (SSE) notification broker.
Routes events (e.g. order updates) to connected merchant sessions.
"""
import asyncio
import logging
from typing import Dict, Set, Any

logger = logging.getLogger("bizassist.realtime")

class RealtimeManager:
    def __init__(self):
        # Maps business_id -> Set of asyncio.Queue
        self.connections: Dict[int, Set[asyncio.Queue]] = {}

    def subscribe(self, business_id: int) -> asyncio.Queue:
        """Subscribe a new client queue for a business_id."""
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
            try:
                # Add to queue without blocking if space available
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Discard slow reader
                logger.warning(f"[REALTIME] Queue full for Business {business_id}, dropping connection.")
                self.unsubscribe(business_id, q)

realtime_manager = RealtimeManager()
