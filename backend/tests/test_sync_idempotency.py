"""
tests/test_sync_idempotency.py
==============================
R7b Slice 1 — HTTP-level exactly-once replay guard (the OUTER wall).

The offline outbox tags each user-intent mutation with a stable UUID sent as the
`X-Client-Request-Id` header. A replay of that request (network retry, outbox
flush on reconnect) must return the SAME response and must NOT create a second
invoice / payment / purchase.

These tests prove the OUTER wall independently of the inner per-command wall by
letting the sale invoice number AUTO-generate (so two un-guarded POSTs would make
two distinct invoices) — only the header makes them collapse to one.

NEGATIVE-path coverage: no header → unguarded (distinct rows); different keys →
distinct rows; same key, different tenant → NOT cross-replayed (isolation).

Self-contained: own signups + product, order-independent.
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
from database.models import Product, Inventory, User, Invoice, InvoicePayment
from core.models import IdempotencyKey

client = TestClient(app)

HDR = "X-Client-Request-Id"


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _signup(name="Idem Biz", state="29"):
    uname = f"idem_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": uname, "password": "TestPass123!", "business_name": name})
    assert r.status_code == 200, r.text
    b = r.json()
    bid = b["id"]
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == bid).first()
        u.state_code = state
        p = Product(business_id=bid, name="Idem Rice", sku=f"IR{uuid.uuid4().hex[:5]}",
                    unit="Bag", hsn_sac="1006", cgst_rate=9, sgst_rate=9, igst_rate=18,
                    selling_price=100, track_inventory=True)
        db.add(p); db.flush()
        db.add(Inventory(business_id=bid, product_name="Idem Rice", product_id=p.id, stock=500))
        db.commit()
        pid = p.id
    finally:
        db.close()
    headers = {"Authorization": f"Bearer {b['token']}"}
    # Shift gatekeeper (Phase 3): the POS route (POST /invoices) requires an
    # OPEN register shift for every role — open one for this test operator.
    r = client.post("/shifts/open", headers=headers, json={"opening_cash": 0})
    assert r.status_code == 201, r.text
    return {"headers": headers, "bid": bid, "pid": pid}


def _sale_body(pid, qty=1):
    return {"place_of_supply": "29", "lines": [{"product_id": pid, "quantity": qty, "unit_price": 100}]}


def _invoice_count(bid):
    db = SessionLocal()
    try:
        return db.query(Invoice).filter(Invoice.business_id == bid).count()
    finally:
        db.close()


def _idem_count(bid):
    db = SessionLocal()
    try:
        return db.query(IdempotencyKey).filter(IdempotencyKey.business_id == bid).count()
    finally:
        db.close()


# ── OUTER WALL: same key → exactly once ───────────────────────────────────────

def test_same_key_replays_one_invoice():
    a = _signup()
    key = uuid.uuid4().hex
    h = {**a["headers"], HDR: key}

    r1 = client.post("/sales", headers=h, json=_sale_body(a["pid"]))
    r2 = client.post("/sales", headers=h, json=_sale_body(a["pid"]))

    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    # Same body replayed verbatim — same invoice id.
    assert r1.json()["id"] == r2.json()["id"]
    # Exactly ONE invoice and ONE stored key for this business.
    assert _invoice_count(a["bid"]) == 1
    assert _idem_count(a["bid"]) == 1


def test_no_header_creates_distinct_invoices():
    """Control: without the header the guard is inert — auto-numbers differ → two rows."""
    a = _signup()
    r1 = client.post("/sales", headers=a["headers"], json=_sale_body(a["pid"]))
    r2 = client.post("/sales", headers=a["headers"], json=_sale_body(a["pid"]))
    assert r1.json()["id"] != r2.json()["id"]
    assert _invoice_count(a["bid"]) == 2
    assert _idem_count(a["bid"]) == 0   # nothing stored when no key sent


def test_different_keys_create_distinct_invoices():
    a = _signup()
    h1 = {**a["headers"], HDR: uuid.uuid4().hex}
    h2 = {**a["headers"], HDR: uuid.uuid4().hex}
    r1 = client.post("/sales", headers=h1, json=_sale_body(a["pid"]))
    r2 = client.post("/sales", headers=h2, json=_sale_body(a["pid"]))
    assert r1.json()["id"] != r2.json()["id"]
    assert _invoice_count(a["bid"]) == 2
    assert _idem_count(a["bid"]) == 2


def test_key_is_tenant_scoped():
    """The SAME key string from a different business must NOT replay business A's
    response — each tenant processes independently."""
    a, b = _signup(name="Tenant A"), _signup(name="Tenant B")
    key = uuid.uuid4().hex
    ra = client.post("/sales", headers={**a["headers"], HDR: key}, json=_sale_body(a["pid"]))
    rb = client.post("/sales", headers={**b["headers"], HDR: key}, json=_sale_body(b["pid"]))
    assert ra.status_code == 200 and rb.status_code == 200
    # B got its OWN invoice, not a replay of A's.
    assert ra.json()["id"] != rb.json()["id"]
    assert _invoice_count(a["bid"]) == 1
    assert _invoice_count(b["bid"]) == 1


# ── OUTER WALL on payments ────────────────────────────────────────────────────

def test_pos_invoices_route_replays_one_invoice():
    """The POS counter saves via POST /invoices (create_sale_invoice_frontend) — the
    route the offline outbox actually flushes. Same key must collapse to one bill."""
    a = _signup()
    key = uuid.uuid4().hex
    h = {**a["headers"], HDR: key}
    body = {"items": [{"product_id": a["pid"], "product": "Idem Rice", "qty": 1, "price": 100}]}

    r1 = client.post("/invoices", headers=h, json=body)
    r2 = client.post("/invoices", headers=h, json=body)
    assert r1.status_code == 201 and r2.status_code == 201, (r1.text, r2.text)
    assert r1.json()["id"] == r2.json()["id"]
    assert _invoice_count(a["bid"]) == 1
    assert _idem_count(a["bid"]) == 1


def test_payment_replay_is_exactly_once():
    a = _signup()
    # Create an unpaid sale to pay against.
    sale = client.post("/sales", headers=a["headers"], json=_sale_body(a["pid"], qty=2))
    inv_id = sale.json()["id"]
    total = sale.json()["total_amount"]

    key = uuid.uuid4().hex
    h = {**a["headers"], HDR: key}
    p1 = client.post("/payments", headers=h, json={"invoice_id": inv_id, "amount_paid": total})
    p2 = client.post("/payments", headers=h, json={"invoice_id": inv_id, "amount_paid": total})

    assert p1.status_code == 201 and p2.status_code == 201, (p1.text, p2.text)
    assert p1.json()["id"] == p2.json()["id"]   # replayed, not a second receipt

    db = SessionLocal()
    try:
        n = db.query(InvoicePayment).filter(
            InvoicePayment.business_id == a["bid"], InvoicePayment.invoice_id == inv_id
        ).count()
    finally:
        db.close()
    assert n == 1   # one payment row, not two
