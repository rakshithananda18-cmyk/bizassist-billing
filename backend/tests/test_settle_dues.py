"""
tests/test_settle_dues.py
=========================
FIFO customer dues settlement — the "customer pays a lump sum, clear oldest
bills first, carry the leftover as an advance" flow.

The headline scenario (owner's example):
  two pending bills of 500 and 600; customer pays 1000
    → bill#1 (500) fully paid, bill#2 partially paid 500 leaving 100 pending.
  paying 1200 instead
    → both cleared, 100 carried as advance (customer outstanding goes negative).

Pure-DB unit test (SQLite), mirroring tests/test_billing.py.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Product, Invoice, InvoiceLineItem, Inventory, User, Customer
from core.models import StockLedger, InvoicePayment, JournalEntry, JournalLine
from core.billing import commands as billing

BID = 701000


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        ids = [r.id for r in db.query(Invoice.id).filter(Invoice.business_id == BID).all()]
        if ids:
            db.query(InvoiceLineItem).filter(InvoiceLineItem.invoice_id.in_(ids)).delete(synchronize_session=False)
        db.query(Invoice).filter(Invoice.business_id == BID).delete()
        db.query(InvoicePayment).filter(InvoicePayment.business_id == BID).delete()
        ent = [r.id for r in db.query(JournalEntry.id).filter(JournalEntry.business_id == BID).all()]
        if ent:
            db.query(JournalLine).filter(JournalLine.entry_id.in_(ent)).delete(synchronize_session=False)
        db.query(JournalEntry).filter(JournalEntry.business_id == BID).delete()
        db.query(StockLedger).filter(StockLedger.business_id == BID).delete()
        db.query(Inventory).filter(Inventory.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.query(Customer).filter(Customer.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def db():
    _ensure_schema()
    _clear()
    s = SessionLocal()
    s.add(User(id=BID, username=f"settle_{BID}", password="x", state_code="29"))
    s.add(Customer(id=BID, business_id=BID, name="Regular Buyer"))
    s.add(Product(business_id=BID, name="Widget", selling_price=1.0,
                  cgst_rate=0, sgst_rate=0, igst_rate=0, track_inventory=False))
    s.commit()
    yield s
    s.close()


def _pid(db):
    return db.query(Product).filter(Product.business_id == BID).first().id


def _bill(db, amount, date):
    """A pending invoice for the customer, total == amount (no tax)."""
    return billing.create_sale_invoice(
        db, business_id=BID, customer_id=BID,
        invoice_date=date,
        lines=[{"product_id": _pid(db), "quantity": amount, "unit_price": 1.0}],
    )


def _outstanding(db, inv_id):
    inv = db.query(Invoice).filter(Invoice.id == inv_id).first()
    return round((inv.total_amount or 0) - (inv.paid_amount or 0), 2), inv.status


def test_fifo_partial_clears_oldest_first(db):
    b1 = _bill(db, 500, "2026-01-01")
    b2 = _bill(db, 600, "2026-01-05")

    res = billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                       amount=1000, idempotency_key="s1")
    assert res["total_applied"] == 1000.0
    assert res["advance"] == 0.0

    o1, s1 = _outstanding(db, b1.id)
    o2, s2 = _outstanding(db, b2.id)
    assert (o1, s1) == (0.0, "Paid")            # oldest fully cleared
    assert (o2, s2) == (100.0, "Partial")       # next partially paid, 100 left


def _credit(db):
    return round(db.query(Customer).filter(Customer.id == BID).first().credit_balance or 0.0, 2)


def test_overpayment_banks_advance_as_credit(db):
    b1 = _bill(db, 500, "2026-01-01")
    b2 = _bill(db, 600, "2026-01-05")

    res = billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                       amount=1200, idempotency_key="s2")
    assert res["total_applied"] == 1100.0
    assert res["advance"] == 100.0
    assert res["credit_balance"] == 100.0       # leftover banked, not lost

    # Both bills cleared EXACTLY — no invoice is overpaid.
    assert _outstanding(db, b1.id) == (0.0, "Paid")
    assert _outstanding(db, b2.id) == (0.0, "Paid")
    assert _credit(db) == 100.0


def test_advance_auto_applies_to_next_invoice(db):
    # Customer has ₹100 banked credit …
    b1 = _bill(db, 500, "2026-01-01")
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID, amount=600, idempotency_key="s3")
    assert _credit(db) == 100.0

    # … next ₹300 bill auto-applies it: 100 paid, 200 outstanding, credit drained.
    b2 = _bill(db, 300, "2026-02-01")
    o2, s2 = _outstanding(db, b2.id)
    assert (o2, s2) == (200.0, "Partial")
    assert _credit(db) == 0.0


def test_advance_larger_than_next_bill_leaves_remainder(db):
    b1 = _bill(db, 500, "2026-01-01")
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID, amount=1000, idempotency_key="s4")
    assert _credit(db) == 500.0                 # 500 banked

    b2 = _bill(db, 200, "2026-02-01")           # smaller than credit
    assert _outstanding(db, b2.id) == (0.0, "Paid")
    assert _credit(db) == 300.0                 # 200 used, 300 still banked


def test_settle_is_idempotent_no_double_pay(db):
    b1 = _bill(db, 500, "2026-01-01")
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID, amount=500, idempotency_key="dup")
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID, amount=500, idempotency_key="dup")
    # Same key → the per-invoice payment is not double-applied.
    total_paid = (db.query(InvoicePayment)
                  .filter(InvoicePayment.business_id == BID).count())
    assert total_paid == 1
    o1, s1 = _outstanding(db, b1.id)
    assert (o1, s1) == (0.0, "Paid")


def test_zero_amount_rejected(db):
    _bill(db, 500, "2026-01-01")
    with pytest.raises(ValueError, match="greater than 0"):
        billing.settle_customer_dues(db, business_id=BID, customer_id=BID, amount=0)
    db.rollback()
