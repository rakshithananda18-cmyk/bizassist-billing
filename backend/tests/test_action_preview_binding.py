"""
tests/test_action_preview_binding.py
====================================
P0 AI preview=execute binding. The confirm token now binds the PREVIEW'S
COMPUTED CONTENT (a fingerprint), not just the request params, so:

  • a confirm token from a preview executes fine while the data is unchanged
  • if the underlying data changes between preview and execute (an invoice is
    paid off, the overdue set shifts), the stale token is refused with 428 —
    the action never runs on data the user didn't see

Route-level test via TestClient (the binding lives in routes/actions.py).
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
from database.models import Invoice, Customer

client = TestClient(app)


def _signup():
    u = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={"username": u, "password": "TestPass123!",
                                     "business_name": "Action Co"})
    assert r.status_code == 200, r.text
    b = r.json()
    return {"headers": {"Authorization": f"Bearer {b['token']}"}, "bid": b["id"]}


def _seed_overdue(bid, invoice_id, amount, customer="Acme"):
    db = SessionLocal()
    try:
        if not db.query(Customer).filter(Customer.business_id == bid, Customer.name == customer).first():
            db.add(Customer(business_id=bid, name=customer, email="acme@example.com"))
        db.add(Invoice(business_id=bid, invoice_id=invoice_id, customer=customer,
                       amount=amount, status="Overdue", due_date="2024-01-01"))
        db.commit()
    finally:
        db.close()


def _pay_off(bid, invoice_id):
    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.business_id == bid,
                                       Invoice.invoice_id == invoice_id).first()
        inv.status = "Paid"
        db.commit()
    finally:
        db.close()


def test_unchanged_state_confirm_token_executes():
    u = _signup()
    _seed_overdue(u["bid"], "OV-1", 5000)

    pv = client.post("/action/preview", headers=u["headers"],
                     json={"action": "send_payment_reminders"})
    assert pv.status_code == 200, pv.text
    token = pv.json()["confirm_token"]

    # Execute immediately, data unchanged → NOT a 428 (token still valid).
    ex = client.post("/action/execute", headers=u["headers"],
                     json={"action": "send_payment_reminders", "confirm_token": token})
    assert ex.status_code != 428, ex.text


def test_state_drift_refuses_execute():
    u = _signup()
    _seed_overdue(u["bid"], "OV-1", 5000)
    _seed_overdue(u["bid"], "OV-2", 3000, customer="Beta")

    pv = client.post("/action/preview", headers=u["headers"],
                     json={"action": "send_payment_reminders"})
    assert pv.status_code == 200, pv.text
    token = pv.json()["confirm_token"]

    # Data changes AFTER the user previewed: one invoice gets paid, so the
    # overdue set (and the preview's fingerprint) no longer matches.
    _pay_off(u["bid"], "OV-1")

    ex = client.post("/action/execute", headers=u["headers"],
                     json={"action": "send_payment_reminders", "confirm_token": token})
    assert ex.status_code == 428, ex.text
    assert "confirm" in ex.json()["detail"].lower()
