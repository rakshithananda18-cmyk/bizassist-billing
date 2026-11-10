# Observed counterexample on the unfixed code (task 1.1):
#   POST /auth/logout -> 404 (no route). The dashboard token then still gets
#   200 on GET /profile, without WWW-Authenticate. The ai_dashboard purpose is
#   ignored, so the hand-off ticket is a legacy 30 s ticket.
"""
tests/test_logout_revokes_dashboard.py
======================================
Bug condition exploration for C4.5 (bugfix 1.14, design Property 1 and
Property 6): when a web user signs out of Billing, the AI dashboard session
that Billing opened ends, at the latest on the dashboard's next request (2.14).

Flow: log in to Billing, mint an ai_dashboard hand-off ticket, redeem it at
/redeem-ticket as the dashboard does, sign out with POST /auth/logout and the
Billing token, then make a dashboard request. That request must get 401 with
the session-rejection marker, so the dashboard signs out.
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
import services.auth as auth
from tests.signup_fixture import signup_payload

client = TestClient(app)
PASSWORD = "Password123!"
MARKER = 'Bearer error="invalid_token"'


@pytest.fixture(autouse=True)
def _isolated_session_state():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()
    auth._used_tickets.clear()
    yield
    auth._used_tickets.clear()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_billing_logout_ends_the_dashboard_session():
    """**Validates: Requirements 1.14 (expected 2.14)**"""
    username = f"own_lrd_{uuid.uuid4().hex[:10]}"
    r = client.post("/signup", json=signup_payload({
        "username": username, "password": PASSWORD, "business_name": "Dashboard Logout Store",
    }))
    assert r.status_code == 200, r.text
    r = client.post("/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    billing_token = r.json()["token"]

    r = client.post("/handoff-ticket", json={"purpose": "ai_dashboard"}, headers=_auth(billing_token))
    assert r.status_code == 200, r.text
    r = client.post("/redeem-ticket", json={"ticket": r.json()["ticket"]})
    assert r.status_code == 200, r.text
    dashboard_token = r.json()["token"]
    assert client.get("/profile", headers=_auth(dashboard_token)).status_code == 200

    logout = client.post("/auth/logout", headers=_auth(billing_token))
    after = client.get("/profile", headers=_auth(dashboard_token))
    assert {
        "logout_status": logout.status_code,
        "dashboard_status": after.status_code,
        "dashboard_www_authenticate": after.headers.get("www-authenticate"),
    } == {
        "logout_status": 200,
        "dashboard_status": 401,
        "dashboard_www_authenticate": MARKER,
    }
