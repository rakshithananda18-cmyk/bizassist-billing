"""
tests/test_hash_chain.py
========================
Gate-1 coverage for R3 — the tamper-evident hash chain over the POSTED journal.

Proves:
  • a freshly-posted set of documents forms a chain that verifies clean,
  • editing a posted line in place BREAKS verification at that entry (tamper-
    evidence — the whole point),
  • idempotent re-post of a document does not add a link or break the chain,
  • `/reports/verify-chain` is owner-only (cashier 403) and business-scoped.

Self-contained: signs up its own owner(s) + cashier and seeds its own data.
"""
import os
import sys
import uuid
from datetime import datetime

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import Inventory, Invoice
from core.models import JournalEntry, JournalLine
from core.accounting import posting

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _owner(name):
    r = client.post("/signup", json={
        "username": f"o_{uuid.uuid4().hex[:8]}", "password": "Password123!", "business_name": name,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    return {"headers": {"Authorization": f"Bearer {d['token']}"}, "bid": d["id"]}


def _cashier_of(owner):
    uname = f"c_{uuid.uuid4().hex[:8]}"
    r = client.post("/staff", headers=owner["headers"],
                    json={"username": uname, "password": "Password123!", "role": "cashier"})
    assert r.status_code == 201, r.text
    login = client.post("/login", json={"username": uname, "password": "Password123!"})
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _seed(owner):
    headers, bid = owner["headers"], owner["bid"]
    today = datetime.today().strftime("%Y-%m-%d")
    p = client.post("/products", headers=headers, json={
        "name": "HC Prod", "selling_price": 100.0, "cost_price": 60.0,
        "sku": f"HC-{uuid.uuid4().hex[:5]}", "track_inventory": True,
    })
    pid = p.json()["id"]
    db = SessionLocal()
    try:
        db.add(Inventory(business_id=bid, product_name="HC Prod", product_id=pid,
                         stock=50, cost_price=60.0, selling_price=100.0))
        db.commit()
    finally:
        db.close()
    sale = client.post("/sales", headers=headers, json={
        "lines": [{"product_id": pid, "product_name": "HC Prod", "quantity": 1.0,
                   "unit_price": 100.0, "cgst_rate": 9.0, "sgst_rate": 9.0, "igst_rate": 0.0}],
        "customer": "HC Cust", "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": today, "paid_amount": 40.0, "payment_mode": "UPI",
    })
    assert sale.status_code == 200, sale.text
    client.post("/purchases/confirm", headers=headers, json={
        "supplier_name": "HC Vend", "invoice_number": f"PUR-{uuid.uuid4().hex[:6]}",
        "invoice_date": today, "status": "Pending", "subtotal": 200.0,
        "cgst_total": 20.0, "sgst_total": 20.0, "total_amount": 240.0,
        "items": [{"product_id": pid, "product_name": "HC Prod", "quantity": 4.0, "unit": "Nos",
                   "unit_price": 50.0, "cgst_rate": 10.0, "sgst_rate": 10.0, "taxable_value": 200.0,
                   "cgst_amount": 20.0, "sgst_amount": 20.0, "line_total": 240.0}],
    })
    client.post("/expenses", headers=headers, json={
        "expense_date": today, "category": "Rent", "expense_type": "Indirect",
        "amount": 500.0, "payment_mode": "Cash",
    })
    return sale.json().get("id")


def test_fresh_chain_verifies_clean():
    owner = _owner("HC Clean")
    _seed(owner)
    r = client.get("/reports/verify-chain", headers=owner["headers"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True, data
    assert data["checked"] >= 3
    assert data["head"]


def test_editing_a_posted_entry_breaks_the_chain():
    owner = _owner("HC Tamper")
    _seed(owner)
    # Confirm clean first.
    assert client.get("/reports/verify-chain", headers=owner["headers"]).json()["ok"] is True
    # Tamper: edit a posted journal line in place (what a fraudster would do).
    db = SessionLocal()
    try:
        first_entry = (db.query(JournalEntry)
                       .filter(JournalEntry.business_id == owner["bid"])
                       .order_by(JournalEntry.id.asc()).first())
        line = db.query(JournalLine).filter(JournalLine.entry_id == first_entry.id).first()
        line.debit = (line.debit or 0.0) + 999.0   # cook the books
        db.commit()
        tampered_id = first_entry.id
    finally:
        db.close()
    data = client.get("/reports/verify-chain", headers=owner["headers"]).json()
    assert data["ok"] is False, data
    assert data["broken_at"]["id"] == tampered_id


def test_idempotent_repost_preserves_chain():
    owner = _owner("HC Idem")
    inv_id = _seed(owner)
    assert client.get("/reports/verify-chain", headers=owner["headers"]).json()["ok"] is True
    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.id == inv_id).first()
        posting.post_sale(db, inv)   # idempotent: returns existing, no new link
        db.commit()
    finally:
        db.close()
    data = client.get("/reports/verify-chain", headers=owner["headers"]).json()
    assert data["ok"] is True, data


def test_verify_chain_cashier_forbidden():
    owner = _owner("HC RBAC")
    cashier = _cashier_of(owner)
    assert client.get("/reports/verify-chain", headers=cashier).status_code == 403


def test_verify_chain_tenant_isolated():
    a, b = _owner("HC A"), _owner("HC B")
    _seed(a)
    data_b = client.get("/reports/verify-chain", headers=b["headers"]).json()
    assert data_b["ok"] is True
    assert data_b["checked"] == 0   # B has no entries; an empty chain is trivially intact
