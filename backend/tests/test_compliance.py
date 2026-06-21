"""
tests/test_compliance.py
========================
Gate-1 coverage for the GST compliance endpoints (e-invoice INV-01 + e-way bill
+ IRN persistence). Focus: owner-only RBAC (cashier 403), tenant isolation
(cross-business 404), the ₹50,000 e-way threshold, the e-invoice applicability
flag, and idempotent/​conflict-safe IRN recording.

The JSON-shape + tax math is covered by the pure-unit `test_einvoice.py`; here we
exercise the wired routes end-to-end. Self-contained: signs up its own owner/​
cashier and seeds its own sale.
"""
import os
import sys
import json
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
from database.models import User
from core.models import BusinessSettings

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


def _product(owner, price):
    p = client.post("/products", headers=owner["headers"], json={
        "name": "CMP Prod", "selling_price": price, "cost_price": price * 0.7,
        "sku": f"CMP-{uuid.uuid4().hex[:5]}", "track_inventory": False,
    })
    assert p.status_code in (200, 201), p.text
    return p.json()["id"]


def _sale(owner, pid, price, qty=1.0):
    r = client.post("/sales", headers=owner["headers"], json={
        "lines": [{"product_id": pid, "product_name": "CMP Prod", "quantity": qty,
                   "unit_price": price, "cgst_rate": 0.0, "sgst_rate": 0.0, "igst_rate": 0.0}],
        "customer": "CMP Cust", "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
        "invoice_date": datetime.today().strftime("%Y-%m-%d"),
        "paid_amount": 0.0, "payment_mode": "Credit",
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _set_einvoice_flag(bid, enabled):
    db = SessionLocal()
    try:
        row = db.query(BusinessSettings).filter(BusinessSettings.business_id == bid).first()
        if not row:
            row = BusinessSettings(business_id=bid, template_key="general")
            db.add(row)
        row.overrides = json.dumps({"e_invoice_enabled": enabled})
        db.commit()
    finally:
        db.close()


# ── e-invoice GET ─────────────────────────────────────────────────────────────

def test_einvoice_owner_gets_payload_not_applicable_by_default():
    owner = _owner("CMP A")
    sid = _sale(owner, _product(owner, 100.0), 100.0)
    r = client.get(f"/compliance/e-invoice/{sid}", headers=owner["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    for sec in ("TranDtls", "DocDtls", "SellerDtls", "BuyerDtls", "ItemList", "ValDtls"):
        assert sec in body["payload"]
    assert body["applicable"] is False          # flag off by default
    assert body["already_generated"] is False
    assert body["ready"] is False               # not applicable ⇒ not ready


def test_einvoice_applicable_when_flag_set():
    owner = _owner("CMP Flag")
    sid = _sale(owner, _product(owner, 100.0), 100.0)
    _set_einvoice_flag(owner["bid"], True)
    body = client.get(f"/compliance/e-invoice/{sid}", headers=owner["headers"]).json()
    assert body["applicable"] is True


# ── RBAC + tenant isolation ───────────────────────────────────────────────────

def test_compliance_cashier_forbidden():
    owner = _owner("CMP RBAC")
    sid = _sale(owner, _product(owner, 100.0), 100.0)
    cashier = _cashier_of(owner)
    assert client.get(f"/compliance/e-invoice/{sid}", headers=cashier).status_code == 403
    assert client.post(f"/compliance/e-way-bill/{sid}", headers=cashier, json={}).status_code == 403
    assert client.post(f"/compliance/e-invoice/{sid}/record", headers=cashier,
                       json={"irn": "X" * 64}).status_code == 403


def test_compliance_cross_tenant_404():
    a, b = _owner("CMP T-A"), _owner("CMP T-B")
    sid = _sale(a, _product(a, 100.0), 100.0)
    # Owner B must not reach owner A's invoice.
    assert client.get(f"/compliance/e-invoice/{sid}", headers=b["headers"]).status_code == 404
    assert client.post(f"/compliance/e-way-bill/{sid}", headers=b["headers"], json={}).status_code == 404
    assert client.post(f"/compliance/e-invoice/{sid}/record", headers=b["headers"],
                       json={"irn": "Y" * 64}).status_code == 404


# ── e-way threshold ───────────────────────────────────────────────────────────

def test_eway_required_above_50k():
    owner = _owner("CMP EWB")
    big = _sale(owner, _product(owner, 60000.0), 60000.0)        # > ₹50,000
    small = _sale(owner, _product(owner, 100.0), 100.0)          # well under
    rb = client.post(f"/compliance/e-way-bill/{big}", headers=owner["headers"], json={}).json()
    rs = client.post(f"/compliance/e-way-bill/{small}", headers=owner["headers"], json={}).json()
    assert rb["required"] is True and rb["threshold"] == 50000.0
    assert rs["required"] is False


# ── IRN persistence ───────────────────────────────────────────────────────────

def test_record_irn_idempotent_then_conflict():
    owner = _owner("CMP IRN")
    sid = _sale(owner, _product(owner, 100.0), 100.0)
    irn = "A" * 64
    r1 = client.post(f"/compliance/e-invoice/{sid}/record", headers=owner["headers"],
                     json={"irn": irn, "ack_no": "112233"})
    assert r1.status_code == 200 and r1.json()["irn"] == irn
    # Re-recording the SAME IRN is a no-op success (idempotent).
    r2 = client.post(f"/compliance/e-invoice/{sid}/record", headers=owner["headers"], json={"irn": irn})
    assert r2.status_code == 200
    # A DIFFERENT IRN on an already-stamped invoice is rejected.
    r3 = client.post(f"/compliance/e-invoice/{sid}/record", headers=owner["headers"], json={"irn": "B" * 64})
    assert r3.status_code == 422
    # After recording, the GET reflects already_generated and is no longer "ready".
    body = client.get(f"/compliance/e-invoice/{sid}", headers=owner["headers"]).json()
    assert body["irn"] == irn and body["already_generated"] is True and body["ready"] is False
