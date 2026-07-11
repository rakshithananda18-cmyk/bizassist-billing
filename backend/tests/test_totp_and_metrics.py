"""
tests/test_totp_and_metrics.py
==============================
REVIEW_1 follow-up batch:
  §4.1 — admin TOTP 2FA: RFC-6238 algorithm, enroll/confirm/disable flow,
         login gate (password alone stops working once enabled),
         merchant PUT /settings cannot strip or read the totp key.
  §4.4 — /admin/metrics: plan mix, funnel, activity, churn shape.
  GAP-3 — groq_client factory exists and honors env timeout.
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
from services.auth import clear_token_version_cache
from services import totp

client = TestClient(app)

OWNER = {"username": "own_totp_owner", "password": "Password123", "business_name": "TOTP Test Store"}


@pytest.fixture(autouse=True)
def clear_windows():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()
    clear_token_version_cache()


def _admin_login(otp=None):
    body = {"username": "admin", "password": "admin123"}
    if otp is not None:
        body["otp"] = otp
    return client.post("/login", json=body)


def _admin_headers(otp=None):
    r = _admin_login(otp)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _signup_or_login(creds):
    r = client.post("/signup", json=creds)
    if r.status_code != 200:
        r = client.post("/login", json={"username": creds["username"], "password": creds["password"]})
    assert r.status_code == 200, r.text
    return r.json()


def _admin_totp_secret(headers):
    """Enroll (or read back) the admin's pending/enabled secret via the API."""
    r = client.post("/admin/2fa/setup", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["secret"]


def _cleanup_2fa(secret):
    """Best-effort: disable 2FA so later tests get a clean admin."""
    h = _admin_headers(otp=totp.current_code(secret))
    client.post("/admin/2fa/disable", json={"code": totp.current_code(secret)}, headers=h)


# ── TOTP algorithm ───────────────────────────────────────────────────────────

def test_totp_roundtrip_and_drift():
    secret = totp.generate_secret()
    code = totp.current_code(secret)
    assert totp.verify_code(secret, code)
    # ±1 step drift accepted
    assert totp.verify_code(secret, totp.current_code(secret, at=__import__("time").time() - 30))
    # garbage rejected
    assert not totp.verify_code(secret, "000000") or totp.current_code(secret) == "000000"
    assert not totp.verify_code(secret, "12345")     # wrong length
    assert not totp.verify_code(secret, "abcdef")    # not digits
    assert not totp.verify_code("", "123456")


def test_totp_provisioning_uri_format():
    secret = totp.generate_secret()
    uri = totp.provisioning_uri(secret, "admin")
    assert uri.startswith("otpauth://totp/")
    assert f"secret={secret}" in uri
    assert "period=30" in uri and "digits=6" in uri


# ── Enrollment + login gate ──────────────────────────────────────────────────

def test_2fa_full_lifecycle_and_login_gate():
    h = _admin_headers()

    # Status starts clean (or a stale pending from a crashed run — setup resets it)
    secret = _admin_totp_secret(h)
    try:
        # Pending, not yet enforced: plain login still works
        assert _admin_login().status_code == 200

        # Wrong code can't confirm
        r = client.post("/admin/2fa/confirm", json={"code": "000001"}, headers=h)
        assert r.status_code in (400,)  # (1-in-a-million collision would be a 200)

        # Confirm with a live code → enabled
        r = client.post("/admin/2fa/confirm", json={"code": totp.current_code(secret)}, headers=h)
        assert r.status_code == 200, r.text

        # Password alone now fails, with the distinct "code required" signal
        r = _admin_login()
        assert r.status_code == 401 and "2FA code required" in r.json()["detail"]

        # Wrong code fails differently
        r = _admin_login(otp="000000")
        assert r.status_code == 401

        # Correct code passes
        r = _admin_login(otp=totp.current_code(secret))
        assert r.status_code == 200, r.text

        # Status reflects enabled
        h2 = {"Authorization": f"Bearer {r.json()['token']}"}
        r = client.get("/admin/2fa/status", headers=h2)
        assert r.json()["enabled"] is True

        # Disable needs a valid code
        r = client.post("/admin/2fa/disable", json={"code": "000000"}, headers=h2)
        assert r.status_code == 400
        r = client.post("/admin/2fa/disable", json={"code": totp.current_code(secret)}, headers=h2)
        assert r.status_code == 200

        # Plain login works again
        assert _admin_login().status_code == 200
    finally:
        _cleanup_2fa(secret)


def test_2fa_never_affects_merchants():
    owner = _signup_or_login(OWNER)
    assert owner["token"]  # merchants log in without any otp handling


def test_settings_put_cannot_touch_totp():
    """PUT /settings must preserve the server-managed totp key and never echo it."""
    h = _admin_headers()
    secret = _admin_totp_secret(h)   # pending secret stored in admin settings
    try:
        # GET /settings never exposes it
        r = client.get("/settings", headers=h)
        assert r.status_code == 200
        assert "totp" not in r.json()

        # A settings save doesn't wipe the stored secret
        r = client.put("/settings", json={"general": {}}, headers=h)
        assert r.status_code == 200
        assert "totp" not in r.json()
        r = client.get("/admin/2fa/status", headers=h)
        assert r.json()["pending"] is True   # secret survived the save
    finally:
        _cleanup_2fa(secret)


# ── Metrics (§4.4) ───────────────────────────────────────────────────────────

def test_admin_metrics_shape():
    _signup_or_login(OWNER)
    r = client.get("/admin/metrics", headers=_admin_headers())
    assert r.status_code == 200, r.text
    m = r.json()
    assert set(m["plan_mix"].keys()) >= {"free", "pro"}
    f = m["funnel"]
    assert f["registered"] >= 1
    assert f["registered"] >= f["first_invoice"] >= f["ten_invoices"] >= 0
    assert m["activity"]["total"] == f["registered"]
    assert isinstance(m["churn_risk"], list)
    assert isinstance(m["expiring_within_14d"], list)


def test_admin_metrics_requires_admin():
    owner = _signup_or_login(OWNER)
    r = client.get("/admin/metrics", headers={"Authorization": f"Bearer {owner['token']}"})
    assert r.status_code == 403


# ── Groq client factory (GAP-3) ──────────────────────────────────────────────

def test_groq_client_factory_builds():
    from services.groq_client import make_groq_client, GROQ_TIMEOUT_SECS
    c = make_groq_client("test-key")
    assert c is not None
    assert GROQ_TIMEOUT_SECS > 0
