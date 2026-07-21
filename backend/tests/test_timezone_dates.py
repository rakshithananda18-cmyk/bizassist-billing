"""Timezone correctness for money-date stamping.

Timestamps are stored naive-UTC, but the *business calendar date* on receipts,
invoices, and journal entries must be the merchant's local (IST) date — not the
server process's local date. On a UTC server a receipt taken at 01:00 IST would
otherwise be stamped the previous day. These tests pin the money paths to
`services.dates.biz_today_str()` and prove that helper is server-TZ-independent.
"""
import os, sys, time
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from database.db import SessionLocal
from database.models import Base, Product, Invoice, InvoiceLineItem, Inventory, User, Customer
from core.models import StockLedger, InvoicePayment, JournalEntry, JournalLine
from core.billing import commands as billing
from services.dates import biz_today_str, biz_now

BID = 704200


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
    s.add(User(id=BID, username=f"tz_{BID}", password="x", state_code="29"))
    s.add(Customer(id=BID, business_id=BID, name="Buyer"))
    s.add(Product(business_id=BID, name="W", selling_price=1.0,
                  cgst_rate=0, sgst_rate=0, igst_rate=0, track_inventory=False))
    s.commit()
    yield s
    s.close()


def _pid(db):
    return db.query(Product).filter(Product.business_id == BID).first().id


# ── the helper is independent of the server process timezone ────────────────
def test_biz_today_is_server_tz_independent():
    ist_date = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    for tz in ("UTC", "America/Los_Angeles", "Pacific/Kiritimati", "Asia/Kolkata"):
        os.environ["TZ"] = tz
        try:
            time.tzset()  # make datetime.today() reflect this tz
        except AttributeError:
            pass  # non-POSIX; helper still correct via zoneinfo
        assert biz_today_str() == ist_date, f"biz_today_str drifted under TZ={tz}"
    os.environ.pop("TZ", None)
    try:
        time.tzset()
    except AttributeError:
        pass


# ── a receipt with no explicit date is stamped the IST business date ────────
def test_payment_and_journal_use_business_date(db):
    inv = billing.create_sale_invoice(
        db, business_id=BID, customer_id=BID, invoice_date="2026-01-01",
        lines=[{"product_id": _pid(db), "quantity": 500, "unit_price": 1.0}])
    pay = billing.record_payment(db, business_id=BID, invoice_id=inv.id,
                                 amount_paid=500, idempotency_key="tzpay")
    biz_date = biz_today_str()
    # Receipt date == business (IST) date, not the server-local date.
    assert pay.payment_date == biz_date
    # The journal entry for that receipt carries the same business date.
    je = (db.query(JournalEntry)
          .filter(JournalEntry.business_id == BID,
                  JournalEntry.source_type == "payment",
                  JournalEntry.source_id == pay.id).first())
    assert je is not None and je.entry_date == biz_date


# ── settlement receipts + advance journal also use the business date ────────
def test_settlement_dates_use_business_date(db):
    billing.create_sale_invoice(
        db, business_id=BID, customer_id=BID, invoice_date="2026-01-01",
        lines=[{"product_id": _pid(db), "quantity": 500, "unit_price": 1.0}])
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                 amount=600, idempotency_key="tzsettle")
    biz_date = biz_today_str()
    for p in db.query(InvoicePayment).filter(InvoicePayment.business_id == BID).all():
        assert p.payment_date == biz_date
    adv = (db.query(JournalEntry)
           .filter(JournalEntry.business_id == BID,
                   JournalEntry.source_type == "advance_receipt").first())
    assert adv is not None and adv.entry_date == biz_date
