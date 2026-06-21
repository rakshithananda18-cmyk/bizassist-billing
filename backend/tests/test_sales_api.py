"""
tests/test_sales_api.py
=======================
The Sales API over the billing command:
  • POST /sales creates an invoice (correct GST + status) for the authed business
  • GET /sales/products/search autocompletes the item master
  • GET /sales/barcode/{code} resolves a scan
  • GET /sales/{invoice_no} returns the invoice
  • auth-scoping: the sale belongs to the caller's business_id only

Uses TestClient + a real signup (mirrors test_token_accounting style).
"""
import os
import sys
import uuid

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Product, Inventory, User
from core.catalog import barcode as PB

client = TestClient(app)


@pytest.fixture(scope="module")
def auth():
    username = f"test_sales_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username, "password": "TestPass123!", "business_name": "Sales Test Biz",
    })
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    body = resp.json()
    bid = body["id"]
    # set state for intra-state GST, then seed a product + barcode + stock
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == bid).first()
        u.state_code = "29"
        p = Product(business_id=bid, name="Test Rice 25kg", sku="RICE25", unit="Bag",
                    hsn_sac="1006", cgst_rate=9, sgst_rate=9, igst_rate=18,
                    selling_price=100, track_inventory=True)
        db.add(p)
        db.flush()
        db.add(Inventory(business_id=bid, product_name="Test Rice 25kg", product_id=p.id, stock=50))
        PB.add_barcode(db, bid, p.id, "8901234567")
        db.commit()
        pid = p.id
    finally:
        db.close()
    return {"headers": {"Authorization": f"Bearer {body['token']}"}, "bid": bid, "pid": pid}


def test_create_sale(auth):
    resp = client.post("/sales", headers=auth["headers"], json={
        "place_of_supply": "29-Karnataka", "paid_amount": 236, "payment_mode": "cash",
        "lines": [{"product_id": auth["pid"], "quantity": 2, "unit_price": 100}],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subtotal"] == 200.0
    assert body["cgst_total"] == 18.0 and body["sgst_total"] == 18.0
    assert body["total_amount"] == 236.0
    assert body["status"] == "Paid"
    assert len(body["lines"]) == 1


def test_product_search(auth):
    resp = client.get("/sales/products/search", headers=auth["headers"], params={"q": "Rice"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert any(i["name"] == "Test Rice 25kg" for i in items)


def test_barcode_resolve(auth):
    ok = client.get("/sales/barcode/8901234567", headers=auth["headers"])
    assert ok.status_code == 200
    assert ok.json()["name"] == "Test Rice 25kg"
    miss = client.get("/sales/barcode/0000000", headers=auth["headers"])
    assert miss.status_code == 404


def test_get_sale_and_idempotency(auth):
    # create with an explicit number, then re-POST → same invoice (idempotent)
    payload = {
        "invoice_no": "API-IDEMP-1", "place_of_supply": "29",
        "lines": [{"product_id": auth["pid"], "quantity": 1, "unit_price": 100}],
    }
    a = client.post("/sales", headers=auth["headers"], json=payload)
    b = client.post("/sales", headers=auth["headers"], json=payload)
    assert a.status_code == 200 and b.status_code == 200
    assert a.json()["id"] == b.json()["id"]
    got = client.get("/sales/API-IDEMP-1", headers=auth["headers"])
    assert got.status_code == 200 and got.json()["invoice_no"] == "API-IDEMP-1"


def test_requires_auth(auth):
    resp = client.post("/sales", json={"lines": [{"product_name": "X", "quantity": 1, "unit_price": 10}]})
    assert resp.status_code == 401
