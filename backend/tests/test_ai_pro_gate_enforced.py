"""
tests/test_ai_pro_gate_enforced.py
==================================
The AI endpoints are Pro-only, and now actually refuse.

`/ask` and `/ask/stream` have always CARRIED `require_plan("pro")`, but that
dependency is a no-op unless SUBSCRIPTION_ENFORCED=1 — which is unset in
production. The declaration read as a paywall and enforced nothing: every plan
had the AI for free.

`force_enforcement=True` makes the existing declaration true WITHOUT flipping
the site-wide flag, which would also gate /api/sync/push and the data-transfer
import (a separate, deliberate decision).

These tests pin the part that is easy to lose: the gate must bite with
SUBSCRIPTION_ENFORCED unset, because that is the deployed configuration. A test
that sets the flag would pass against the old code and prove nothing.
"""
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest                                        # noqa: E402
from fastapi.testclient import TestClient            # noqa: E402
from main_groq import app                            # noqa: E402
from database.db import SessionLocal                 # noqa: E402
from database.models import User                     # noqa: E402

client = TestClient(app)
ENDPOINTS = ["/ask", "/ask/stream"]


@pytest.fixture(autouse=True)
def _paywall_off(monkeypatch):
    """The DEPLOYED state. If the gate only works with this on, it does not work."""
    monkeypatch.delenv("SUBSCRIPTION_ENFORCED", raising=False)


def _signup():
    uname = f"aig_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "AI Gate Co"})
    assert r.status_code == 200, r.text
    b = r.json()
    return uname, {"Authorization": f"Bearer {b['token']}"}


def _set_subscription(uname, sub):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == uname).first()
        s = json.loads(u.settings) if u.settings else {}
        if sub is None:
            s.pop("subscription", None)
        else:
            s["subscription"] = sub
        u.settings = json.dumps(s)
        db.commit()
    finally:
        db.close()


def test_free_plan_is_refused_with_the_paywall_flag_unset():
    uname, headers = _signup()
    _set_subscription(uname, None)          # no subscription at all → free
    for ep in ENDPOINTS:
        r = client.post(ep, json={"message": "what were my sales today"}, headers=headers)
        assert r.status_code == 402, f"{ep} let a free plan through: {r.status_code}"
        assert "Pro plan" in r.text


def test_an_expired_pro_is_refused_too():
    """`effective_plan` downgrades a lapsed subscription to free. A gate that
    read the stored string instead would keep serving a cancelled account."""
    uname, headers = _signup()
    _set_subscription(uname, {"plan": "pro", "status": "active",
                              "expires_at": "2020-01-01T00:00:00+00:00"})
    for ep in ENDPOINTS:
        r = client.post(ep, json={"message": "hello"}, headers=headers)
        assert r.status_code == 402, f"{ep} served an expired Pro: {r.status_code}"


def test_an_active_pro_is_not_refused():
    """The gate must not be the reason a paying customer fails. Anything other
    than 402 is fine here — the AI client itself is unconfigured in tests, so a
    503 from _require_ai_client means the gate was passed, which is the point."""
    uname, headers = _signup()
    _set_subscription(uname, {"plan": "pro", "status": "active"})
    for ep in ENDPOINTS:
        r = client.post(ep, json={"message": "hello"}, headers=headers)
        assert r.status_code != 402, f"{ep} refused an active Pro"
