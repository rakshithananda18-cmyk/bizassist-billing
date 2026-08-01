"""
tests/test_invoice_account.py — GET /invoices/{invoice_id}/account
==================================================================
The per-invoice money view: what this bill totalled, what has been received
against it, what is still owed, every receipt, and every return. It is what the
owner reads when a customer asks "what do I owe on this bill", so a wrong number
here is a wrong number spoken out loud to a customer.

WHY THIS FILE EXISTS
--------------------
The route had **zero** line coverage and **no test file in the corpus even
referenced its path**. It was found by measuring `core/api/payments.py` with
`pytest-cov` (rule 57) rather than by the name-reference proxy, which had scored
the module 9/12 and could not distinguish "exercised over HTTP" from "never
called at all". `invoice_account` was in the *covered* three by name and was in
fact the largest untested block in the file.

Three of the properties below are not stylistic — they are **defects that were
already found and fixed elsewhere in this review, living on in this route with
nothing pinning them down**:

1. **`paid` is derived from the payment LEDGER, not from `Invoice.paid_amount`.**
   That column is a projection, and M-7 was precisely the case where it drifted:
   a synced invoice kept `paid_amount = 0` while its receipts existed, so the
   customer was shown a debt they had already settled. Anyone "simplifying" this
   line back to the column reintroduces M-7 silently. (rule 39: reports must
   agree with the ledger.)

2. **The credit-note lookup is delimited.** The route's own comment records that
   a bare substring `LIKE` matched `INV-1` inside `INV-10` and `INV-100` and
   pulled **other invoices' credit notes** into this invoice's returns — money
   attributed to the wrong document. The fix was to match the trailing '.' in
   `"Credit note against <no>."`. A comment is not a test (rule 56).

3. **Tenant scoping.** Both the invoice and its payments are filtered by
   `business_id`, and another tenant's invoice must be indistinguishable from one
   that does not exist (rule 19).

The route function is called directly, bypassing FastAPI's dependency injection,
following `tests/test_pending_invoices.py` — no HTTP stack is needed to assert
arithmetic, and it keeps the failure message pointed at the route.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database.db import SessionLocal
from database.models import (Base, Product, Invoice, InvoiceLineItem, Inventory,
                             User, Customer)
from core.models import StockLedger, InvoicePayment, JournalEntry, JournalLine
from core.billing import commands as billing
from core.api.payments import invoice_account

BID = 704200          # this tenant
OTHER = 704201        # the neighbour, for the scoping tests


def _clear(*bids):
    db = SessionLocal()
    try:
        for bid in bids:
            ids = [r.id for r in db.query(Invoice.id)
                   .filter(Invoice.business_id == bid).all()]
            if ids:
                db.query(InvoiceLineItem).filter(
                    InvoiceLineItem.invoice_id.in_(ids)).delete(synchronize_session=False)
                # Payments FK to invoices, so they go FIRST — SQLite enforces
                # FKs since N4, and the old order "worked" by orphaning rows.
                #
                # Scoped by INVOICE, not by business_id: one of these tests
                # deliberately plants a payment row carrying the neighbour's
                # business_id against this tenant's invoice, which is the very
                # mis-scoping the route must survive. Deleting by business_id
                # alone leaves it behind and the FK then blocks the teardown.
                db.query(InvoicePayment).filter(
                    InvoicePayment.invoice_id.in_(ids)).delete(synchronize_session=False)
            db.query(InvoicePayment).filter(InvoicePayment.business_id == bid).delete()
            db.query(Invoice).filter(Invoice.business_id == bid).delete()
            ent = [r.id for r in db.query(JournalEntry.id)
                   .filter(JournalEntry.business_id == bid).all()]
            if ent:
                db.query(JournalLine).filter(
                    JournalLine.entry_id.in_(ent)).delete(synchronize_session=False)
            db.query(JournalEntry).filter(JournalEntry.business_id == bid).delete()
            db.query(StockLedger).filter(StockLedger.business_id == bid).delete()
            db.query(Inventory).filter(Inventory.business_id == bid).delete()
            db.query(Product).filter(Product.business_id == bid).delete()
            db.query(Customer).filter(Customer.business_id == bid).delete()
            db.query(User).filter(User.id == bid).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def db():
    d = SessionLocal()
    Base.metadata.create_all(bind=d.get_bind())
    d.close()
    _clear(BID, OTHER)
    s = SessionLocal()
    for bid, tag in ((BID, "acct"), (OTHER, "nbr")):
        s.add(User(id=bid, username=f"{tag}_{bid}", password="x", state_code="29"))
        s.add(Customer(id=bid, business_id=bid, name=f"Buyer {tag}"))
        s.add(Product(business_id=bid, name="W", selling_price=1.0,
                      cgst_rate=0, sgst_rate=0, igst_rate=0, track_inventory=False))
    s.commit()
    yield s
    s.close()
    _clear(BID, OTHER)


def _pid(db, bid=BID):
    return db.query(Product).filter(Product.business_id == bid).first().id


def _bill(db, amount, bid=BID, date="2026-03-01"):
    """A bill for exactly `amount` — unit price 1.0, no tax, so total == qty."""
    return billing.create_sale_invoice(
        db, business_id=bid, customer_id=bid, invoice_date=date,
        lines=[{"product_id": _pid(db, bid), "quantity": amount, "unit_price": 1.0}])


def _account(db, invoice_id, bid=BID):
    return invoice_account(invoice_id=invoice_id, current_user={"id": bid}, db=db)


# ══════════════════════════════════════════════════════════════════════════════
# The arithmetic
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unpaid_invoice_owes_its_whole_total(db):
    inv = _bill(db, 500)
    a = _account(db, inv.id)
    assert a["total"] == 500.0
    assert a["paid"] == 0.0
    assert a["outstanding"] == 500.0
    assert a["payments"] == []
    assert a["returns"] == []
    assert a["invoice_no"] == inv.invoice_id


def test_a_part_payment_reduces_the_outstanding_and_is_listed(db):
    inv = _bill(db, 500)
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                 amount=200, idempotency_key="acc-part")
    a = _account(db, inv.id)
    assert a["paid"] == 200.0
    assert a["outstanding"] == 300.0
    assert a["status"] == "Partial"
    assert len(a["payments"]) == 1
    assert a["payments"][0]["amount"] == 200.0


def test_a_fully_paid_invoice_owes_nothing_and_reads_Paid(db):
    inv = _bill(db, 500)
    billing.settle_customer_dues(db, business_id=BID, customer_id=BID,
                                 amount=500, idempotency_key="acc-full")
    a = _account(db, inv.id)
    assert a["paid"] == 500.0
    assert a["outstanding"] == 0.0
    assert a["status"] == "Paid"


def test_outstanding_never_goes_negative(db):
    """An overpayment is a customer credit, not a negative debt. Showing
    `-150` here would read as "we owe the customer ₹150 on this bill", which is
    a different fact living in a different place."""
    inv = _bill(db, 500)
    db.add(InvoicePayment(business_id=BID, invoice_id=inv.id, amount_paid=650.0,
                          payment_mode="Cash", payment_date="2026-03-02"))
    db.commit()
    a = _account(db, inv.id)
    assert a["paid"] == 650.0
    assert a["outstanding"] == 0.0, "outstanding must clamp at zero"


def test_every_receipt_is_listed_and_they_sum_to_paid(db):
    """Rule 55: a total and the list it summarises must be asserted equal.
    A receipt dropped from the list while still counted in `paid` is a customer
    being told they paid money they cannot see a receipt for."""
    inv = _bill(db, 900)
    for n, amt in enumerate([100.0, 250.5, 49.5], start=1):
        db.add(InvoicePayment(business_id=BID, invoice_id=inv.id, amount_paid=amt,
                              payment_mode="Cash", payment_date=f"2026-03-0{n+1}"))
    db.commit()
    a = _account(db, inv.id)
    assert len(a["payments"]) == 3
    assert round(sum(p["amount"] for p in a["payments"]), 2) == a["paid"] == 400.0
    assert a["outstanding"] == 500.0


# ══════════════════════════════════════════════════════════════════════════════
# M-7 — `paid` comes from the LEDGER, not from the projection column
# ══════════════════════════════════════════════════════════════════════════════

def test_paid_is_read_from_the_ledger_when_the_column_is_stale(db):
    """THE M-7 SHAPE. A pulled invoice carried `paid_amount = 0` while its
    receipts existed, so the owner chased a debt that had been settled. This
    route must believe the ledger."""
    inv = _bill(db, 500)
    db.add(InvoicePayment(business_id=BID, invoice_id=inv.id, amount_paid=500.0,
                          payment_mode="UPI", payment_date="2026-03-02"))
    db.commit()
    inv.paid_amount = 0.0                      # the stale projection
    inv.status = "Pending"
    db.commit()

    a = _account(db, inv.id)
    assert a["paid"] == 500.0, (
        "paid was read from Invoice.paid_amount, not from invoice_payments — "
        "this is M-7 returning: the customer is shown a debt they have settled")
    assert a["outstanding"] == 0.0
    assert a["status"] == "Paid"


def test_the_column_is_used_ONLY_when_there_are_no_ledger_rows(db):
    """The documented fallback, pinned so it cannot quietly widen. Legacy and
    CSV-imported invoices carry a paid figure with no receipts behind it; those
    must still report what they know rather than claiming zero."""
    inv = _bill(db, 500)
    inv.paid_amount = 300.0
    db.commit()
    assert db.query(InvoicePayment).filter(
        InvoicePayment.invoice_id == inv.id).count() == 0
    a = _account(db, inv.id)
    assert a["paid"] == 300.0
    assert a["outstanding"] == 200.0
    assert a["payments"] == [], "no receipts exist, so none may be invented"


# ══════════════════════════════════════════════════════════════════════════════
# The returns lookup — a fixed money-misattribution bug, now pinned
# ══════════════════════════════════════════════════════════════════════════════

def test_a_credit_note_against_this_invoice_is_listed_as_a_return(db):
    inv = _bill(db, 500)
    cn = billing.create_credit_note(
        db, business_id=BID, original_invoice_id=inv.id,
        lines=[{"product_id": _pid(db), "qty": 100, "reason": "damaged"}])
    a = _account(db, inv.id)
    assert [r["id"] for r in a["returns"]] == [cn.id]
    assert a["returns"][0]["credit_note_no"] == cn.invoice_id


def test_a_credit_note_for_a_DIFFERENT_invoice_is_not_listed(db):
    inv_a = _bill(db, 500)
    inv_b = _bill(db, 400)
    billing.create_credit_note(
        db, business_id=BID, original_invoice_id=inv_b.id,
        lines=[{"product_id": _pid(db), "qty": 50, "reason": "damaged"}])
    assert _account(db, inv_a.id)["returns"] == [], (
        "a return against another invoice was attributed to this one")


def test_an_invoice_number_that_is_a_PREFIX_of_another_does_not_steal_returns(db):
    """THE DELIMITER BUG, pinned. A bare `LIKE '%Credit note against INV-1%'`
    also matches `INV-10` and `INV-100`, so invoice 1's account showed the
    returns belonging to invoices 10 and 100 — money attributed to the wrong
    document, in the view a customer is shown.

    Built by hand rather than through the allocator, because the allocator will
    not deal a `-1` and a `-10` on demand and the bug needs exactly that pair.
    """
    short = Invoice(business_id=BID, customer_id=BID, invoice_id="ACC-1",
                    invoice_date="2026-03-01", total_amount=100.0,
                    amount=100.0, paid_amount=0.0, status="Pending")
    long = Invoice(business_id=BID, customer_id=BID, invoice_id="ACC-10",
                   invoice_date="2026-03-01", total_amount=200.0,
                   amount=200.0, paid_amount=0.0, status="Pending")
    db.add_all([short, long])
    db.commit()

    # A credit note that belongs to ACC-10 ONLY.
    cn = Invoice(business_id=BID, customer_id=BID, invoice_id="ACC-CN-1",
                 invoice_date="2026-03-02", invoice_type="credit_note",
                 total_amount=-50.0, amount=-50.0, paid_amount=0.0,
                 status="Paid", notes="Credit note against ACC-10.")
    db.add(cn)
    db.commit()

    assert [r["id"] for r in _account(db, long.id)["returns"]] == [cn.id], (
        "the credit note's own invoice lost its return")
    assert _account(db, short.id)["returns"] == [], (
        "ACC-1 claimed ACC-10's credit note — the substring bug is back, and "
        "this is a customer being shown someone else's return")


def test_an_invoice_with_no_number_reports_no_returns_rather_than_matching_all(db):
    """`inv.invoice_id` is nullable. Without the guard the marker becomes
    'Credit note against None.' — rule 9: a NULL must never take part in a
    matching decision by falling through to a wildcard."""
    inv = Invoice(business_id=BID, customer_id=BID, invoice_id=None,
                  invoice_date="2026-03-01", total_amount=100.0, amount=100.0,
                  paid_amount=0.0, status="Pending")
    db.add(inv)
    db.commit()
    assert _account(db, inv.id)["returns"] == []


# ══════════════════════════════════════════════════════════════════════════════
# Tenant scoping — rule 19
# ══════════════════════════════════════════════════════════════════════════════

def test_another_tenants_invoice_is_indistinguishable_from_a_missing_one(db):
    theirs = _bill(db, 500, bid=OTHER)
    with pytest.raises(HTTPException) as e:
        _account(db, theirs.id, bid=BID)
    assert e.value.status_code == 404
    assert "not found" in str(e.value.detail).lower(), (
        "the error must not confirm the invoice exists for someone else")


def test_a_missing_invoice_is_404(db):
    with pytest.raises(HTTPException) as e:
        _account(db, 999_999_999)
    assert e.value.status_code == 404


def test_a_cross_tenant_payment_can_no_longer_be_written_at_all(db):
    """This test used to CREATE the corruption in order to prove the query
    filtered it out. As of the N4-T tenant references it cannot: the database
    refuses the write.

    That is a strictly stronger guarantee and it is why the old version of this
    test now fails — the fixture was simulating, inside one database, the exact
    hazard the constraint was added for. Recorded rather than deleted, because
    "the test broke" and "the test was made obsolete by a better guarantee" look
    identical in a diff.
    """
    inv = _bill(db, 500)
    db.add(InvoicePayment(business_id=BID, invoice_id=inv.id, amount_paid=100.0,
                          payment_mode="Cash", payment_date="2026-03-02"))
    db.commit()

    db.add(InvoicePayment(business_id=OTHER, invoice_id=inv.id, amount_paid=999.0,
                          payment_mode="Cash", payment_date="2026-03-02"))
    with pytest.raises(IntegrityError) as e:
        db.commit()
    assert "fk_tenant_invoice_payments_invoice_id" in str(e.value)
    db.rollback()

    a = _account(db, inv.id)
    assert a["paid"] == 100.0
    assert len(a["payments"]) == 1


def test_the_query_is_still_scoped_by_business_even_so(db):
    """Defence in depth, and NOT redundant with the constraint above.

    The guard is installed by `ensure_tenant_fks`, which deliberately SKIPS
    installation on any database that already holds violating rows — so a
    customer mid-repair is running unguarded, and that is precisely when the
    query-level filter is the only thing left. It therefore still has to be
    proved, which means writing a row the constraint would normally refuse.

    The trigger is dropped for the duration of this one test and restored
    afterwards. That is a deliberate, narrow escape hatch: without it the only
    way to keep this property covered would be to weaken the constraint.
    """
    inv = _bill(db, 500)
    db.add(InvoicePayment(business_id=BID, invoice_id=inv.id, amount_paid=100.0,
                          payment_mode="Cash", payment_date="2026-03-02"))
    db.commit()

    from core.accounting.db_invariants import TENANT_FKS, ensure_tenant_fks
    only = [f for f in TENANT_FKS
            if f.child == "invoice_payments" and f.fk_column == "invoice_id"]
    engine = db.get_bind()

    # DDL goes through the ENGINE, not the Session. Dropping a trigger and then
    # asking `ensure_tenant_fks` to commit on `db.connection()` leaves the
    # Session's transaction and the raw Connection's fighting over the same
    # unit of work — which surfaced here as `This transaction is inactive`
    # rather than as anything to do with the property under test.
    with engine.connect() as c:
        for t in (f"{only[0].name}_ins", f"{only[0].name}_upd"):
            c.execute(text(f"DROP TRIGGER IF EXISTS {t}"))
        c.commit()
    try:
        db.add(InvoicePayment(business_id=OTHER, invoice_id=inv.id,
                              amount_paid=999.0, payment_mode="Cash",
                              payment_date="2026-03-02"))
        db.commit()

        a = _account(db, inv.id)
        assert a["paid"] == 100.0, "a payment row from another tenant was counted"
        assert len(a["payments"]) == 1
    finally:
        db.rollback()
        db.query(InvoicePayment).filter(
            InvoicePayment.business_id == OTHER,
            InvoicePayment.invoice_id == inv.id).delete(synchronize_session=False)
        db.commit()
        db.close()
        with engine.connect() as c:
            ensure_tenant_fks(c, only)


# ══════════════════════════════════════════════════════════════════════════════
# Receipt rendering
# ══════════════════════════════════════════════════════════════════════════════

def test_a_receipt_date_is_a_plain_date_not_a_timestamp(db):
    inv = _bill(db, 500)
    db.add(InvoicePayment(business_id=BID, invoice_id=inv.id, amount_paid=50.0,
                          payment_mode="Cash",
                          payment_date="2026-03-02T14:35:11"))
    db.commit()
    assert _account(db, inv.id)["payments"][0]["date"] == "2026-03-02"


def test_a_receipt_with_no_mode_defaults_to_Cash_and_a_blank_note(db):
    inv = _bill(db, 500)
    db.add(InvoicePayment(business_id=BID, invoice_id=inv.id, amount_paid=50.0,
                          payment_mode=None, note=None,
                          payment_date="2026-03-02"))
    db.commit()
    row = _account(db, inv.id)["payments"][0]
    assert row["method"] == "Cash"
    assert row["note"] == ""
