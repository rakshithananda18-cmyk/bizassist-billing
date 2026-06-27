"""
tests/test_realtime_delta.py
============================
Real-Time Sync Robustness, Phase 1 (delta push).

Locks down the additive delta-event contract in ``services/realtime.py``:
  - ``delta_event`` builds a backward-compatible ``sync.trigger`` event that
    also carries the changed record (op/payload/kind/rid/uid);
  - a payload-less trigger is still coalesced when one is already queued;
  - two DISTINCT payloaded deltas on the same entity are NEVER coalesced
    (coalescing them would silently drop a real change).
"""
import os
import sys
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from services.realtime import realtime_manager, delta_event


def test_delta_event_shape_backward_compatible():
    ev = delta_event(
        "party",
        payload={"id": 5, "name": "Acme"},
        kind="customer",
        rid=5,
        uid="abc-123",
    )
    # Legacy fields un-migrated clients/pages still key on:
    assert ev["type"] == "sync.trigger"
    assert ev["entity"] == "party"
    # New additive fields:
    assert ev["op"] == "upsert"
    assert ev["kind"] == "customer"
    assert ev["rid"] == 5
    assert ev["uid"] == "abc-123"
    assert ev["payload"] == {"id": 5, "name": "Acme"}


def test_delta_event_minimal_is_pure_trigger():
    ev = delta_event("product")
    assert ev == {"type": "sync.trigger", "entity": "product", "op": "upsert"}
    assert "payload" not in ev  # → client refetches, as before


@pytest.mark.anyio
async def test_payloadless_triggers_coalesce():
    q = realtime_manager.subscribe(business_id=7001)
    try:
        await realtime_manager.broadcast(7001, {"type": "sync.trigger", "entity": "party"})
        await realtime_manager.broadcast(7001, {"type": "sync.trigger", "entity": "party"})
        # second one is a duplicate pure trigger → coalesced
        assert q.qsize() == 1
    finally:
        realtime_manager.unsubscribe(7001, q)


@pytest.mark.anyio
async def test_distinct_deltas_are_not_coalesced():
    q = realtime_manager.subscribe(business_id=7002)
    try:
        await realtime_manager.broadcast(
            7002, delta_event("party", payload={"id": 1, "name": "A"}, kind="customer", rid=1)
        )
        await realtime_manager.broadcast(
            7002, delta_event("party", payload={"id": 2, "name": "B"}, kind="customer", rid=2)
        )
        # Both must survive — distinct rows, even though same entity/kind.
        assert q.qsize() == 2
        first = await q.get()
        second = await q.get()
        assert {first["rid"], second["rid"]} == {1, 2}
    finally:
        realtime_manager.unsubscribe(7002, q)
