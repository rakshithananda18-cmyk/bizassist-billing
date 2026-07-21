"""
tests/test_financial_invariants.py
==================================
P0 DB financial invariants:
  • record_payment rejects a receipt that would push cumulative payments past
    the invoice total (data-entry typo guard); allow_overpayment opts out
  • journal foots globally after a sale + payment (SUM debits == SUM credits)
  • run_integrity_check reports ok on healthy books and detects a broken hash
    chain after a tampered journal line

Pure-DB unit test (SQLite), mirroring tests/test_billing.py conventions.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Product, Invoice, InvoiceLineItem, Inventory, User
from core.models import StockLedger, InvoicePayment, JournalEntry, JournalLine
from core.billing import commands as billing
from core.accounting import integrity

BID = 700900


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
        ent_ids = [r.id for r in db.query(JournalEntry.id).filter(JournalEntry.business_id == BID).all()]
        if ent_ids:
            db.query(JournalLine).filter(JournalLine.entry_id.in_(ent_ids)).delete(synchronize_session=False)
        db.query(JournalEntry).filter(JournalEntry.business_id == BID).delete()
        db.query(StockLedger).filter(StockLedger.business_id == BID).delete()
        db.query(Inventory).filter(Inventory.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def db():
    _ensure_schema()
    _clear()
    s = SessionLocal()
    s.add(User(id=BID, username=f"inv_biz_{BID}", password="x", state_code="29"))
    s.add(Product(business_id=BID, name="Widget", selling_price=100.0,
                  cgst_rate=0, sgst_rate=0, igst_rate=0, track_inventory=True))
    s.commit()
    yield s
    s.close()


def _pid(db):
    return db.query(Product).filter(Product.business_id == BID).first().id


def _invoice(db, total_price):
    return billing.create_sale_invoice(
        db, business_id=BID,
        lines=[{"product_id": _pid(db), "quantity": 1, "unit_price": total_price}],
    )


# ── overpayment guard ────────────────────────────────────────────────────────

def test_payment_within_balance_is_allowed(db):
    inv = _invoice(db, 100.0)
    pay = billing.record_payment(db, business_id=BID, invoice_id=inv.id, amount_paid=100.0,
                                 idempotency_key="k1")
    assert pay.id is not None


def test_gross_overpayment_is_rejected(db):
    inv = _invoice(db, 100.0)
    with pytest.raises(ValueError, match="exceeds the outstanding balance"):
        billing.record_payment(db, business_id=BID, invoice_id=inv.id, amount_paid=1000.0,
                               idempotency_key="k2")
    db.rollback()


def test_cumulative_overpayment_across_partials_is_rejected(db):
    inv = _invoice(db, 100.0)
    billing.record_payment(db, business_id=BID, invoice_id=inv.id, amount_paid=80.0, idempotency_key="k3")
    with pytest.raises(ValueError, match="exceeds the outstanding balance"):
        billing.record_payment(db, business_id=BID, invoice_id=inv.id, amount_paid=80.0, idempotency_key="k4")
    db.rollback()


def test_overpayment_allowed_with_flag(db):
    inv = _invoice(db, 100.0)
    pay = billing.record_payment(db, business_id=BID, invoice_id=inv.id, amount_paid=500.0,
                                 allow_overpayment=True, idempotency_key="k5")
    assert pay.id is not None


# ── integrity: journal foots + hash chain ────────────────────────────────────

def test_integrity_ok_after_sale_and_payment(db):
    inv = _invoice(db, 100.0)
    billing.record_payment(db, business_id=BID, invoice_id=inv.id, amount_paid=100.0, idempotency_key="k6")
    report = integrity.run_integrity_check(db, BID)
    assert report["ok"] is True
    assert report["journal_balance"]["ok"] is True
    assert report["journal_balance"]["drift"] == 0.0
    assert report["hash_chain"]["ok"] is True


def test_integrity_detects_tampered_journal_line(db):
    _invoice(db, 100.0)
    # Tamper: bump a debit without touching the stored hash → chain must break.
    line = db.query(JournalLine).join(
        JournalEntry, JournalLine.entry_id == JournalEntry.id
    ).filter(JournalEntry.business_id == BID, JournalLine.debit > 0).first()
    line.debit = float(line.debit) + 50.0
    db.commit()
    report = integrity.run_integrity_check(db, BID)
    assert report["ok"] is False
    # either the chain hash mismatches or the journal no longer foots (or both)
    assert (report["hash_chain"]["ok"] is False) or (report["journal_balance"]["ok"] is False)
