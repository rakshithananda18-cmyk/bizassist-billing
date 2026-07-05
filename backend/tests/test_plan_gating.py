"""
tests/test_plan_gating.py
=========================
Pro/free segregation:

  * /profile.is_premium reflects an active paid plan (admin grant) AND the legacy
    is_premium override column (OR of both).
  * Cloud sync (/api/sync/push) is refused for the free plan ONLY when
    SUBSCRIPTION_ENFORCED=1; a no-op otherwise (so nothing breaks before the
    paywall is switched on).
  * The admin subscription grant flips a target account to premium end-to-end.

Run:
    cd backend && python -m pytest tests/test_plan_gating.py -v
"""
import os
import sys
import json
import uuid
from datetime import datetime

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("ADMIN_API_ENABLED", "1")   # conftest also sets this

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import User

client = TestClient(app)


def _signup(name="Plan Co"):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return uname, b["id"], {"Authorization": f"Bearer {b['token']}"}


def _grant_pro_via_settings(uname):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == uname).first()
        s = json.loads(u.settings) if u.settings else {}
        s["subscription"] = {"plan": "pro", "status": "active"}
        u.settings = json.dumps(s)
        db.commit()
    finally:
        db.close()


def _set_column(uname, value):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == uname).first()
        u.is_premium = value
        db.commit()
    finally:
        db.close()


def _push_body():
    return {"changes": []}   # empty batch: gate runs before body processing


# ---------------------------------------------------------------------------
# is_premium sourcing
# ---------------------------------------------------------------------------
def test_free_account_is_not_premium():
    _, _, headers = _signup()
    assert client.get("/profile", headers=headers).json()["is_premium"] is False


def test_paid_plan_makes_premium():
    uname, _, headers = _signup()
    _grant_pro_via_settings(uname)
    assert client.get("/profile", headers=headers).json()["is_premium"] is True


def test_legacy_column_override_makes_premium():
    uname, _, headers = _signup()
    _set_column(uname, True)   # manual/admin flip — must still be honored (OR)
    assert client.get("/profile", headers=headers).json()["is_premium"] is True


# ---------------------------------------------------------------------------
# cloud sync gate (only bites when SUBSCRIPTION_ENFORCED=1)
# ---------------------------------------------------------------------------
def test_free_sync_allowed_when_not_enforced(monkeypatch):
    monkeypatch.delenv("SUBSCRIPTION_ENFORCED", raising=False)
    _, _, headers = _signup()
    r = client.post("/api/sync/push", headers=headers, json=_push_body())
    assert r.status_code == 200, r.text     # no-op gate → free can still push


def test_free_sync_blocked_when_enforced(monkeypatch):
    monkeypatch.setenv("SUBSCRIPTION_ENFORCED", "1")
    _, _, headers = _signup()
    r = client.post("/api/sync/push", headers=headers, json=_push_body())
    assert r.status_code == 402, r.text
    assert "pro" in r.json()["detail"].lower()


def test_pro_sync_allowed_when_enforced(monkeypatch):
    monkeypatch.setenv("SUBSCRIPTION_ENFORCED", "1")
    uname, _, headers = _signup()
    _grant_pro_via_settings(uname)
    r = client.post("/api/sync/push", headers=headers, json=_push_body())
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# admin grant path end-to-end
# ---------------------------------------------------------------------------
def test_admin_grant_flips_target_to_premium():
    admin_uname, _, admin_headers = _signup("Admin Co")
    target_uname, target_bid, target_headers = _signup("Target Co")

    # promote the admin account
    db = SessionLocal()
    try:
        a = db.query(User).filter(User.username == admin_uname).first()
        a.role = "admin"
        db.commit()
    finally:
        db.close()

    # target is free to start
    assert client.get("/profile", headers=target_headers).json()["is_premium"] is False

    # admin grants Pro
    r = client.post(f"/admin/subscription/{target_bid}", headers=admin_headers,
                    json={"plan": "pro", "status": "active"})
    assert r.status_code == 200, r.text

    # target is now premium
    assert client.get("/profile", headers=target_headers).json()["is_premium"] is True

    # revoke → back to free
    r2 = client.post(f"/admin/subscription/{target_bid}", headers=admin_headers,
                     json={"plan": "free"})
    assert r2.status_code == 200, r2.text
    assert client.get("/profile", headers=target_headers).json()["is_premium"] is False
