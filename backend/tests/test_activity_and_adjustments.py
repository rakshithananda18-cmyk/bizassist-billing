"""
tests/test_activity_and_adjustments.py
======================================
Batch-4 owner requirements:
  * GET /activity — the full business activity feed (owner-only, categorized,
    human summaries, what-changed diffs).
  * Stock adjustments now REQUIRE a reason (anti-tamper) and land in the feed.
  * Sync resolver: a staff token whose staff row isn't mirrored resolves via
    the OWNER BizID instead of the old cross-business refusal.
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

client = TestClient(app)

OWNER = {"username": "own_activity_owner", "password": "Password123",
         "business_name": "Activity Feed Store"}


@pytest.fixture(autouse=True)
def clear_windows():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _signup_or_login(creds):
    r = client.post("/signup", json=creds)
    if r.status_code != 200:
        r = client.post("/login", json={"username": creds["username"], "password": creds["password"]})
    assert r.status_code == 200, r.text
    return r.json()


def _headers(tok):
    return {"Authorization": f"Bearer {tok}"}


def _create_product(h, name):
    r = client.post("/products", headers=h, json={
        "name": name, "selling_price": 100, "cost_price": 60, "opening_stock": 10,
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_activity_feed_captures_everything_and_diffs():
    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])

    p = _create_product(h, "Feed Widget")
    # An update produces a what-changed diff.
    r = client.patch(f"/products/{p['id']}", headers=h, json={"selling_price": 120})
    assert r.status_code == 200, r.text

    r = client.get("/activity?limit=50", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    summaries = [i["summary"] for i in body["items"]]
    assert any("Feed Widget" in s for s in summaries), summaries
    # Opening stock movement shows up under the stock category.
    assert any(i["category"] == "stock" for i in body["items"])
    # The product update carries a field-level diff.
    upd = next(i for i in body["items"]
               if i["table"] == "products" and i["action"] == "UPDATE")
    assert upd["changes"] and "selling_price" in upd["changes"]
    assert upd["changes"]["selling_price"]["to"] in (120, 120.0, "120.0", "120")

    # Category filter narrows correctly; a bad category is a clean 400.
    r = client.get("/activity?category=stock", headers=h)
    assert r.status_code == 200
    assert all(i["category"] == "stock" for i in r.json()["items"])
    assert client.get("/activity?category=nope", headers=h).status_code == 400


def test_activity_feed_blocked_for_staff():
    owner = _signup_or_login(OWNER)
    from services.auth import create_access_token, decode_access_token
    tv = decode_access_token(owner["token"]).get("tv", 0)
    cashier_tok = create_access_token({
        "id": owner["id"], "user_id": owner["user_id"], "username": "act_cashier",
        "public_id": owner["public_id"], "business_name": owner["business_name"],
        "role": "cashier", "tv": tv,
    })
    assert client.get("/activity", headers=_headers(cashier_tok)).status_code == 403


def test_stock_adjustment_requires_reason():
    owner = _signup_or_login(OWNER)
    h = _headers(owner["token"])
    p = _create_product(h, "Reason Widget")

    # Blank reason → 422 with a helpful message.
    r = client.post(f"/products/{p['id']}/stock/adjustment", headers=h,
                    json={"qty_delta": -2, "note": "  "})
    assert r.status_code == 422
    assert "reason is required" in r.json()["detail"].lower()

    # With a reason it records, and the movement lands in the activity feed.
    r = client.post(f"/products/{p['id']}/stock/adjustment", headers=h,
                    json={"qty_delta": -2, "note": "damaged in transit"})
    assert r.status_code == 201, r.text

    r = client.get("/activity?category=stock", headers=h)
    assert any("Reason Widget" in i["summary"] and "adjustment" in i["summary"].lower()
               for i in r.json()["items"])


def test_sync_resolver_heals_unmirrored_staff():
    """A staff token (owner BizID + staff username unknown to this DB) must
    resolve to the owner's business instead of a cross-business refusal."""
    from routes.sync import _resolve_business_id_by_username
    from database.db import SessionLocal

    owner = _signup_or_login(OWNER)
    db = SessionLocal()
    try:
        fake_staff_token_payload = {
            "id": owner["id"], "user_id": 999999,
            "username": "totally_unmirrored_staff",
            "public_id": owner["public_id"], "role": "cashier",
        }
        resolved = _resolve_business_id_by_username(fake_staff_token_payload, db)
        assert resolved == owner["id"]
    finally:
        db.close()
