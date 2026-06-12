"""
tests/test_actions.py  — Phase 3 (gated actions)
================================================
Reminders actually send (where an email exists + SMTP is configured), never
double-send (idempotent), and degrade honestly when not configured. mark_invoice_paid
changes real state with audit and is a no-op when already paid.
"""
import os
import sys
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
import services.actions as actions
from database.db import SessionLocal
from database.models import Base, Invoice, Customer, User, ActionLog

BID = 660011


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        for M in (Invoice, Customer, ActionLog):
            db.query(M).filter(M.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()


def _seed():
    db = SessionLocal()
    try:
        db.add(User(id=BID, username=f"biz{BID}", password="x", business_name="Test Biz"))
        db.add(Customer(business_id=BID, name="Acme", email="acme@example.com"))
        db.add(Customer(business_id=BID, name="NoMail"))  # no email
        db.add_all([
            Invoice(business_id=BID, invoice_id="A-1", customer="Acme",   amount=5000, status="Overdue", due_date="2024-01-01"),
            Invoice(business_id=BID, invoice_id="N-1", customer="NoMail", amount=3000, status="Overdue", due_date="2024-01-01"),
            Invoice(business_id=BID, invoice_id="TST-INV-1", customer="Acme", amount=900, status="Overdue", due_date="2024-02-01"),
        ])
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    _seed()
    yield
    _clear()


# ── send_payment_reminders ──────────────────────────────────────────

@patch("services.actions.email_configured", return_value=True)
def test_preview_marks_channels_by_contact(_cfg):
    pv = actions.preview("send_payment_reminders", BID)
    ch = {i["customer"]: i["channel"] for i in pv["items"]}
    assert ch["Acme"] == "email"        # has email + SMTP on
    assert ch["NoMail"] == "no_contact"  # no email on file


@patch("services.actions.email_configured", return_value=True)
def test_preview_honours_selected_customers(_cfg):
    # picking one customer must scope the reminder to just that one (the
    # 'Send to 1 selected' bug: selection was ignored and all 20 were logged).
    pv = actions.preview("send_payment_reminders", BID, {"customers": ["Acme"]})
    assert [i["customer"] for i in pv["items"]] == ["Acme"]
    assert pv["count"] == 1


@patch("services.actions.email_configured", return_value=False)
def test_preview_flags_unconfigured_smtp(_cfg):
    pv = actions.preview("send_payment_reminders", BID)
    ch = {i["customer"]: i["channel"] for i in pv["items"]}
    assert ch["Acme"] == "email_unconfigured"
    assert "not configured" in pv["warning"].lower() or "drafted" in pv["warning"].lower()


@patch("services.actions.email_configured", return_value=True)
@patch("services.actions.send_email", return_value=True)
def test_execute_sends_and_is_idempotent(mock_send, _cfg):
    r1 = actions.execute("send_payment_reminders", BID)
    assert r1["ok"] and "Emailed 1" in r1["markdown"]      # Acme emailed once
    assert mock_send.call_count == 1
    # second run same day → Acme skipped (already reminded), no new send
    r2 = actions.execute("send_payment_reminders", BID)
    assert mock_send.call_count == 1                        # NOT called again
    assert "Skipped 1" in r2["markdown"]


# ── mark_invoice_paid ───────────────────────────────────────────────

def test_mark_paid_preview_and_execute():
    pv = actions.preview("mark_invoice_paid", BID, {"query": "mark TST-INV-1 as paid"})
    assert pv["executable"] is True
    assert pv["params"]["invoice_id"] == "TST-INV-1"

    res = actions.execute("mark_invoice_paid", BID, {"invoice_id": "TST-INV-1"})
    assert res["ok"] and res["executed"] == 1

    db = SessionLocal()
    try:
        inv = db.query(Invoice).filter(Invoice.business_id == BID,
                                       Invoice.invoice_id == "TST-INV-1").first()
        assert inv.status == "Paid"
    finally:
        db.close()


def test_mark_paid_is_noop_when_already_paid():
    actions.execute("mark_invoice_paid", BID, {"invoice_id": "TST-INV-1"})
    again = actions.execute("mark_invoice_paid", BID, {"invoice_id": "TST-INV-1"})
    assert again["ok"] and again["executed"] == 0
    assert "already" in again["markdown"].lower()


def test_mark_paid_unknown_invoice():
    pv = actions.preview("mark_invoice_paid", BID, {"query": "mark ZZ-INV-9999 paid"})
    assert pv["executable"] is False