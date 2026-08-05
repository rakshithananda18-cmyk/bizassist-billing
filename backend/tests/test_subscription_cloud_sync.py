"""
tests/test_subscription_cloud_sync.py
=====================================
Regression (2026-07-16, "cloud shows Pro but desktop stays free"): the local
backend's subscription pull used to bail unless the LOCAL record's
`general.hosting_mode == "hybrid"`. A fresh-device mirror created by the login
fallback keeps the default 'local', so the Pro plan never propagated even
though a cloud sync token was provisioned at login. The cloud token is the
real cloud-link signal.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app

client = TestClient(app)


def _signup():
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Plan Sync Co",
    })
    assert r.status_code == 200, r.text
    return r.json()


class _FakeResp:
    status_code = 200

    def json(self):
        return {"subscription": {"plan": "pro", "status": "active", "expires_at": None}}


def test_plan_syncs_from_cloud_even_when_local_hosting_mode_is_local(monkeypatch):
    """Fresh-device mirror (hosting_mode='local' locally) + stored cloud token
    → GET /settings?force=true must pull the cloud Pro plan."""
    acct = _signup()
    auth = {"Authorization": f"Bearer {acct['token']}"}

    # The device has a cloud sync token (provisioned at login) …
    import services.sync_worker as sw
    monkeypatch.setattr(sw, "_get_cloud_token", lambda business_id: "cloud-tok")
    # … and the cloud says the business is Pro.
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp())

    r = client.get("/settings?force=true", headers=auth)
    assert r.status_code == 200, r.text
    sub = r.json().get("subscription") or {}
    assert sub.get("plan") == "pro", f"cloud Pro plan did not propagate: {sub}"
    assert sub.get("status") == "active"


def test_missing_token_does_not_lock_out_the_next_check(monkeypatch):
    """Regression: an admin's Pro grant stayed invisible for 30 minutes.

    The cooldown was armed BEFORE the cloud-token lookup, so the very first
    GET /settings at app start — which routinely beats the login's token
    provisioning — bought half an hour of silence without ever asking the
    cloud anything. Neither existing test caught it: both pass ?force=true,
    which is exactly the path that skips the cooldown.
    """
    acct = _signup()
    auth = {"Authorization": f"Bearer {acct['token']}"}

    import services.sync_worker as sw
    import httpx

    # 1. App start, token not provisioned yet. Unforced, like the real client.
    monkeypatch.setattr(sw, "_get_cloud_token", lambda business_id: None)
    r = client.get("/settings", headers=auth)
    assert r.status_code == 200
    assert (r.json().get("subscription") or {}).get("plan", "free") == "free"

    # 2. Login finishes, the token lands, and the admin has granted Pro. The
    #    next unforced read must actually ask — no 30-minute lockout.
    monkeypatch.setattr(sw, "_get_cloud_token", lambda business_id: "cloud-tok")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp())
    r = client.get("/settings", headers=auth)
    assert (r.json().get("subscription") or {}).get("plan") == "pro", \
        "a check that never happened must not arm the cooldown"


def test_successful_check_still_holds_the_cooldown(monkeypatch):
    """The other half: once the cloud HAS answered, stop asking. Without this
    the fix above would turn every GET /settings into a cloud round-trip."""
    acct = _signup()
    auth = {"Authorization": f"Bearer {acct['token']}"}

    import services.sync_worker as sw
    import httpx
    monkeypatch.setattr(sw, "_get_cloud_token", lambda business_id: "cloud-tok")

    calls = []
    monkeypatch.setattr(httpx, "get", lambda *a, **k: calls.append(a) or _FakeResp())

    client.get("/settings", headers=auth)
    assert len(calls) == 1
    client.get("/settings", headers=auth)
    assert len(calls) == 1, "a second read inside the cooldown must not re-ask the cloud"


def test_pure_local_account_makes_no_cloud_call(monkeypatch):
    """No cloud token → no network call, plan stays free."""
    acct = _signup()
    auth = {"Authorization": f"Bearer {acct['token']}"}

    import services.sync_worker as sw
    monkeypatch.setattr(sw, "_get_cloud_token", lambda business_id: None)

    calls = []
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: calls.append(a) or _FakeResp())

    r = client.get("/settings?force=true", headers=auth)
    assert r.status_code == 200
    assert (r.json().get("subscription") or {}).get("plan", "free") == "free"
    assert calls == [], "pure-local account must not call the cloud"
