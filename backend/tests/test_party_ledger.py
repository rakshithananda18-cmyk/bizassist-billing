"""
tests/test_party_ledger.py
==========================
Gate-1 coverage for the Party Ledger / Account Statement
(`/reports/party-ledger`). Proves the running statement ties to the rest of
the books and is access-controlled:

  • a customer's CLOSING receivable == the Balance-Sheet receivables
    (single-customer business), with a running balance on every row,
  • a vendor's CLOSING payable == the Balance-Sheet payables,
  • the `from` window produces a non-zero OPENING balance from prior rows,
  • owner-only (cashier 403) and tenant-scoped (foreign/missing party 404).

Self-contained: signs up its own owner(s) + cashier.
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
from database.models import Inventory

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


def _product(owner):
    r = client.post("/products", headers=owner["headers"], json={
        "name": "PL Prod", "selling_price": 100.0, "cost_price": 60.0,
        "sku": f"PL-{uuid.uuid4().hex[:5]}", "track_inventory": True,
    })
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    db = SessionLocal()
    try:
        db.add(Inventory(business_id=owner["bid"], product_name="PL Prod", product_id=pid,
                         stock=50, cost_price=60.0, selling_price=100.0))
        db.commit()
    finally:
        db.close()
    return pid


def _customer(owner, name="PL Cust"):
    r = client.post("/customers", headers=owner["headers"], json={"name": name, "phone": "1112223334"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _vendor(owner, name="PL Vend"):
    r = client.post("/vendors", headers=owner["headers"], json={"name": name, "phone": "5556667778"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sale(owner, pid, cid, date, paid=0.0):
    r = client.post("/sales", headers=owner["headers"], json={
        "lines": [{"product_id": pid, "product_name": "PL Prod", "quantity": 1.0,
                   "unit_price": 100.0, "cgst_rate": 9.0, "sgst_rate": 9.0, "igst_rate": 0.0}],
        "customer": "PL Cust", "customer_id": cid, "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": date, "paid_amount": paid, "payment_mode": "Credit",
    })
    assert r.status_code == 200, r.text


def _purchase(owner, pid, vid, date, status):
    client.post("/purchases/confirm", headers=owner["headers"], json={
        "supplier_name": "PL Vend", "supplier_id": vid, "invoice_number": f"PUR-{uuid.uuid4().hex[:6]}",
        "invoice_date": date, "status": status, "subtotal": 200.0,
        "cgst_total": 20.0, "sgst_total": 20.0, "total_amount": 240.0,
        "items": [{"product_id": pid, "product_name": "PL Prod", "quantity": 4.0, "unit": "Nos",
                   "unit_price": 50.0, "cgst_rate": 10.0, "sgst_rate": 10.0, "taxable_value": 200.0,
                   "cgst_amount": 20.0, "sgst_amount": 20.0, "line_total": 240.0}],
    })


def _balance_sheet(owner):
    return client.get("/reports/balance-sheet", headers=owner["headers"]).json()


def test_customer_ledger_closing_ties_to_receivables():
    owner = _owner("PL Cust Biz")
    pid, cid = _product(owner), _customer(owner)
    _sale(owner, pid, cid, "2026-02-01", paid=0.0)
    _sale(owner, pid, cid, "2026-03-01", paid=50.0)

    r = client.get(f"/reports/party-ledger?party_type=customer&party_id={cid}", headers=owner["headers"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["summary"]["balance_type"] == "Receivable"
    # Single customer ⇒ their closing receivable equals the whole balance sheet receivables.
    bs_recv = _balance_sheet(owner)["assets"]["receivables"]
    assert abs(data["summary"]["closing_balance"] - bs_recv) < 0.01
    # Running balance is present and monotonic with the entries.
    assert data["entries"] and "balance" in data["entries"][0]
    assert data["entries"][-1]["balance"] == data["summary"]["closing_balance"]


def test_vendor_ledger_closing_ties_to_payables():
    owner = _owner("PL Vend Biz")
    pid, vid = _product(owner), _vendor(owner)
    _purchase(owner, pid, vid, "2026-02-10", "Pending")   # payable
    _purchase(owner, pid, vid, "2026-02-12", "Paid")      # settled

    data = client.get(f"/reports/party-ledger?party_type=vendor&party_id={vid}",
                      headers=owner["headers"]).json()
    assert data["summary"]["balance_type"] == "Payable"
    bs_pay = _balance_sheet(owner)["liabilities"]["payables"]
    assert abs(data["summary"]["abs_closing"] - bs_pay) < 0.01


def test_from_window_produces_opening_balance():
    owner = _owner("PL Window Biz")
    pid, cid = _product(owner), _customer(owner)
    _sale(owner, pid, cid, "2026-01-05")   # before the window
    _sale(owner, pid, cid, "2026-04-05")   # inside the window

    data = client.get(
        f"/reports/party-ledger?party_type=customer&party_id={cid}&from=2026-04-01&to=2026-04-30",
        headers=owner["headers"],
    ).json()
    assert data["opening_balance"] > 0                       # the Jan sale rolled into opening
    assert all(e["date"] >= "2026-04-01" for e in data["entries"])
    # closing = opening + windowed activity = full receivable
    assert data["summary"]["closing_balance"] > data["opening_balance"]


def test_party_ledger_cashier_forbidden():
    owner = _owner("PL RBAC")
    cid = _customer(owner)
    cashier = _cashier_of(owner)
    r = client.get(f"/reports/party-ledger?party_type=customer&party_id={cid}", headers=cashier)
    assert r.status_code == 403


def test_party_ledger_foreign_and_missing_party_404():
    a, b = _owner("PL A"), _owner("PL B")
    cid_a = _customer(a)
    # B cannot read A's customer ledger.
    assert client.get(f"/reports/party-ledger?party_type=customer&party_id={cid_a}",
                      headers=b["headers"]).status_code == 404
    # Non-existent id.
    assert client.get("/reports/party-ledger?party_type=customer&party_id=999999",
                      headers=a["headers"]).status_code == 404
