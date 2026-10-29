"""
tests/test_bill_scan_pro_gate.py
================================
Bill scanning is Pro-only, and actually refuses.

Every scan spends a vision-model call, which is the same class of metered cost
as /ask — so it is gated the same way. `require_plan("pro")` alone would be
decorative: it is a no-op unless SUBSCRIPTION_ENFORCED=1, which is unset in
production, so the endpoint would have read as a paywall while serving every
plan for free. That is exactly what /ask did until 209b96a.

These tests run with SUBSCRIPTION_ENFORCED UNSET on purpose — the deployed
configuration. A test that set the flag would pass against an ungated endpoint
and prove nothing.
"""
import io
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest                                     # noqa: E402
from fastapi.testclient import TestClient         # noqa: E402
from main_groq import app                         # noqa: E402
from database.db import SessionLocal              # noqa: E402
from database.models import User                  # noqa: E402
from tests.planhelpers import grant_pro           # noqa: E402

from tests.signup_fixture import signup_payload

client = TestClient(app)
UPLOAD = "/purchases/upload"


@pytest.fixture(autouse=True)
def _paywall_off(monkeypatch):
    monkeypatch.delenv("SUBSCRIPTION_ENFORCED", raising=False)


def _account():
    uname = f"scan_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json=signup_payload({
        "username": uname, "password": "TestPass123!", "business_name": "Scan Co"}))
    assert r.status_code == 200, r.text
    b = r.json()
    return uname, {"Authorization": f"Bearer {b['token']}"}


def _a_file():
    return {"file": ("bill.png", io.BytesIO(b"not really a png"), "image/png")}


def test_free_plan_cannot_scan_a_bill():
    _, headers = _account()
    r = client.post(UPLOAD, files=_a_file(), headers=headers)
    assert r.status_code == 402, f"a free plan reached the vision model: {r.status_code}"
    assert "Pro plan" in r.text


def test_an_expired_pro_cannot_scan_either():
    """effective_plan downgrades a lapsed subscription to free. A gate reading
    the stored string would keep spending on a cancelled account."""
    uname, headers = _account()
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == uname).first()
        s = json.loads(u.settings) if u.settings else {}
        s["subscription"] = {"plan": "pro", "status": "active",
                             "expires_at": "2020-01-01T00:00:00+00:00"}
        u.settings = json.dumps(s)
        db.commit()
    finally:
        db.close()
    assert client.post(UPLOAD, files=_a_file(), headers=headers).status_code == 402


def test_an_active_pro_is_not_refused_by_the_gate():
    """The gate must not be why a paying customer fails. The junk file will be
    rejected downstream (422/500) — anything but 402 means the gate passed."""
    uname, headers = _account()
    grant_pro(uname)
    r = client.post(UPLOAD, files=_a_file(), headers=headers)
    assert r.status_code != 402, "the gate refused an active Pro"
