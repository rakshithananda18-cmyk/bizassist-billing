import os
import sys
import pytest
import asyncio
from unittest.mock import AsyncMock, patch

# Set test environment database and mock api keys
os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

# Ensure backend folder is in path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from services.realtime import realtime_manager

@pytest.mark.anyio
async def test_realtime_manager_subscribe_and_broadcast():
    # 1. Subscribe a queue
    q = realtime_manager.subscribe(business_id=999)
    assert 999 in realtime_manager.connections
    assert q in realtime_manager.connections[999]

    # 2. Broadcast an event
    event = {"type": "sync.trigger", "entity": "product"}
    await realtime_manager.broadcast(business_id=999, event=event)

    # 3. Verify event is queued
    received = await q.get()
    assert received == event

    # 4. Unsubscribe queue
    realtime_manager.unsubscribe(business_id=999, q=q)
    assert 999 not in realtime_manager.connections


@pytest.mark.anyio
async def test_realtime_manager_queue_full_drops_connection():
    # Subscribe a queue
    q = realtime_manager.subscribe(business_id=888)
    
    # Fill up the queue past max size (100) or check handling
    # Queue put_nowait raises QueueFull if we put more than maxsize
    # Let's mock a queue that raises QueueFull
    with patch.object(q, "put_nowait", side_effect=asyncio.QueueFull):
        event = {"type": "sync.trigger", "entity": "product"}
        await realtime_manager.broadcast(business_id=888, event=event)
        
    # Verify that the queue was unsubscribed automatically
    assert 888 not in realtime_manager.connections
