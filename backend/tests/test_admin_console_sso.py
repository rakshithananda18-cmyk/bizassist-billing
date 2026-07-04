"""
tests/test_admin_console_sso.py
===============================
Admin Console & SSO Integration plan coverage:

Phase C — SSO handoff tickets (billing → Dashboard BIZASSIST):
  * owner mints a ticket, redeems it once for a fresh JWT
  * tickets are single-use and expire
  * cashiers can't mint tickets

Phase A — hardening:
  * ADMIN_API_ENABLED gate is fail-closed (404 when off)
  * admin mutations land in the audit log

Phase B — console features:
  * /admin/businesses carries fleet fields
  * /admin/telemetry + /admin/server-log endpoints are admin-only
  * subscriptions: grant/revoke via admin, read-only for clients,
    preserved across PUT /settings, enforced only when SUBSCRIPTION_ENFORCED=1
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

import sys
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from services.auth import create_access_token, create_sse_ticket

client = TestClient(app)

OWNER = {"username": "own_sso_owner", "password": "Password123", "business_name": "SSO Test Store"}


@pytest.fixture(autouse=True)
def clear_rate_limit_windows():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _signup_or_login(creds):
    r = client.post("/signup", json=creds)
    if r.status_code != 200:
        r = client.post("/login", json={"username": creds["username"], "password": creds["password"]})
    assert r.status_code == 200, r.text
    return r.json()


def _admin_headers():
    r = client.post("/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _headers(tok):
    return {"Authorization": f"Bearer {tok}"}


# ── Phase C: SSO handoff/redeem ───────────────────────────────────────────────

def test_sso_handoff_and_redeem_single_use():
    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])

    r = client.post("/handoff-ticket", headers=h)
    assert r.status_code == 200, r.text
    ticket = r.json()["ticket"]
    assert ticket

    r = client.post("/redeem-ticket", json={"ticket": ticket})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == OWNER["username"]
    assert body["token"]
    assert body["role"] == owner["role"]

    # Single-use: second redemption must fail
    r2 = client.post("/redeem-ticket", json={"ticket": ticket})
    assert r2.status_code == 401


def test_sso_redeem_expired_ticket():
    owner = _signup_or_login(OWNER)
    payload = {"id": owner["id"], "user_id": owner["user_id"],
               "username": owner["username"], "role": owner["role"]}
    ticket = create_sse_ticket(payload, expires_in_seconds=-1)
    r = client.post("/redeem-ticket", json={"ticket": ticket})
    assert r.status_code == 401


def test_sso_redeem_garbage_ticket():
    r = client.post("/redeem-ticket", json={"ticket": "not-a-real-ticket"})
    assert r.status_code == 401


def test_sso_cashier_cannot_mint_ticket():
    owner = _signup_or_login(OWNER)
    cashier_token = create_access_token({
        "id": owner["id"], "user_id": owner["user_id"],
        "username": owner["username"], "role": "cashier",
    })
    r = client.post("/handoff-ticket", headers=_headers(cashier_token))
    assert r.status_code == 403


# ── Phase A: fail-closed admin gate + audit log ──────────────────────────────

def test_admin_api_fail_closed_when_disabled():
    ah = _admin_headers()
    prev = os.environ.get("ADMIN_API_ENABLED")
    os.environ["ADMIN_API_ENABLED"] = "0"
    try:
        r = client.get("/admin/businesses", headers=ah)
        assert r.status_code == 404          # not 403 — surface must not exist
    finally:
        os.environ["ADMIN_API_ENABLED"] = prev or "1"
    # Re-enabled: works again
    r = client.get("/admin/businesses", headers=ah)
    assert r.status_code == 200


def test_admin_mutation_writes_audit_log():
    ah = _admin_headers()
    owner = _signup_or_login(OWNER)
    r = client.post(f"/admin/subscription/{owner['id']}",
                    json={"plan": "pro", "note": "audit-test"}, headers=ah)
    assert r.status_code == 200, r.text

    r = client.get("/admin/audit-log", headers=ah)
    assert r.status_code == 200
    entries = r.json()
    hit = next((e for e in entries if e.get("action") == "set_subscription"
                and e.get("details", {}).get("note") == "audit-test"), None)
    assert hit is not None
    # Identities are BizID-based (stable across cloud/local DBs), not just row ids.
    # (The seeded admin account may predate BizIDs — key must exist, value may be None.)
    assert hit.get("admin_username") == "admin"
    assert "admin_bizid" in hit
    assert hit["details"].get("target_bizid") == owner["public_id"]
    assert hit["details"].get("target_username") == OWNER["username"]

    # cleanup: revoke
    client.post(f"/admin/subscription/{owner['id']}", json={"plan": "free"}, headers=ah)


# ── Phase B: fleet fields, telemetry, server log ─────────────────────────────

def test_admin_businesses_has_fleet_fields():
    _signup_or_login(OWNER)
    ah = _admin_headers()
    r = client.get("/admin/businesses", headers=ah)
    assert r.status_code == 200
    rows = r.json()
    assert rows, "expected at least one business"
    for key in ("bizid", "hosting_mode", "last_sync_at", "sync_queue_depth", "online_last_24h", "plan"):
        assert key in rows[0], f"missing fleet field {key}"


def test_admin_telemetry_viewer_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # telemetry writes logs/ relative to CWD
    batch = {
        "source": "desktop-shell", "device_id": "test-device-123",
        "app_version": "9.9.9", "platform": "win32",
        "events": [{"event": "boot_ok", "level": "info", "payload": {"ms": 1200}}],
    }
    r = client.post("/api/telemetry/log", json=batch)
    assert r.status_code == 200 and r.json()["accepted"] == 1

    ah = _admin_headers()
    r = client.get("/admin/telemetry", params={"device": "test-device"}, headers=ah)
    assert r.status_code == 200
    events = r.json()["events"]
    assert any(e["event"] == "boot_ok" and e["device_id"] == "test-device-123" for e in events)

    # level filter excludes
    r = client.get("/admin/telemetry", params={"level": "error"}, headers=ah)
    assert all(e["level"] == "error" for e in r.json()["events"])

    r = client.get("/admin/telemetry/devices", headers=ah)
    assert r.status_code == 200
    assert any(d["device_id"] == "test-device-123" and d["app_version"] == "9.9.9"
               for d in r.json())


def test_admin_telemetry_requires_admin():
    owner = _signup_or_login(OWNER)
    r = client.get("/admin/telemetry", headers=_headers(owner["token"]))
    assert r.status_code == 403
    r = client.get("/admin/server-log", headers=_headers(owner["token"]))
    assert r.status_code == 403


def test_admin_server_log_endpoint():
    ah = _admin_headers()
    r = client.get("/admin/server-log", params={"lines": 50}, headers=ah)
    assert r.status_code == 200
    body = r.json()
    assert "lines" in body and isinstance(body["lines"], list)


# ── Phase B.5: subscriptions ─────────────────────────────────────────────────

def test_subscription_grant_visible_and_client_immutable():
    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])
    ah = _admin_headers()

    # Grant pro
    r = client.post(f"/admin/subscription/{owner['id']}",
                    json={"plan": "pro", "status": "active"}, headers=ah)
    assert r.status_code == 200 and r.json()["plan"] == "pro"

    # Owner sees it read-only in /settings
    r = client.get("/settings", headers=h)
    assert r.status_code == 200
    assert r.json()["subscription"]["plan"] == "pro"

    # A normal settings save must NOT clobber the subscription
    r = client.put("/settings", json={"general": {"privacy_mode": True}}, headers=h)
    assert r.status_code == 200
    assert r.json()["subscription"]["plan"] == "pro"
    r = client.get("/settings", headers=h)
    assert r.json()["subscription"]["plan"] == "pro"
    assert r.json()["general"]["privacy_mode"] is True

    # Revoke
    r = client.post(f"/admin/subscription/{owner['id']}", json={"plan": "free"}, headers=ah)
    assert r.status_code == 200 and r.json()["plan"] == "free"
    r = client.get("/settings", headers=h)
    assert r.json()["subscription"]["plan"] == "free"


def test_subscription_expiry_downgrades():
    owner = _signup_or_login(OWNER)
    ah = _admin_headers()
    r = client.post(f"/admin/subscription/{owner['id']}",
                    json={"plan": "pro", "expires_at": "2000-01-01T00:00:00"}, headers=ah)
    assert r.status_code == 200
    r = client.get("/settings", headers=_headers(owner["token"]))
    assert r.json()["subscription"]["plan"] == "free"   # expired → effective free
    client.post(f"/admin/subscription/{owner['id']}", json={"plan": "free"}, headers=ah)


def test_subscription_enforcement_gates_ask_and_hybrid():
    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])
    ah = _admin_headers()
    prev = os.environ.get("SUBSCRIPTION_ENFORCED")
    os.environ["SUBSCRIPTION_ENFORCED"] = "1"
    try:
        # Free plan: AI blocked with 402
        r = client.post("/ask", json={"message": "how many invoices"}, headers=h)
        assert r.status_code == 402
        # Free plan: hybrid activation blocked with 402
        r = client.put("/settings", json={"general": {"hosting_mode": "hybrid"}}, headers=h)
        assert r.status_code == 402

        # Grant pro → both pass the plan gate
        r = client.post(f"/admin/subscription/{owner['id']}", json={"plan": "pro"}, headers=ah)
        assert r.status_code == 200
        r = client.post("/ask", json={"message": "how many invoices"}, headers=h)
        assert r.status_code == 200          # DIRECT route — no LLM call needed
        r = client.put("/settings", json={"general": {"hosting_mode": "hybrid"}}, headers=h)
        assert r.status_code == 200
        # restore hosting mode + plan
        client.put("/settings", json={"general": {"hosting_mode": "local"}}, headers=h)
        client.post(f"/admin/subscription/{owner['id']}", json={"plan": "free"}, headers=ah)
    finally:
        if prev is None:
            os.environ.pop("SUBSCRIPTION_ENFORCED", None)
        else:
            os.environ["SUBSCRIPTION_ENFORCED"] = prev


def test_subscription_dormant_by_default():
    """With SUBSCRIPTION_ENFORCED unset/0 nothing is blocked (testing phase)."""
    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])
    assert os.environ.get("SUBSCRIPTION_ENFORCED", "0") != "1"
    r = client.post("/ask", json={"message": "how many invoices"}, headers=h)
    assert r.status_code == 200
