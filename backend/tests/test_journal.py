"""
tests/test_journal.py
=====================
Gate-1 coverage for the derived double-entry General Journal
(`/reports/journal`) and General Ledger (`/reports/general-ledger`).

Core invariants (true regardless of the numbers):
  • EVERY journal entry foots — its Dr lines equal its Cr lines,
  • the journal as a whole foots (total Dr == total Cr),
  • the General Ledger nets to zero across all accounts (Σ closing == 0),
    with Sales on the credit side and Purchases on the debit side.
Plus owner-only (cashier 403) and tenant isolation.

Self-contained: signs up its own owner/cashier and seeds its own data.
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
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _seed(owner):
    headers, bid = owner["headers"], owner["bid"]
    today = datetime.today().strftime("%Y-%m-%d")
    p = client.post("/products", headers=headers, json={
        "name": "JN Prod", "selling_price": 100.0, "cost_price": 60.0,
        "sku": f"JN-{uuid.uuid4().hex[:5]}", "track_inventory": True,
    })
    pid = p.json()["id"]
    db = SessionLocal()
    try:
        db.add(Inventory(business_id=bid, product_name="JN Prod", product_id=pid,
                         stock=50, cost_price=60.0, selling_price=100.0))
        db.commit()
    finally:
        db.close()
    # Sale (partly paid → both Cash and AR legs).
    client.post("/sales", headers=headers, json={
        "lines": [{"product_id": pid, "product_name": "JN Prod", "quantity": 1.0,
                   "unit_price": 100.0, "cgst_rate": 9.0, "sgst_rate": 9.0, "igst_rate": 0.0}],
        "customer": "JN Cust", "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": today, "paid_amount": 40.0, "payment_mode": "UPI",
    })
    # Unpaid purchase (→ Accounts Payable leg).
    client.post("/purchases/confirm", headers=headers, json={
        "supplier_name": "JN Vend", "invoice_number": f"PUR-{uuid.uuid4().hex[:6]}",
        "invoice_date": today, "status": "Pending", "subtotal": 200.0,
        "cgst_total": 20.0, "sgst_total": 20.0, "total_amount": 240.0,
        "items": [{"product_id": pid, "product_name": "JN Prod", "quantity": 4.0, "unit": "Nos",
                   "unit_price": 50.0, "cgst_rate": 10.0, "sgst_rate": 10.0, "taxable_value": 200.0,
                   "cgst_amount": 20.0, "sgst_amount": 20.0, "line_total": 240.0}],
    })
    # Expense.
    client.post("/expenses", headers=headers, json={
        "expense_date": today, "category": "Rent", "expense_type": "Indirect",
        "amount": 500.0, "payment_mode": "Cash",
    })


def test_every_journal_entry_foots_and_journal_balances():
    owner = _owner("JN Biz")
    _seed(owner)
    data = client.get("/reports/journal", headers=owner["headers"]).json()
    assert data["entries"], "expected journal entries after seeding"
    for e in data["entries"]:
        assert e["balanced"] is True, e
        assert abs(e["debit_total"] - e["credit_total"]) < 0.01, e
    assert data["totals"]["balanced"] is True
    assert abs(data["totals"]["total_debit"] - data["totals"]["total_credit"]) < 0.01


def test_general_ledger_nets_to_zero_with_sales_credit_purchases_debit():
    owner = _owner("JN GL Biz")
    _seed(owner)
    data = client.get("/reports/general-ledger", headers=owner["headers"]).json()
    ledgers = {l["account"]: l for l in data["ledgers"]}
    # Double-entry ⇒ every posting nets out: Σ closing across accounts == 0.
    assert abs(sum(l["closing_balance"] for l in data["ledgers"])) < 0.01
    # Sales is a credit account; Purchases a debit account.
    assert ledgers["Sales"]["total_credit"] > 0 and ledgers["Sales"]["total_debit"] == 0
    assert ledgers["Purchases"]["total_debit"] > 0 and ledgers["Purchases"]["total_credit"] == 0
    # Running balance present on every posting.
    assert all("balance" in p for p in ledgers["Sales"]["postings"])


def test_general_ledger_account_filter():
    owner = _owner("JN Filter Biz")
    _seed(owner)
    data = client.get("/reports/general-ledger", headers=owner["headers"],
                      params={"account": "sales"}).json()
    # Filter is case-insensitive exact match; only the one account returns.
    assert len(data["ledgers"]) == 1
    assert data["ledgers"][0]["account"] == "Sales"


def test_journal_cashier_forbidden():
    owner = _owner("JN RBAC")
    cashier = _cashier_of(owner)
    assert client.get("/reports/journal", headers=cashier).status_code == 403
    assert client.get("/reports/general-ledger", headers=cashier).status_code == 403


def test_journal_tenant_isolation():
    a, b = _owner("JN A"), _owner("JN B")
    _seed(a)
    data_b = client.get("/reports/journal", headers=b["headers"]).json()
    assert data_b["entries"] == []
    assert data_b["totals"]["total_debit"] == 0.0
