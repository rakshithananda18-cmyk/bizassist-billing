# Observed counterexamples on the unfixed code (task 1.1, SUBSCRIPTION_ENFORCED=0):
#   free: subscription = {plan: free, status: none, expires_at: None, ends_at: None,
#     days_remaining: None, trial: False, enforced: False}, no gates.
#   pro:  subscription = {plan: pro, status: active, expires_at: None, ends_at: None,
#     days_remaining: None, trial: False, enforced: False}, no gates.
"""
tests/test_settings_gates.py
============================
Bug condition exploration for C5.1 (bugfix 1.7, 1.27 and 1.56, design
Property 1 and Property 7): GET /settings reports, per feature, whether the
server gates it for this account, so Billing stops inferring gates from
`enforced` and an unknown plan (2.7, 2.27, 2.56).

With SUBSCRIPTION_ENFORCED=0 (production, assumption 4):
  * a free account: web_preview and field_team gated, hybrid_sync not gated;
  * a Pro account: none of ai, field_team, hybrid_sync and web_preview gated.
"""
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
from tests.planhelpers import grant_pro
from tests.signup_fixture import signup_payload

client = TestClient(app)
PASSWORD = "Password123!"


@pytest.fixture(autouse=True)
def _isolated_plan_state(monkeypatch):
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()
    monkeypatch.setenv("SUBSCRIPTION_ENFORCED", "0")


def _owner_on_plan(plan: str) -> str:
    username = f"own_gate_{uuid.uuid4().hex[:10]}"
    r = client.post("/signup", json=signup_payload({
        "username": username, "password": PASSWORD, "business_name": "Plan Gates Store",
    }))
    assert r.status_code == 200, r.text
    if plan == "pro":
        grant_pro(username)
    return r.json()["token"]


@pytest.mark.parametrize("plan, expected_gates", [
    pytest.param("free", {"web_preview": True, "field_team": True, "hybrid_sync": False}, id="free"),
    pytest.param("pro", {"ai": False, "field_team": False, "hybrid_sync": False, "web_preview": False}, id="pro"),
])
def test_settings_reports_server_gates(plan, expected_gates):
    """**Validates: Requirements 1.7, 1.27, 1.56 (expected 2.7, 2.27, 2.56)**"""
    token = _owner_on_plan(plan)
    r = client.get("/settings", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    subscription = r.json()["subscription"]
    assert (subscription["plan"], subscription["enforced"]) == (plan, False)
    gates = subscription.get("gates")
    assert isinstance(gates, dict), f"GET /settings has no subscription.gates: {subscription}"
    assert {name: gates.get(name) for name in expected_gates} == expected_gates
