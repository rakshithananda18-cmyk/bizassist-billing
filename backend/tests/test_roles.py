"""
tests/test_roles.py
===================
Staff RBAC — owner (full access) vs cashier (billing-floor only).

A cashier may ring up sales; they are blocked (403) from owner-only actions:
reports, data imports, business settings, purchases, connection management, and
manual stock adjustments. The guard is the single `restrict_cashier` in
services.auth (each route Depends on it).

The owner side asserts the routes are not *role*-blocked (they may still 4xx for
a missing record/bad body — we only assert it is never a 403-by-role).
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import User, Product

client = TestClient(app)


def _signup(business_name):
    uname = f"u_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"], "username": uname}


@pytest.fixture(scope="module")
def owner():
    return _signup("Owner Shop")


@pytest.fixture(scope="module")
def cashier():
    o = _signup("Cashier Shop")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == o["bid"]).first()
        u.role = "cashier"
        db.commit()
    finally:
        db.close()
    # Re-sign the JWT so it carries role="cashier".
    from services.auth import create_access_token
    token = create_access_token({
        "id": o["bid"], "username": o["username"],
        "business_name": "Cashier Shop", "role": "cashier",
    })
    return {"headers": {"Authorization": f"Bearer {token}"}, "bid": o["bid"]}


# (method, path, body) — owner-only routes. Bodies are valid where the route uses
# a Pydantic model, so the ONLY possible rejection is the role 403 (not a 422).
OWNER_ONLY = [
    ("GET",  "/reports/day-summary", None),
    ("GET",  "/purchases", None),
    ("POST", "/connections/code", None),                                  # no body param
    ("POST", "/import/products", {"items": []}),                          # manual body read
    ("POST", "/business/setup", {"template_key": "general"}),            # SetupRequest
    ("POST", "/products/999999/stock/adjustment", {"qty_delta": 1, "note": "x"}),
    
    # Connections / B2B Gating:
    ("GET",  "/connections", None),
    ("GET",  "/bizid", None),
    ("POST", "/connections/redeem", {"code": "abc"}),
    ("POST", "/connections/accept", {"seller_bizid": 1}),
    
    # B2B ordering Gating:
    ("GET",  "/catalog/123", None),
    ("POST", "/orders", {"seller_bizid": 1, "items": []}),
    ("GET",  "/orders", None),
    
    # Alerts Config Gating:
    ("GET",  "/alerts/config", None),
    ("POST", "/alerts/config", {"email": "test@domain.com"}),
    
    # Chat / Ask AI Gating:
    ("GET",  "/chat/sessions", None),
    ("GET",  "/chat/history", None),
    
    # Action Exec Gating:
    ("POST", "/action/preview", {"action": "remind"}),
    ("POST", "/action/execute", {"action": "remind"}),
    ("GET",  "/action/history", None),
    
    # Deterministic Intents Gating:
    ("POST", "/intent", {"intent": "remind"}),
    ("POST", "/suggestions", {"context": "remind"}),
    
    # Smart Advisory Gating:
    ("GET",  "/smart-insights", None),
    ("GET",  "/smart-insights/summary", None),
    
    # File Import/Upload Gating:
    ("GET",  "/upload/999/data", None),
    ("DELETE", "/upload/999", None),
    
    # Dashboard Insights Gating:
    ("GET",  "/insights", None),
    ("GET",  "/dashboard-summary", None),
    ("GET",  "/database", None),
    ("GET",  "/stock/ledger", None),
]


@pytest.mark.parametrize("method,path,body", OWNER_ONLY)
def test_cashier_is_blocked_from_owner_routes(cashier, method, path, body):
    resp = client.request(method, path, headers=cashier["headers"], json=body)
    assert resp.status_code == 403, f"{method} {path} should be 403 for cashier, got {resp.status_code}: {resp.text}"


@pytest.mark.parametrize("method,path,body", OWNER_ONLY)
def test_owner_is_not_role_blocked(owner, method, path, body):
    resp = client.request(method, path, headers=owner["headers"], json=body)
    assert resp.status_code != 403, f"{method} {path} should not be role-blocked for owner, got 403: {resp.text}"


def test_cashier_settings_modification(cashier, owner):
    # Cashier cannot modify non-general settings (e.g. transactions)
    resp = client.put("/settings", headers=cashier["headers"], json={
        "transactions": {"terms_and_conditions": "No returns"}
    })
    assert resp.status_code == 403
    
    # Cashier can modify general settings
    resp = client.put("/settings", headers=cashier["headers"], json={
        "general": {"business_name": "Cashier Shop Name Edit"}
    })
    assert resp.status_code == 200
    
    # Owner can modify both
    resp = client.put("/settings", headers=owner["headers"], json={
        "transactions": {"terms_and_conditions": "Standard terms"}
    })
    assert resp.status_code == 200

    # Cashier attempts to update global fields inside general section -> 403
    resp_fail = client.put("/settings", headers=cashier["headers"], json={
        "general": {"realtime_sync_global": False}
    })
    assert resp_fail.status_code == 403
    assert "Permission denied" in resp_fail.json()["detail"]


def test_cashier_can_ring_up_a_sale(cashier):
    """Cashiers CAN do their core job — create a sale invoice."""
    bid = cashier["bid"]
    db = SessionLocal()
    try:
        p = Product(business_id=bid, name="Cashier Sale Item", selling_price=100,
                    track_inventory=True, cgst_rate=9.0, sgst_rate=9.0)
        db.add(p); db.commit(); pid = p.id
    finally:
        db.close()
    resp = client.post("/sales", headers=cashier["headers"], json={
        "place_of_supply": "29", "paid_amount": 118.0,
        "lines": [{"product_id": pid, "quantity": 1, "unit_price": 100}],
    })
    assert resp.status_code in (200, 201), resp.text


def test_unauthenticated_is_401(cashier):
    """No token → 401 (auth) before any role check."""
    resp = client.get("/reports/day-summary")
    assert resp.status_code == 401
