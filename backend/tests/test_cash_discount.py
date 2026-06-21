"""
tests/test_cash_discount.py
===========================
Gate-1 coverage for R4 — the POST-tax cash discount / round-off (the "Cash Dis"
line on real kirana receipts; see BENCHMARK_RECEIPT_MR_TRADERS.md).

Invariants proven:
  • cash_discount = 0 is a STRICT no-op — same grand total, same journal, NO
    "Discount Allowed" line (so every existing invoice/test is unaffected),
  • cash_discount > 0 reduces the PAYABLE but NOT the taxable value or GST,
  • the posted sale entry still FOOTS, booking the discount as "Discount Allowed",
    with Sales + GST left on the FULL value,
  • the discount is clamped to the rounded total (never makes the bill negative).

Self-contained: signs up its own owner and seeds its own product.
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
from database.models import Inventory, Invoice

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


def _product(owner):
    headers, bid = owner["headers"], owner["bid"]
    pid = client.post("/products", headers=headers, json={
        "name": "CD Prod", "selling_price": 100.0, "cost_price": 60.0,
        "sku": f"CD-{uuid.uuid4().hex[:5]}", "track_inventory": True,
    }).json()["id"]
    db = SessionLocal()
    try:
        db.add(Inventory(business_id=bid, product_name="CD Prod", product_id=pid,
                         stock=500, cost_price=60.0, selling_price=100.0))
        db.commit()
    finally:
        db.close()
    return pid


def _sale(owner, pid, *, cash_discount=0.0, paid=0.0, mark_paid=False):
    # qty1 × 100, CGST 9 + SGST 9 → taxable 100, GST 18, raw 118.
    return client.post("/sales", headers=owner["headers"], json={
        "lines": [{"product_id": pid, "product_name": "CD Prod", "quantity": 1.0,
                   "unit_price": 100.0, "cgst_rate": 9.0, "sgst_rate": 9.0, "igst_rate": 0.0}],
        "customer": "CD Cust", "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
        "paid_amount": paid, "payment_mode": "Cash", "cash_discount": cash_discount,
        "mark_paid": mark_paid,
    })


def _inv(inv_id):
    db = SessionLocal()
    try:
        return db.query(Invoice).filter(Invoice.id == inv_id).first()
    finally:
        db.close()


def _sale_entry_accounts(owner, source_id):
    """Net (debit-credit isn't needed) — return {account: {'debit':x,'credit':y}} for the posted sale entry."""
    aj = client.get("/reports/audit-journal", headers=owner["headers"]).json()
    for e in aj["entries"]:
        if e["type"] == "sale" and e["source_id"] == source_id:
            acc = {}
            for ln in e["lines"]:
                acc[ln["account"]] = {"debit": ln["debit"], "credit": ln["credit"]}
            return e, acc
    return None, {}


# ── No-op at zero ─────────────────────────────────────────────────────────────

def test_zero_cash_discount_is_noop():
    owner = _owner("CD Zero")
    pid = _product(owner)
    r = _sale(owner, pid, cash_discount=0.0, paid=118.0)
    assert r.status_code == 200, r.text
    inv = _inv(r.json()["id"])
    assert inv.total_amount == 118.0
    assert (inv.cash_discount or 0.0) == 0.0
    assert round((inv.cgst_total or 0) + (inv.sgst_total or 0), 2) == 18.0

    entry, acc = _sale_entry_accounts(owner, inv.id)
    assert entry and entry["balanced"] is True
    assert "Discount Allowed" not in acc, "no discount line when cash_discount is 0"
    assert acc["Sales"]["credit"] == 100.0
    assert acc["GST Payable"]["credit"] == 18.0


# ── Discount reduces payable, not GST; entry foots with Discount Allowed ───────

def test_cash_discount_reduces_payable_not_gst():
    owner = _owner("CD Disc")
    pid = _product(owner)
    r = _sale(owner, pid, cash_discount=3.0, paid=115.0)
    assert r.status_code == 200, r.text
    inv = _inv(r.json()["id"])

    assert inv.total_amount == 115.0, "payable = 118 − 3"
    assert inv.cash_discount == 3.0
    assert round((inv.cgst_total or 0) + (inv.sgst_total or 0), 2) == 18.0, "GST unchanged"

    entry, acc = _sale_entry_accounts(owner, inv.id)
    assert entry["balanced"] is True
    assert acc["Discount Allowed"]["debit"] == 3.0
    assert acc["Sales"]["credit"] == 100.0, "Sales stays on the FULL value"
    assert acc["GST Payable"]["credit"] == 18.0
    paid_side = acc.get("Cash & Bank", {}).get("debit", 0) + acc.get("Accounts Receivable", {}).get("debit", 0)
    assert round(paid_side, 2) == 115.0, "Cash + AR = payable"


def test_cash_discount_clamped_to_total():
    owner = _owner("CD Clamp")
    pid = _product(owner)
    r = _sale(owner, pid, cash_discount=1000.0, paid=0.0)   # absurd discount
    assert r.status_code == 200, r.text
    inv = _inv(r.json()["id"])
    assert inv.total_amount == 0.0, "payable floored at 0, never negative"
    assert inv.cash_discount == 118.0, "clamped to the rounded total"
    entry, acc = _sale_entry_accounts(owner, inv.id)
    assert entry["balanced"] is True


def test_mark_paid_settles_full_payable_as_paid():
    """'Paid & Print' (mark_paid) → status Paid with paid_amount == grand, even when
    the client sends paid_amount 0 (it shouldn't have to know the exact rounded grand)."""
    owner = _owner("CD Paid")
    pid = _product(owner)
    r = _sale(owner, pid, cash_discount=3.0, paid=0.0, mark_paid=True)
    assert r.status_code == 200, r.text
    inv = _inv(r.json()["id"])
    assert inv.status == "Paid"
    assert inv.paid_amount == inv.total_amount == 115.0   # full payable settled


def test_credit_sale_without_mark_paid_stays_unpaid():
    owner = _owner("CD Credit")
    pid = _product(owner)
    r = _sale(owner, pid, cash_discount=0.0, paid=0.0, mark_paid=False)
    assert r.status_code == 200, r.text
    inv = _inv(r.json()["id"])
    assert inv.status in ("Pending", "Unpaid")
    assert (inv.paid_amount or 0.0) == 0.0


def test_posted_chain_still_verifies_with_cash_discount():
    """A cash-discount sale must not break the tamper-evident hash chain (R3)."""
    owner = _owner("CD Chain")
    pid = _product(owner)
    assert _sale(owner, pid, cash_discount=3.0, paid=115.0).status_code == 200
    res = client.get("/reports/verify-chain", headers=owner["headers"]).json()
    assert res["ok"] is True, res
