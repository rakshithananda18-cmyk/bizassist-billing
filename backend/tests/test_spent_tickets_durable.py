# Observed counterexamples on the unfixed code (task 1.1):
#   POST /redeem-ticket: first redemption 200; after _used_tickets.clear() the
#     same ticket is redeemed again -> 200 and a new session.
#   redeem_sse_ticket: after _used_tickets.clear() the same /realtime/ticket
#     ticket is accepted again (returns the owner's payload, not None).
"""
tests/test_spent_tickets_durable.py
===================================
Bug condition exploration for C4.3 (bugfix 1.40, design Property 1 and
Property 4): a hand-off or SSE ticket is redeemable at most once, also after a
restart (2.40).

A restart is simulated by clearing services.auth._used_tickets, the in-process
record of spent tickets, between two redemptions of the same fresh ticket. The
second redemption must be refused as already used. Each ticket is fresh (30 s)
when it is redeemed again, so no other refusal reason applies.
"""
import logging
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient

from main_groq import app
import services.auth as auth
from tests.signup_fixture import signup_payload

client = TestClient(app)
PASSWORD = "Password123!"


@pytest.fixture(autouse=True)
def _isolated_ticket_state():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()
    auth._used_tickets.clear()
    yield
    auth._used_tickets.clear()


def _owner_token() -> str:
    username = f"own_spt_{uuid.uuid4().hex[:10]}"
    r = client.post("/signup", json=signup_payload({
        "username": username, "password": PASSWORD, "business_name": "Spent Ticket Store",
    }))
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _simulate_restart() -> None:
    auth._used_tickets.clear()


def test_handoff_ticket_stays_spent_after_a_restart(caplog):
    """POST /redeem-ticket (AI dashboard, admin console).

    **Validates: Requirements 1.40 (expected 2.40)**
    """
    token = _owner_token()
    r = client.post("/handoff-ticket", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    ticket = r.json()["ticket"]

    first = client.post("/redeem-ticket", json={"ticket": ticket})
    assert first.status_code == 200, first.text

    _simulate_restart()
    with caplog.at_level(logging.INFO, logger="bizassist.auth"):
        second = client.post("/redeem-ticket", json={"ticket": ticket})
    assert second.status_code == 401, (
        f"the spent ticket was redeemed again after a restart: {second.status_code}, "
        f"body keys {sorted(second.json()) if second.status_code == 200 else second.text[:200]}"
    )
    detail = str(second.json().get("detail", ""))
    assert "already used" in detail.lower() or "already_used" in caplog.text, (
        f"the refusal does not name the already_used reason: detail={detail!r}"
    )


def test_sse_ticket_stays_spent_after_a_restart():
    """services.auth.redeem_sse_ticket, the SSE ticket redeemer.

    **Validates: Requirements 1.40 (expected 2.40)**
    """
    token = _owner_token()
    r = client.post("/realtime/ticket", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    ticket = r.json()["ticket"]

    assert auth.redeem_sse_ticket(ticket) is not None, "a fresh SSE ticket was refused"
    _simulate_restart()
    again = auth.redeem_sse_ticket(ticket)
    assert again is None, (
        f"the spent SSE ticket was redeemed again after a restart for {again.get('username')!r}"
    )
