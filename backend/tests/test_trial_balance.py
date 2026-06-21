"""
tests/test_trial_balance.py
===========================
Gate-1 coverage for the derived Trial Balance (`/reports/trial-balance`). The
core invariant is that it ALWAYS foots — total Dr == total Cr — because Capital
is the balancing plug; the statement is self-checking. Also proves it is
owner-only (cashier 403) and tenant-scoped (a fresh business sees only zeros).

Self-contained: signs up its own owner A / owner B / cashier-of-A, so it does
not depend on test ordering or other suites.
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
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _seed_transactions(owner):
    """A paid sale + a paid purchase + an unpaid purchase + an expense + stock."""
    headers, bid = owner["headers"], owner["bid"]
    today = datetime.today().strftime("%Y-%m-%d")

    p = client.post("/products", headers=headers, json={
        "name": "TB Prod", "selling_price": 100.0, "cost_price": 60.0,
        "sku": f"TB-{uuid.uuid4().hex[:5]}", "track_inventory": True,
    })
    assert p.status_code == 201, p.text
    pid = p.json()["id"]

    db = SessionLocal()
    try:
        db.add(Inventory(business_id=bid, product_name="TB Prod", product_id=pid,
                         stock=10, cost_price=60.0, selling_price=100.0))
        db.commit()
    finally:
        db.close()

    # Sale — partially paid (creates cash receipt + a receivable).
    sale = client.post("/sales", headers=headers, json={
        "lines": [{"product_id": pid, "product_name": "TB Prod", "quantity": 1.0,
                   "unit_price": 100.0, "cgst_rate": 9.0, "sgst_rate": 9.0, "igst_rate": 0.0}],
        "customer": "TB Cust", "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": today, "paid_amount": 50.0, "payment_mode": "UPI",
    })
    assert sale.status_code == 200, sale.text

    # Paid purchase.
    client.post("/purchases/confirm", headers=headers, json={
        "supplier_name": "TB Vend", "invoice_number": f"PUR-{uuid.uuid4().hex[:6]}",
        "invoice_date": today, "status": "Paid", "subtotal": 100.0,
        "cgst_total": 10.0, "sgst_total": 10.0, "total_amount": 120.0,
        "items": [{"product_id": pid, "product_name": "TB Prod", "quantity": 2.0, "unit": "Nos",
                   "unit_price": 50.0, "cgst_rate": 10.0, "sgst_rate": 10.0, "taxable_value": 100.0,
                   "cgst_amount": 10.0, "sgst_amount": 10.0, "line_total": 120.0}],
    })

    # Unpaid purchase (creates a payable).
    client.post("/purchases/confirm", headers=headers, json={
        "supplier_name": "TB Vend", "invoice_number": f"PUR-{uuid.uuid4().hex[:6]}",
        "invoice_date": today, "status": "Pending", "subtotal": 200.0,
        "cgst_total": 20.0, "sgst_total": 20.0, "total_amount": 240.0,
        "items": [{"product_id": pid, "product_name": "TB Prod", "quantity": 4.0, "unit": "Nos",
                   "unit_price": 50.0, "cgst_rate": 10.0, "sgst_rate": 10.0, "taxable_value": 200.0,
                   "cgst_amount": 20.0, "sgst_amount": 20.0, "line_total": 240.0}],
    })


def test_trial_balance_empty_foots_to_zero():
    owner = _owner("TB Empty")
    r = client.get("/reports/trial-balance", headers=owner["headers"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["totals"]["total_debit"] == 0.0
    assert data["totals"]["total_credit"] == 0.0
    assert data["totals"]["balanced"] is True
    # Every standard account is present even when empty.
    names = {a["account"] for a in data["accounts"]}
    assert {"Cash & Bank", "Accounts Receivable", "Inventory", "Accounts Payable",
            "Sales", "Purchases", "Operating Expenses", "Capital / Owner's Equity"} <= names


def test_trial_balance_always_foots_after_transactions():
    owner = _owner("TB Active")
    _seed_transactions(owner)
    data = client.get("/reports/trial-balance", headers=owner["headers"]).json()
    td, tc = data["totals"]["total_debit"], data["totals"]["total_credit"]
    assert data["totals"]["balanced"] is True
    assert abs(td - tc) < 0.01            # the core invariant: Dr == Cr
    assert td > 0                          # there is real activity
    # Sales is a credit-side (income) account; a payable landed on the credit side.
    sales = next(a for a in data["accounts"] if a["account"] == "Sales")
    payables = next(a for a in data["accounts"] if a["account"] == "Accounts Payable")
    assert sales["credit"] > 0 and sales["debit"] == 0
    assert payables["credit"] > 0
    # Purchases is a debit-side account.
    purchases = next(a for a in data["accounts"] if a["account"] == "Purchases")
    assert purchases["debit"] > 0 and purchases["credit"] == 0


def test_trial_balance_cashier_forbidden():
    owner = _owner("TB Owner")
    cashier = _cashier_of(owner)
    assert client.get("/reports/trial-balance", headers=cashier).status_code == 403


def test_trial_balance_tenant_isolation():
    a, b = _owner("TB A"), _owner("TB B")
    _seed_transactions(a)
    # B is untouched — its trial balance must still be all zeros (no leak from A).
    data_b = client.get("/reports/trial-balance", headers=b["headers"]).json()
    assert data_b["totals"]["total_debit"] == 0.0
    assert data_b["totals"]["total_credit"] == 0.0
    assert data_b["totals"]["balanced"] is True
