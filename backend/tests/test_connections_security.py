"""
tests/test_connections_security.py
==================================
The must-pass security gate for the B2B ecosystem (the USP moat). Self-contained
(creates its own seller/buyer/stranger + connection), so it doesn't depend on
test ordering. Proves the core promise — "share the deal, not the books":

  • a buyer NEVER sees a seller's cost price / margin,
  • a buyer NEVER sees a seller's customers,
  • an UNCONNECTED business is denied the catalog (403),
  • hidden-stock policy is honoured (stock not leaked),
  • revoking a connection immediately closes the data pipe.
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
from database.models import User, Product, Inventory
from core.models import B2BConnection

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _signup(business_name):
    uname = f"u_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"]}


def _bizid(bid):
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == bid).first().public_id
    finally:
        db.close()


def _connect(seller, buyer):
    """Seller issues a code; buyer redeems it → an 'accepted' connection. Returns conn_id."""
    code = client.post("/connections/code", headers=seller["headers"]).json()["code"]
    r = client.post("/connections/redeem", headers=buyer["headers"], json={"code": code})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        conn = db.query(B2BConnection).filter(
            B2BConnection.seller_business_id == seller["bid"],
            B2BConnection.buyer_business_id == buyer["bid"],
        ).first()
        return conn.id
    finally:
        db.close()


def _seed_products(seller_bid):
    db = SessionLocal()
    try:
        p = Product(business_id=seller_bid, name="Secret-Margin Item", selling_price=100.0,
                    cost_price=60.0, category="Medicines", is_active=True)
        db.add(p); db.commit()
        db.add(Inventory(business_id=seller_bid, product_id=p.id, stock=25)); db.commit()
    finally:
        db.close()


def test_catalog_never_leaks_cost_or_margin():
    seller, buyer = _signup("Seller Co"), _signup("Buyer Co")
    _connect(seller, buyer)
    _seed_products(seller["bid"])
    resp = client.get(f"/catalog/{_bizid(seller['bid'])}", headers=buyer["headers"])
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) >= 1
    for it in items:
        assert "cost_price" not in it                 # the seller's margin is NEVER exposed
        assert "wholesale_price" not in it
        assert "distributor_price" not in it
        assert it["selling_price"] == 100.0           # buyer sees the policy price, not cost 60


def test_buyer_cannot_see_seller_customers():
    seller, buyer = _signup("Seller Cust"), _signup("Buyer Cust")
    _connect(seller, buyer)
    client.post("/customers", headers=seller["headers"],
                json={"name": "Seller Secret Customer", "phone": "9990001111"})
    resp = client.get("/customers", headers=buyer["headers"])
    assert resp.status_code == 200
    data = resp.json()
    rows = data["items"] if isinstance(data, dict) and "items" in data else data
    names = [c.get("name") for c in rows]
    assert "Seller Secret Customer" not in names      # customers stay private to the seller


def test_unconnected_stranger_is_denied_catalog():
    seller, buyer, stranger = _signup("Seller X"), _signup("Buyer X"), _signup("Stranger X")
    _connect(seller, buyer)
    _seed_products(seller["bid"])
    seller_bizid = _bizid(seller["bid"])
    assert client.get(f"/catalog/{seller_bizid}", headers=buyer["headers"]).status_code == 200
    assert client.get(f"/catalog/{seller_bizid}", headers=stranger["headers"]).status_code == 403


def test_hidden_stock_is_not_leaked():
    seller, buyer = _signup("Seller H"), _signup("Buyer H")
    conn_id = _connect(seller, buyer)
    _seed_products(seller["bid"])
    client.post(f"/connections/{conn_id}/policy", headers=seller["headers"], json={
        "price_tier": "standard", "discount_pct": 0.0, "credit_limit": 0.0,
        "stock_visibility": "hidden", "catalog_category": None,
    })
    items = client.get(f"/catalog/{_bizid(seller['bid'])}", headers=buyer["headers"]).json()["items"]
    assert items and all(it["stock"] is None for it in items)


def test_revoke_immediately_closes_the_pipe():
    seller, buyer = _signup("Seller R"), _signup("Buyer R")
    conn_id = _connect(seller, buyer)
    _seed_products(seller["bid"])
    seller_bizid = _bizid(seller["bid"])
    assert client.get(f"/catalog/{seller_bizid}", headers=buyer["headers"]).status_code == 200
    assert client.post(f"/connections/{conn_id}/revoke", headers=buyer["headers"]).status_code == 200
    assert client.get(f"/catalog/{seller_bizid}", headers=buyer["headers"]).status_code == 403
