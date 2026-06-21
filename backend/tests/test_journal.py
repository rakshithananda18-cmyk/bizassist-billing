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


# ── R2b: opening-balance carry-forward in the General Ledger ──────────────────

def _cf_product(owner):
    p = client.post("/products", headers=owner["headers"], json={
        "name": "CF Prod", "selling_price": 100.0, "cost_price": 60.0,
        "sku": f"CF-{uuid.uuid4().hex[:5]}", "track_inventory": False,
    })
    assert p.status_code in (200, 201), p.text
    return p.json()["id"]


def _dated_credit_sale(owner, pid, date):
    r = client.post("/sales", headers=owner["headers"], json={
        "lines": [{"product_id": pid, "product_name": "CF Prod", "quantity": 1.0,
                   "unit_price": 100.0, "cgst_rate": 9.0, "sgst_rate": 9.0, "igst_rate": 0.0}],
        "customer": "CF Cust", "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": date, "paid_amount": 0.0, "payment_mode": "Credit",
    })
    assert r.status_code == 200, r.text


def _gl(owner, **params):
    data = client.get("/reports/general-ledger", headers=owner["headers"], params=params).json()
    return {l["account"]: l for l in data["ledgers"]}


def test_general_ledger_carries_opening_forward():
    """A windowed GL must open at the prior period's closing balance (R2b), so a
    windowed closing equals the cumulative as-of-to closing — the report no longer
    silently drops everything before `from`."""
    owner = _owner("JN CF")
    pid = _cf_product(owner)
    _dated_credit_sale(owner, pid, "2025-12-20")   # prior period
    _dated_credit_sale(owner, pid, "2026-01-15")   # inside the window

    win = _gl(owner, **{"from": "2026-01-01", "to": "2026-01-31"})
    assert "opening_balance" in win["Sales"]

    # opening(window) == closing of all activity strictly before the window
    asof_dec = _gl(owner, **{"to": "2025-12-31"})
    assert abs(win["Sales"]["opening_balance"] - asof_dec["Sales"]["closing_balance"]) < 0.01

    # closing(window) == cumulative closing as-of the window's end (no `from`)
    asof_jan = _gl(owner, **{"to": "2026-01-31"})
    assert abs(win["Sales"]["closing_balance"] - asof_jan["Sales"]["closing_balance"]) < 0.01

    # opening + in-window movement == closing (internal consistency)
    movement = win["Sales"]["total_debit"] - win["Sales"]["total_credit"]
    assert abs(win["Sales"]["opening_balance"] + movement - win["Sales"]["closing_balance"]) < 0.01
    # Prior Dec sale is NOT a posting inside the window — it lives in the opening only.
    assert len(win["Sales"]["postings"]) == 1


def test_general_ledger_boundary_day_counted_once():
    """A transaction dated exactly on `from_date` belongs to the window, never the
    opening — counted once, not double."""
    owner = _owner("JN CF2")
    pid = _cf_product(owner)
    _dated_credit_sale(owner, pid, "2026-01-01")   # exactly on the boundary

    win = _gl(owner, **{"from": "2026-01-01", "to": "2026-01-31"})
    assert win["Sales"]["opening_balance"] == 0.0          # nothing strictly before
    assert len(win["Sales"]["postings"]) == 1              # the boundary sale is in-window


def test_general_ledger_opening_only_account_appears():
    """An account with a carried-forward balance but no in-window activity must still
    show up (with its opening == closing and no postings)."""
    owner = _owner("JN CF3")
    pid = _cf_product(owner)
    _dated_credit_sale(owner, pid, "2025-12-10")   # only prior-period activity

    win = _gl(owner, **{"from": "2026-01-01", "to": "2026-01-31"})
    assert "Sales" in win                                   # carried forward, still listed
    assert win["Sales"]["postings"] == []
    assert abs(win["Sales"]["opening_balance"] - win["Sales"]["closing_balance"]) < 0.01
    assert win["Sales"]["opening_balance"] != 0.0
