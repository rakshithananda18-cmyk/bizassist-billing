import os
import sys
import pytest
import asyncio
from datetime import datetime, timedelta
from fastapi import HTTPException
from unittest.mock import patch, MagicMock

# Set test environment database and mock api keys
os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"
os.environ["JWT_SECRET"] = "mock_jwt_secret_key_minimum_32_bytes_long"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from services.auth import (
    create_sse_ticket,
    get_active_user_or_ticket,
    _sse_tickets,
    restrict_cashier_or_ticket
)
from services.realtime import realtime_manager

def test_ticket_creation_and_expiration():
    user = {"id": 10, "username": "test_user", "role": "owner"}
    ticket = create_sse_ticket(user, expires_in_seconds=2)
    assert ticket in _sse_tickets
    
    # Retrieve user using ticket
    resolved_user = get_active_user_or_ticket(ticket=ticket)
    assert resolved_user["id"] == 10
    
    # Single-use check: ticket should be removed now
    assert ticket not in _sse_tickets
    with pytest.raises(HTTPException) as exc_info:
        get_active_user_or_ticket(ticket=ticket)
    assert exc_info.value.status_code == 401
    
    # Expiration check
    expired_ticket = create_sse_ticket(user, expires_in_seconds=-5)
    with pytest.raises(HTTPException) as exc_info:
        get_active_user_or_ticket(ticket=expired_ticket)
    assert exc_info.value.status_code == 401

def test_restrict_cashier_or_ticket():
    # Owner should be allowed
    owner_user = {"id": 10, "username": "owner_user", "role": "owner"}
    assert restrict_cashier_or_ticket(owner_user) == owner_user

    # Cashier should be blocked with 403
    cashier_user = {"id": 11, "username": "cashier_user", "role": "cashier"}
    with pytest.raises(HTTPException) as exc_info:
        restrict_cashier_or_ticket(cashier_user)
    assert exc_info.value.status_code == 403

@pytest.mark.anyio
async def test_connection_limit_guard():
    business_id = 777
    queues = []
    
    # Subscribe 20 connections
    for _ in range(20):
        q = realtime_manager.subscribe(business_id)
        queues.append(q)
        
    assert len(realtime_manager.connections[business_id]) == 20
    
    # 21st subscription should raise HTTPException 429
    with pytest.raises(HTTPException) as exc_info:
        realtime_manager.subscribe(business_id)
    assert exc_info.value.status_code == 429
    assert "Too many SSE connections" in exc_info.value.detail

    # Clean up and check that subscription works again
    for q in queues:
        realtime_manager.unsubscribe(business_id, q)
    assert business_id not in realtime_manager.connections

    # Subscribe one more time to verify it's cleared
    q = realtime_manager.subscribe(business_id)
    assert len(realtime_manager.connections[business_id]) == 1
    realtime_manager.unsubscribe(business_id, q)

@pytest.mark.anyio
async def test_event_deduplication_backpressure():
    business_id = 999
    q = realtime_manager.subscribe(business_id)
    
    try:
        # Broadcast standard sync.trigger events
        event1 = {"type": "sync.trigger", "entity": "product"}
        event2 = {"type": "sync.trigger", "entity": "product"}
        event3 = {"type": "sync.trigger", "entity": "party"}
        event4 = {"type": "sync.trigger", "entity": "product"}
        
        await realtime_manager.broadcast(business_id, event1)
        await realtime_manager.broadcast(business_id, event2)  # Duplicate of product
        await realtime_manager.broadcast(business_id, event3)  # Different entity
        await realtime_manager.broadcast(business_id, event4)  # Duplicate of product again
        
        # Verify queue contents
        assert q.qsize() == 2  # Only one product event and one party event
        
        recv1 = await q.get()
        recv2 = await q.get()
        
        assert recv1 == event1
        assert recv2 == event3
    finally:
        realtime_manager.unsubscribe(business_id, q)
