"""Regression + invariant tests for GET /billing/pending-invoices.

This endpoint feeds the Transactions "pending dues" list. It once filtered on a
lowercase "partial" while the app writes "Partial" (capital P), so every
partially-settled invoice silently vanished from Transactions while Contacts and
Invoices still showed it — the "Transactions cleared, Contacts pending" mismatch.

These tests lock the endpoint to a single invariant: it lists EXACTLY the
non-credit-note invoices that still owe money (balance = total - paid > 0),
regardless of how the status string is cased. The route function is called
directly (bypassing FastAPI's dependency injection) so no full app/HTTP stack is
needed.
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
from core.api.payments import list_pending_invoices

BID = 703100


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
    s.add(User(id=BID, username=f"pend_{BID}", password="x", state_code="29"))
    s.add(Customer(id=BID, business_id=BID, name="Buyer"))
    s.add(Product(business_id=BID, name="W", selling_price=1.0,
                  cgst_rate=0, sgst_rate=0, igst_rate=0, track_inventory=False))
    s.commit()
    yield s
    s.close()


def _pid(db):
    return db.query(Product).filter(Product.business_id == BID).first().id


def _bill(db, amount, date="2026-01-01"):
    return billing.create_sale_invoice(
        db, business_id=BID, customer_id=BID, invoice_date=date,
        lines=[{"product_id": _pid(db), "quantity": amount, "unit_price": 1.0}])


def _call(db):
    """Invoke the real route function directly and index the result by invoice_id."""
    rows = list_pending_invoices(current_user={"id": BID}, db=db)
    return {r["invoice_id"]: r for r in rows}


def _set(db, inv, *, status=None, paid=None):
    if status is not None:
        inv.status = status
    if paid is not None:
        inv.paid_amount = paid
    db.commit()


# ── the headline bug: a Partial invoice must be listed ──────────────────────
def test_partial_invoice_from_real_settle_is_listed(db):
    a = _bill(db, 500, "2026-01-01")
    b = _bill(db, 600, "2026-01-05")
    # Pay 700 → A fully Paid, B Partial with 400 outstanding.
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                 amount=700, idempotency_key="p1")
    assert b.status == "Partial"

    rows = _call(db)
    assert a.invoice_id not in rows, "fully-paid invoice must not be a pending due"
    assert b.invoice_id in rows, "partially-paid invoice was dropped (the bug)"
    assert rows[b.invoice_id]["balance_due"] == 400.0


# ── status casing must never decide inclusion ───────────────────────────────
@pytest.mark.parametrize("status", ["Partial", "partial", "PARTIAL", "Pending",
                                    "pending", "Overdue", "overdue"])
def test_status_casing_is_ignored(db, status):
    inv = _bill(db, 300, "2026-01-01")
    _set(db, inv, status=status, paid=100)   # balance 200 owed
    rows = _call(db)
    assert inv.invoice_id in rows
    assert rows[inv.invoice_id]["balance_due"] == 200.0


@pytest.mark.parametrize("status", ["Paid", "paid", "PAID"])
def test_paid_is_always_excluded(db, status):
    inv = _bill(db, 300, "2026-01-01")
    _set(db, inv, status=status, paid=300)
    assert inv.invoice_id not in _call(db)


# ── balance guard: a stale non-Paid status with zero balance is NOT a due ────
def test_zero_balance_is_skipped_even_if_status_pending(db):
    inv = _bill(db, 300, "2026-01-01")
    _set(db, inv, status="Pending", paid=300)   # fully paid, status not flipped
    assert inv.invoice_id not in _call(db)


# ── credit notes are never dues ─────────────────────────────────────────────
def test_credit_notes_excluded(db):
    inv = _bill(db, 300, "2026-01-01")
    _set(db, inv, status="Pending", paid=0)
    inv.invoice_type = "credit_note"
    db.commit()
    assert inv.invoice_id not in _call(db)


# ── the cross-view invariant: endpoint == what Contacts computes as owed ─────
def test_endpoint_total_matches_customer_outstanding(db):
    _bill(db, 500, "2026-01-01")
    _bill(db, 600, "2026-01-05")
    _bill(db, 250, "2026-01-09")
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                 amount=900, idempotency_key="inv1")

    endpoint_total = round(sum(r["balance_due"] for r in
                               list_pending_invoices(current_user={"id": BID}, db=db)), 2)
    # Same figure Contacts derives: SUM(total - paid) over non-credit-note invoices.
    contacts_total = round(sum(
        (i.total_amount or i.amount or 0) - (i.paid_amount or 0)
        for i in db.query(Invoice).filter(
            Invoice.business_id == BID, Invoice.invoice_type != "credit_note").all()
    ), 2)
    assert endpoint_total == contacts_total == 450.0
