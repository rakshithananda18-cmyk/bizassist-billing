"""
tests/test_audit_journal.py
===========================
Gate-1 coverage for the POSTED double-entry journal (the audit trail written at
transaction time) and the `/reports/audit-journal` endpoint.

Proves:
  • creating documents POSTS balanced journal entries (sale/purchase/expense),
  • posting is IDEMPOTENT per source document (re-post → no duplicate),
  • the posted journal RECONCILES with the reconstructed `/reports/general-ledger`
    account-for-account (posted == derived),
  • owner-only (cashier 403) and tenant isolation.

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
from core.models import JournalEntry
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
        "name": "AJ Prod", "selling_price": 100.0, "cost_price": 60.0,
        "sku": f"AJ-{uuid.uuid4().hex[:5]}", "track_inventory": True,
    })
    pid = p.json()["id"]
    db = SessionLocal()
    try:
        db.add(Inventory(business_id=bid, product_name="AJ Prod", product_id=pid,
                         stock=50, cost_price=60.0, selling_price=100.0))
        db.commit()
    finally:
        db.close()
    sale = client.post("/sales", headers=headers, json={
        "lines": [{"product_id": pid, "product_name": "AJ Prod", "quantity": 1.0,
                   "unit_price": 100.0, "cgst_rate": 9.0, "sgst_rate": 9.0, "igst_rate": 0.0}],
        "customer": "AJ Cust", "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": today, "paid_amount": 40.0, "payment_mode": "UPI",
    })
    assert sale.status_code == 200, sale.text
    client.post("/purchases/confirm", headers=headers, json={
        "supplier_name": "AJ Vend", "invoice_number": f"PUR-{uuid.uuid4().hex[:6]}",
        "invoice_date": today, "status": "Pending", "subtotal": 200.0,
        "cgst_total": 20.0, "sgst_total": 20.0, "total_amount": 240.0,
        "items": [{"product_id": pid, "product_name": "AJ Prod", "quantity": 4.0, "unit": "Nos",
                   "unit_price": 50.0, "cgst_rate": 10.0, "sgst_rate": 10.0, "taxable_value": 200.0,
                   "cgst_amount": 20.0, "sgst_amount": 20.0, "line_total": 240.0}],
    })
    client.post("/expenses", headers=headers, json={
        "expense_date": today, "category": "Rent", "expense_type": "Indirect",
        "amount": 500.0, "payment_mode": "Cash",
    })
    return sale.json().get("id")


def test_documents_post_balanced_entries_at_transaction_time():
    owner = _owner("AJ Biz")
    _seed(owner)
    data = client.get("/reports/audit-journal", headers=owner["headers"]).json()
    assert data["entries"], "expected POSTED journal entries after creating documents"
    assert data["totals"]["posted"] is True
    types = {e["type"] for e in data["entries"]}
    assert {"sale", "purchase", "expense"} <= types
    for e in data["entries"]:
        assert e["balanced"] is True, e
    assert data["totals"]["balanced"] is True


def test_posting_is_idempotent_per_source_document():
    owner = _owner("AJ Idem")
    inv_id = _seed(owner)
    assert inv_id
    db = SessionLocal()
    try:
        before = db.query(JournalEntry).filter(
            JournalEntry.business_id == owner["bid"],
            JournalEntry.source_type == "sale",
            JournalEntry.source_id == inv_id,
        ).count()
        assert before == 1
        inv = db.query(Invoice).filter(Invoice.id == inv_id).first()
        posting.post_sale(db, inv)   # re-post the same document
        db.commit()
        after = db.query(JournalEntry).filter(
            JournalEntry.business_id == owner["bid"],
            JournalEntry.source_type == "sale",
            JournalEntry.source_id == inv_id,
        ).count()
        assert after == 1            # no duplicate
    finally:
        db.close()


def test_posted_journal_reconciles_with_derived_general_ledger():
    owner = _owner("AJ Recon")
    _seed(owner)
    # Net (debit - credit) per account from the POSTED journal.
    aj = client.get("/reports/audit-journal", headers=owner["headers"]).json()
    posted = {}
    for e in aj["entries"]:
        for ln in e["lines"]:
            posted[ln["account"]] = round(posted.get(ln["account"], 0.0) + ln["debit"] - ln["credit"], 2)
    # Closing balance per account from the DERIVED general ledger.
    gl = client.get("/reports/general-ledger", headers=owner["headers"]).json()
    derived = {l["account"]: l["closing_balance"] for l in gl["ledgers"]}
    assert set(posted) == set(derived)
    for acct, bal in derived.items():
        assert abs(posted[acct] - bal) < 0.01, (acct, posted[acct], bal)


def test_audit_journal_cashier_forbidden():
    owner = _owner("AJ RBAC")
    cashier = _cashier_of(owner)
    assert client.get("/reports/audit-journal", headers=cashier).status_code == 403


def test_audit_journal_tenant_isolation():
    a, b = _owner("AJ A"), _owner("AJ B")
    _seed(a)
    data_b = client.get("/reports/audit-journal", headers=b["headers"]).json()
    assert data_b["entries"] == []
    assert data_b["totals"]["total_debit"] == 0.0
