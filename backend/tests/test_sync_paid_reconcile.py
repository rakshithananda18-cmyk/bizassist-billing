"""Regression: sync must not let a stale client "un-pay" a settled invoice.

Invoice.paid_amount/status are a PROJECTION of the append-only invoice_payments
ledger. A stale device could push paid_amount=0 / status=Pending and clobber an
invoice that was settled elsewhere (the "shows Pending but already paid" bug).
The sync push now re-derives these from the server's own payment rows.
"""
import os, sys
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from database.db import SessionLocal
from database.models import Base, User, Customer, Invoice
from core.models import InvoicePayment
from routes.sync import _reconcile_invoice_paid_state, _reconcile_parent_invoice_of_payment

BID = 705300


def _clear():
    db = SessionLocal()
    try:
        db.query(InvoicePayment).filter(InvoicePayment.business_id == BID).delete()
        db.query(Invoice).filter(Invoice.business_id == BID).delete()
        db.query(Customer).filter(Customer.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def db():
    d = SessionLocal()
    Base.metadata.create_all(bind=d.get_bind())
    d.close()
    _clear()
    s = SessionLocal()
    s.add(User(id=BID, username=f"sync_{BID}", password="x", state_code="29"))
    s.add(Customer(id=BID, business_id=BID, name="Buyer"))
    s.commit()
    yield s
    s.close()


def _invoice(db, total=424.0, paid=424.0, status="Paid"):
    inv = Invoice(business_id=BID, invoice_id="LCL-OW-0016", customer="Buyer",
                  customer_id=BID, total_amount=total, paid_amount=paid,
                  status=status, invoice_date="2026-07-10")
    db.add(inv); db.flush()
    return inv


def _pay(db, inv, amount):
    p = InvoicePayment(business_id=BID, invoice_id=inv.id, customer_id=BID,
                       amount_paid=amount, payment_mode="Cash", note="Settlement (FIFO)")
    db.add(p); db.flush()
    return p


# ── the headline bug: a stale client push tried to zero a settled invoice ────
def test_reconcile_restores_paid_from_ledger(db):
    inv = _invoice(db, total=424, paid=424, status="Paid")
    _pay(db, inv, 321)
    _pay(db, inv, 103)                 # ledger = 424
    # Simulate the stale-client overwrite that sync would have applied:
    inv.paid_amount = 0.0
    inv.status = "Pending"
    db.flush()

    _reconcile_invoice_paid_state(db, inv)
    assert inv.paid_amount == 424.0
    assert inv.status == "Paid"


def test_reconcile_partial(db):
    inv = _invoice(db, total=424, paid=0, status="Pending")
    _pay(db, inv, 321)                 # ledger = 321 < 424 → Partial
    _reconcile_invoice_paid_state(db, inv)
    assert inv.paid_amount == 321.0
    assert inv.status == "Partial"


# ── legacy invoices with NO ledger rows must be left untouched ───────────────
def test_reconcile_leaves_legacy_paid_invoice_untouched(db):
    inv = _invoice(db, total=500, paid=500, status="Paid")   # no payment rows
    _reconcile_invoice_paid_state(db, inv)
    assert inv.paid_amount == 500.0    # NOT reset to 0
    assert inv.status == "Paid"


# ── reconcile via a synced payment row reaches the parent invoice ────────────
def test_reconcile_from_payment_sync(db):
    inv = _invoice(db, total=424, paid=0, status="Pending")
    p = _pay(db, inv, 424)
    _reconcile_parent_invoice_of_payment(db, p)
    db.flush()   # the sync push flushes after reconcile; persist then verify
    assert inv.paid_amount == 424.0 and inv.status == "Paid"
