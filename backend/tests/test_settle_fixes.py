"""Regression tests for the settle/advance fixes.

Covers three bugs found in the FIFO settlement + advance-credit flow:
  #1  a retried settle (same idempotency_key) that produced an advance used to
      re-bank the whole leftover onto Customer.credit_balance a second time.
  #3  the advance leftover was never posted to the journal at settlement, and
      the auto-application to the next invoice re-booked it as Cash.
"""
import os, sys
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from database.db import SessionLocal
from database.models import Base, Product, Invoice, InvoiceLineItem, Inventory, User, Customer
from core.models import StockLedger, InvoicePayment, JournalEntry, JournalLine
from core.billing import commands as billing
from core.accounting import posting

BID = 702500


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
    d = SessionLocal()
    Base.metadata.create_all(bind=d.get_bind())
    d.close()
    _clear()
    s = SessionLocal()
    s.add(User(id=BID, username=f"fix_{BID}", password="x", state_code="29"))
    s.add(Customer(id=BID, business_id=BID, name="Buyer"))
    s.add(Product(business_id=BID, name="W", selling_price=1.0,
                  cgst_rate=0, sgst_rate=0, igst_rate=0, track_inventory=False))
    s.commit()
    yield s
    s.close()


def _pid(db):
    return db.query(Product).filter(Product.business_id == BID).first().id


def _bill(db, amount, date):
    return billing.create_sale_invoice(
        db, business_id=BID, customer_id=BID, invoice_date=date,
        lines=[{"product_id": _pid(db), "quantity": amount, "unit_price": 1.0}])


def _credit(db):
    return round(db.query(Customer).filter(Customer.id == BID).first().credit_balance or 0.0, 2)


def _acct_balance(db, account):
    """Net debit-minus-credit posted to `account` for this business."""
    rows = (db.query(JournalLine)
            .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
            .filter(JournalEntry.business_id == BID, JournalLine.account == account)
            .all())
    return round(sum((r.debit or 0) - (r.credit or 0) for r in rows), 2)


# ── BUG #1: retry must not double-bank the advance ──────────────────────────
def test_retry_with_advance_does_not_double_bank(db):
    _bill(db, 500, "2026-01-01")
    _bill(db, 600, "2026-01-05")
    r1 = billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                      amount=1200, idempotency_key="dup-adv")
    assert r1["advance"] == 100.0 and _credit(db) == 100.0
    # Retry same key — advance must NOT be added again.
    r2 = billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                      amount=1200, idempotency_key="dup-adv")
    assert _credit(db) == 100.0, "advance double-banked on retry!"
    assert r2["advance"] == 100.0 and r2["total_applied"] == 1100.0
    # Only two per-invoice receipts ever written.
    assert db.query(InvoicePayment).filter(InvoicePayment.business_id == BID).count() == 2


# ── BUG #3: advance is booked to the journal at settlement, released on apply ─
def test_advance_receipt_and_release_journal(db):
    _bill(db, 500, "2026-01-01")
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                 amount=600, idempotency_key="jr")
    # Advance leftover (100) booked Dr Cash / Cr Customer Advances.
    adv_entries = (db.query(JournalEntry)
                   .filter(JournalEntry.business_id == BID,
                           JournalEntry.source_type == "advance_receipt").count())
    assert adv_entries == 1
    assert _acct_balance(db, posting.ACC_ADVANCE) == -100.0   # liability (credit)

    # Applying it to the next bill draws the liability back to zero (Dr Advances)
    # and does NOT re-book cash for that 100.
    cash_before = _acct_balance(db, posting.ACC_CASH)
    _bill(db, 300, "2026-02-01")   # auto-applies 100 credit
    assert _credit(db) == 0.0
    assert _acct_balance(db, posting.ACC_ADVANCE) == 0.0      # released
    assert _acct_balance(db, posting.ACC_CASH) == cash_before  # no phantom cash


# ── advance journal is idempotent on retry too ──────────────────────────────
def test_advance_journal_not_double_posted_on_retry(db):
    _bill(db, 500, "2026-01-01")
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                 amount=600, idempotency_key="jr2")
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                 amount=600, idempotency_key="jr2")
    assert (db.query(JournalEntry)
            .filter(JournalEntry.business_id == BID,
                    JournalEntry.source_type == "advance_receipt").count()) == 1
    assert _acct_balance(db, posting.ACC_ADVANCE) == -100.0
