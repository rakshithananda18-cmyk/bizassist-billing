"""
tests/test_review1_hardening.py
===============================
Coverage for the REVIEW_1 hardening + Admin Console growth-half work:

BUG-1  — /admin/health-check no longer 500s (sqlalchemy.text import regression)
GAP-1  — session hardening:
           * POST /auth/refresh issues a fresh token from a valid one
           * /admin/force-logout/{id} revokes outstanding tokens (tv bump)
           * generic ?token= query auth is OFF by default
§4.3   — campaigns / announcements / offers:
           * admin CRUD + audience preview + funnel counters
           * merchant announcements feed + seen/dismiss acks
           * offer redemption grants Pro (once), respects caps
           * email/whatsapp campaigns can't activate (honest guard)
§4.2   — /admin/sync-doctor responds with per-business verdicts
"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"
os.environ["ADMIN_API_ENABLED"] = "1"

import sys
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from services.auth import create_access_token, clear_token_version_cache

client = TestClient(app)

OWNER = {"username": "own_r1_owner", "password": "Password123", "business_name": "R1 Hardening Store"}


@pytest.fixture(autouse=True)
def clear_rate_limit_windows():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()
    clear_token_version_cache()


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


# ── BUG-1: health check ───────────────────────────────────────────────────────

def test_admin_health_check_returns_200():
    r = client.get("/admin/health-check", headers=_admin_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["db_type"] in ("sqlite", "postgresql")


# ── GAP-1: refresh / revocation / query-token ────────────────────────────────

def test_refresh_issues_working_token():
    owner = _signup_or_login(OWNER)
    r = client.post("/auth/refresh", headers=_headers(owner["token"]))
    assert r.status_code == 200, r.text
    fresh = r.json()["token"]
    assert fresh
    r2 = client.get("/profile", headers=_headers(fresh))
    assert r2.status_code == 200, r2.text


def test_force_logout_revokes_existing_token():
    owner = _signup_or_login(OWNER)
    tok = owner["token"]
    # Token works before revocation
    assert client.get("/profile", headers=_headers(tok)).status_code == 200

    r = client.post(f"/admin/force-logout/{owner['id']}", headers=_admin_headers())
    assert r.status_code == 200, r.text
    assert r.json()["revoked_accounts"] >= 1

    clear_token_version_cache()   # skip the 30s cache window in-process
    r2 = client.get("/profile", headers=_headers(tok))
    assert r2.status_code == 401, f"revoked token still accepted: {r2.status_code}"

    # Fresh login works again and carries the bumped tv
    relogin = client.post("/login", json={"username": OWNER["username"], "password": OWNER["password"]})
    assert relogin.status_code == 200
    assert client.get("/profile", headers=_headers(relogin.json()["token"])).status_code == 200


def test_query_token_auth_disabled_by_default():
    owner = _signup_or_login(OWNER)
    r = client.get(f"/profile?token={owner['token']}")
    assert r.status_code == 401, "generic ?token= auth should be off by default"


# ── §4.3: offers ─────────────────────────────────────────────────────────────

def test_offer_create_redeem_once_and_plan_grant():
    admin_h = _admin_headers()
    r = client.post("/admin/offers", headers=admin_h, json={
        "code": "r1test30", "description": "Test offer",
        "effect": {"plan": "pro", "days": 30}, "max_redemptions": 5,
    })
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "R1TEST30"

    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])

    r = client.post("/offers/redeem", json={"code": "r1test30"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "pro"

    # Plan visible through the admin subscription view
    r = client.get(f"/admin/subscription/{owner['id']}", headers=admin_h)
    assert r.status_code == 200
    assert r.json()["plan"] == "pro"

    # Second redemption of the same code → 409
    r = client.post("/offers/redeem", json={"code": "R1TEST30"}, headers=h)
    assert r.status_code == 409, r.text


def test_offer_validation_rejects_bad_effect():
    r = client.post("/admin/offers", headers=_admin_headers(), json={
        "code": "badeffect", "effect": {"plan": "enterprise", "days": 30},
    })
    assert r.status_code == 400


# ── §4.3: campaigns + announcements ──────────────────────────────────────────

def test_campaign_lifecycle_and_merchant_feed():
    admin_h = _admin_headers()

    r = client.post("/admin/campaigns", headers=admin_h, json={
        "title": "R1 test announcement", "body_md": "**Hello** merchants!",
        "channel": "in_app", "status": "active", "audience": {},
    })
    assert r.status_code == 200, r.text
    campaign_id = r.json()["id"]
    assert r.json()["live"] is True

    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])

    # Merchant sees it (delivery row is written on first fetch)
    r = client.get("/announcements", headers=h)
    assert r.status_code == 200, r.text
    anns = r.json()["announcements"]
    assert any(a["id"] == campaign_id for a in anns), anns

    # Ack seen + dismiss
    assert client.post(f"/announcements/{campaign_id}/ack", json={"event": "seen"}, headers=h).status_code == 200
    assert client.post(f"/announcements/{campaign_id}/ack", json={"event": "dismissed"}, headers=h).status_code == 200

    # Dismissed → gone from the feed
    r = client.get("/announcements", headers=h)
    assert all(a["id"] != campaign_id for a in r.json()["announcements"])

    # Funnel counters reflect the journey
    r = client.get("/admin/campaigns", headers=admin_h)
    row = next(c for c in r.json() if c["id"] == campaign_id)
    assert row["stats"]["delivered"] >= 1
    assert row["stats"]["seen"] >= 1
    assert row["stats"]["dismissed"] >= 1

    # Pause hides it from merchants
    r = client.post(f"/admin/campaigns/{campaign_id}/status", headers=admin_h, json={"status": "paused"})
    assert r.status_code == 200 and r.json()["live"] is False


def test_email_campaign_cannot_activate_yet():
    r = client.post("/admin/campaigns", headers=_admin_headers(), json={
        "title": "email blast", "body_md": "x", "channel": "email", "status": "active",
    })
    assert r.status_code == 400, "email campaigns must not activate until the notifier is wired"


def test_audience_preview_counts():
    _signup_or_login(OWNER)
    r = client.post("/admin/campaigns/preview-audience", headers=_admin_headers(),
                    json={"audience": {}})
    assert r.status_code == 200
    assert r.json()["matched"] >= 1


def test_announcements_blocked_for_cashiers():
    owner = _signup_or_login(OWNER)
    # Carry the owner's CURRENT token_version claim — an earlier test may have
    # bumped it via force-logout, and a stale/absent tv is (correctly) a 401
    # before the role check ever runs.
    from services.auth import decode_access_token
    tv = decode_access_token(owner["token"]).get("tv", 0)
    cashier_tok = create_access_token({
        "id": owner["id"], "user_id": owner["user_id"], "username": "r1_cashier",
        "public_id": owner["public_id"], "business_name": owner["business_name"],
        "role": "cashier", "tv": tv,
    })
    r = client.get("/announcements", headers=_headers(cashier_tok))
    assert r.status_code == 403
    r = client.post("/offers/redeem", json={"code": "ANY"}, headers=_headers(cashier_tok))
    assert r.status_code == 403


def test_campaign_admin_endpoints_require_admin():
    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])
    assert client.get("/admin/campaigns", headers=h).status_code == 403
    assert client.get("/admin/offers", headers=h).status_code == 403
    assert client.get("/admin/sync-doctor", headers=h).status_code == 403


# ── §4.2: sync doctor ────────────────────────────────────────────────────────

def test_sync_doctor_reports_businesses():
    _signup_or_login(OWNER)
    r = client.get("/admin/sync-doctor", headers=_admin_headers())
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list) and len(rows) >= 1
    for row in rows:
        assert row["status"] in ("green", "amber", "red")
        assert "pending_ops" in row and "reasons" in row
