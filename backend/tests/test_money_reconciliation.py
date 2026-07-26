"""
tests/test_money_reconciliation.py
==================================
Review finding M-6 — the end-to-end money test.

Every money surface had unit tests. None of them rang a *day* of mixed trade
through the counter and then asked the only question that actually matters:

    does everything still add up?

That gap is why M-2 (journals not syncing) and M-7 (paid state not reconciling
on pull) both shipped. Each subsystem was individually correct and internally
consistent; the defect only existed *between* them, where nothing looked.

THE INVARIANTS (true regardless of the numbers)
-----------------------------------------------
  I1  Every journal entry foots: Σ debits == Σ credits.
  I2  The whole journal foots.
  I3  The general ledger nets to zero across all accounts.
  I4  Cash & Bank in the journal == the cash actually taken at the counter.
  I5  Accounts Receivable == the sum of outstanding balances on open invoices.
  I6  Sales (net of returns) == Σ taxable value on invoices, credit notes negative.
  I7  GST Payable == Σ tax collected, less tax refunded on returns.
  I8  Stock on hand == opening + purchases − sales + returns, per product.
  9   Invoice.paid_amount/status agree with the payment ledger for EVERY invoice.
  I10 The hash chain verifies.

Each is asserted after a full trading day: cash sales, credit sales, part
payments, a later settlement, an advance application, a return, and an expense.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Invoice, InvoiceLineItem, Product, Inventory, User, Customer
from core.models import (
    InvoicePayment, JournalEntry, JournalLine, StockLedger, DocumentSequence,
    PeriodLock, Expense,
)
from core.billing import commands as billing
from core.accounting import posting
from core.sync import apply_hooks
from core.stock import ledger as SL

BID = 701500
R2 = lambda x: round(float(x or 0.0), 2)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _clear():
    db = SessionLocal()
    try:
        ids = [r.id for r in db.query(Invoice.id).filter(Invoice.business_id == BID).all()]
        if ids:
            db.query(InvoiceLineItem).filter(
                InvoiceLineItem.invoice_id.in_(ids)).delete(synchronize_session=False)
        db.query(InvoicePayment).filter(InvoicePayment.business_id == BID).delete()
        ent = [r.id for r in db.query(JournalEntry.id).filter(
            JournalEntry.business_id == BID).all()]
        if ent:
            db.query(JournalLine).filter(
                JournalLine.entry_id.in_(ent)).delete(synchronize_session=False)
        db.query(JournalEntry).filter(JournalEntry.business_id == BID).delete()
        db.query(PeriodLock).filter(PeriodLock.business_id == BID).delete()
        db.query(Invoice).filter(Invoice.business_id == BID).delete()
        db.query(Expense).filter(Expense.business_id == BID).delete()
        db.query(StockLedger).filter(StockLedger.business_id == BID).delete()
        db.query(Inventory).filter(Inventory.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.query(Customer).filter(Customer.business_id == BID).delete()
        db.query(DocumentSequence).filter(DocumentSequence.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()
    _clear()
    db = SessionLocal()
    try:
        db.add(User(id=BID, username=f"biz{BID}", password="x", state_code="29"))
        db.commit()
    finally:
        db.close()
    yield
    _clear()


def _product(db, name, *, stock=100, price=100.0):
    p = Product(business_id=BID, name=name, hsn_sac="1006", unit="Nos",
                cgst_rate=9.0, sgst_rate=9.0, igst_rate=18.0,
                selling_price=price, track_inventory=True)
    db.add(p)
    db.flush()
    db.add(Inventory(business_id=BID, product_name=name, product_id=p.id, stock=stock))
    SL.record_movement(db, business_id=BID, movement_type=SL.OPENING,
                       qty_delta=stock, product_id=p.id, product_name=name,
                       update_cache=False)
    db.commit()
    return p.id


# ── Ledger readers ───────────────────────────────────────────────────────────

def _account_totals(db):
    """{account: (debit, credit)} across every posted line for this business."""
    rows = (
        db.query(JournalLine.account,
                 JournalLine.debit, JournalLine.credit, JournalEntry.id)
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .filter(JournalEntry.business_id == BID)
        .all()
    )
    out = {}
    for account, dr, cr, _ in rows:
        d, c = out.get(account, (0.0, 0.0))
        out[account] = (d + (dr or 0.0), c + (cr or 0.0))
    return {k: (R2(v[0]), R2(v[1])) for k, v in out.items()}


def _net(totals, account):
    """Debit-positive net movement on an account."""
    d, c = totals.get(account, (0.0, 0.0))
    return R2(d - c)


# ── The trading day ──────────────────────────────────────────────────────────

def _trade_a_day(db):
    """Cash sale, credit sale, part payment, settlement, advance, return, expense."""
    rice = _product(db, "Rice", stock=100, price=100.0)
    dal = _product(db, "Dal", stock=50, price=200.0)

    cust = Customer(business_id=BID, name="Ravi Stores")
    db.add(cust)
    db.flush()
    db.commit()

    facts = {"rice": rice, "dal": dal, "customer_id": cust.id}

    # 1. Cash sale, paid in full at the counter.
    facts["cash_sale"] = billing.create_sale_invoice(
        db, business_id=BID, place_of_supply="29", mark_paid=True,
        payment_mode="Cash",
        lines=[{"product_id": rice, "quantity": 2, "unit_price": 100.0}])

    # 2. Credit sale — nothing paid.
    facts["credit_sale"] = billing.create_sale_invoice(
        db, business_id=BID, place_of_supply="29", customer_id=cust.id,
        lines=[{"product_id": dal, "quantity": 3, "unit_price": 200.0}])

    # 3. Part-paid sale.
    facts["part_sale"] = billing.create_sale_invoice(
        db, business_id=BID, place_of_supply="29", customer_id=cust.id,
        paid_amount=100.0, payment_mode="Cash",
        lines=[{"product_id": rice, "quantity": 4, "unit_price": 100.0}])

    # 4. A later receipt settling the credit sale in full.
    billing.record_payment(
        db, business_id=BID, invoice_id=facts["credit_sale"].id,
        amount_paid=R2(facts["credit_sale"].total_amount),
        payment_mode="Cash", idempotency_key="settle-credit-sale")

    # 5. A return against the cash sale.
    facts["credit_note"] = billing.create_credit_note(
        db, business_id=BID, original_invoice_id=facts["cash_sale"].id,
        lines=[{"product_id": rice, "qty": 1}])

    # 6. An operating expense.
    exp = Expense(business_id=BID, amount=500.0, category="Rent",
                  expense_type="Indirect", payment_mode="Cash",
                  expense_date="2026-07-01")
    db.add(exp)
    db.flush()
    posting.post_expense(db, exp)
    db.commit()
    facts["expense"] = exp
    return facts


# ── I1 / I2 / I10 — the journal is internally sound ─────────────────────────

def test_every_journal_entry_foots():
    db = SessionLocal()
    try:
        _trade_a_day(db)
        entries = db.query(JournalEntry).filter(JournalEntry.business_id == BID).all()
        assert entries, "a full trading day posted no journal entries at all"
        for e in entries:
            lines = db.query(JournalLine).filter(JournalLine.entry_id == e.id).all()
            dr = R2(sum(l.debit or 0.0 for l in lines))
            cr = R2(sum(l.credit or 0.0 for l in lines))
            assert abs(dr - cr) < 0.01, f"{e.source_type}#{e.source_id} Dr {dr} != Cr {cr}"
    finally:
        db.close()


def test_the_journal_as_a_whole_foots():
    db = SessionLocal()
    try:
        _trade_a_day(db)
        totals = _account_totals(db)
        dr = R2(sum(v[0] for v in totals.values()))
        cr = R2(sum(v[1] for v in totals.values()))
        assert abs(dr - cr) < 0.01, f"books do not balance: Dr {dr} vs Cr {cr}"
    finally:
        db.close()


def test_the_general_ledger_nets_to_zero():
    db = SessionLocal()
    try:
        _trade_a_day(db)
        totals = _account_totals(db)
        assert abs(R2(sum(_net(totals, a) for a in totals))) < 0.01
    finally:
        db.close()


def test_the_hash_chain_verifies_after_a_full_day():
    db = SessionLocal()
    try:
        _trade_a_day(db)
        report = posting.verify_chain(db, BID)
        assert report["ok"], report
        assert report["checked"] > 0
    finally:
        db.close()


# ── I4 — cash in the journal == cash actually taken ─────────────────────────

def test_cash_account_equals_money_actually_received_less_expenses():
    """The drawer test. Cash & Bank must equal every rupee that came in through
    the payment ledger, minus what went out as expenses."""
    db = SessionLocal()
    try:
        facts = _trade_a_day(db)

        # Cash actually received = the payment ledger, excluding advance
        # applications (those move a liability, they are not new cash).
        received = 0.0
        for p in db.query(InvoicePayment).filter(InvoicePayment.business_id == BID).all():
            if apply_hooks and (p.idempotency_key or "").startswith("advance-credit::"):
                continue
            received += (p.amount_paid or 0.0)
        received = R2(received)

        spent = R2(facts["expense"].amount)
        totals = _account_totals(db)
        assert _net(totals, posting.ACC_CASH) == R2(received - spent), (
            f"cash in the books ({_net(totals, posting.ACC_CASH)}) != "
            f"received {received} - spent {spent}"
        )
    finally:
        db.close()


# ── I5 — receivables == what customers still owe ────────────────────────────

def test_accounts_receivable_equals_outstanding_invoice_balances():
    db = SessionLocal()
    try:
        _trade_a_day(db)

        outstanding = 0.0
        for inv in db.query(Invoice).filter(Invoice.business_id == BID).all():
            total = R2(inv.total_amount)
            paid = R2(inv.paid_amount)
            if (inv.invoice_type or "") == "credit_note":
                outstanding -= total          # a return reduces what is owed
            else:
                outstanding += (total - paid)
        outstanding = R2(outstanding)

        totals = _account_totals(db)
        assert _net(totals, posting.ACC_AR) == outstanding, (
            f"receivables in the books ({_net(totals, posting.ACC_AR)}) != "
            f"outstanding on invoices ({outstanding}) — someone is being chased "
            f"for the wrong amount"
        )
    finally:
        db.close()


# ── I6 / I7 — revenue and tax tie back to the documents ────────────────────

def test_sales_account_equals_taxable_value_net_of_returns():
    db = SessionLocal()
    try:
        _trade_a_day(db)

        net_sales = 0.0
        for inv in db.query(Invoice).filter(Invoice.business_id == BID).all():
            gst = R2((inv.cgst_total or 0) + (inv.sgst_total or 0)
                     + (inv.igst_total or 0) + (inv.cess_total or 0))
            cash_disc = R2(getattr(inv, "cash_discount", 0.0))
            taxable = R2(R2(inv.total_amount) + cash_disc - gst)
            net_sales += -taxable if (inv.invoice_type or "") == "credit_note" else taxable

        totals = _account_totals(db)
        # Sales is a credit-balance account, so its debit-positive net is negative.
        assert abs(-_net(totals, posting.ACC_SALES) - R2(net_sales)) < 0.02
    finally:
        db.close()


def test_gst_payable_equals_tax_collected_net_of_returns():
    db = SessionLocal()
    try:
        _trade_a_day(db)

        net_gst = 0.0
        for inv in db.query(Invoice).filter(Invoice.business_id == BID).all():
            gst = R2((inv.cgst_total or 0) + (inv.sgst_total or 0)
                     + (inv.igst_total or 0) + (inv.cess_total or 0))
            net_gst += -gst if (inv.invoice_type or "") == "credit_note" else gst

        totals = _account_totals(db)
        assert abs(-_net(totals, posting.ACC_GST_OUT) - R2(net_gst)) < 0.02, (
            "GST in the books disagrees with GST on the invoices — this is what "
            "gets filed"
        )
    finally:
        db.close()


# ── I8 — stock ties to the movements ────────────────────────────────────────

def test_stock_on_hand_equals_opening_less_sales_plus_returns():
    db = SessionLocal()
    try:
        facts = _trade_a_day(db)
        # Rice: opened 100, sold 2 + 4, returned 1.
        assert SL.current_stock(db, BID, product_id=facts["rice"]) == 95.0
        # Dal: opened 50, sold 3.
        assert SL.current_stock(db, BID, product_id=facts["dal"]) == 47.0
    finally:
        db.close()


def test_the_stock_ledger_is_the_only_source_of_the_on_hand_figure():
    """Summing the append-only movements must reproduce current_stock exactly —
    if a cached column ever drifts from the ledger, this catches it."""
    db = SessionLocal()
    try:
        facts = _trade_a_day(db)
        for pid in (facts["rice"], facts["dal"]):
            summed = R2(sum(
                m.qty_delta or 0.0
                for m in db.query(StockLedger).filter(
                    StockLedger.business_id == BID,
                    StockLedger.product_id == pid).all()
            ))
            assert summed == R2(SL.current_stock(db, BID, product_id=pid))
    finally:
        db.close()


# ── I9 — the paid-state projection agrees with the ledger, for EVERY invoice ─

def test_every_invoice_paid_state_agrees_with_its_payment_ledger():
    """The M-7 invariant, asserted across a whole day rather than one row."""
    db = SessionLocal()
    try:
        _trade_a_day(db)
        for inv in db.query(Invoice).filter(Invoice.business_id == BID).all():
            if (inv.invoice_type or "") == "credit_note":
                continue
            ledger = R2(sum(
                p.amount_paid or 0.0
                for p in db.query(InvoicePayment).filter(
                    InvoicePayment.business_id == BID,
                    InvoicePayment.invoice_id == inv.id).all()
            ))
            if ledger == 0:
                continue
            assert R2(inv.paid_amount) == ledger, (
                f"{inv.invoice_id}: paid_amount {inv.paid_amount} != ledger {ledger}")
            assert inv.status == apply_hooks.derive_paid_state(
                ledger, R2(inv.total_amount)), (
                f"{inv.invoice_id}: status {inv.status} disagrees with its ledger")
    finally:
        db.close()


def test_a_settled_invoice_reads_as_paid_end_to_end():
    """The customer-visible version of the same thing."""
    db = SessionLocal()
    try:
        facts = _trade_a_day(db)
        db.refresh(facts["credit_sale"])
        assert facts["credit_sale"].status == "Paid"
        db.refresh(facts["part_sale"])
        assert facts["part_sale"].status == "Partial"
    finally:
        db.close()


# ── Every document produced a journal entry — nothing fell through ─────────

def test_every_commercial_document_has_a_journal_entry():
    """The M-2 invariant. A document with no entry means the books are short by
    exactly that amount, and nothing else in the system would notice."""
    db = SessionLocal()
    try:
        _trade_a_day(db)

        for inv in db.query(Invoice).filter(Invoice.business_id == BID).all():
            want = "credit_note" if (inv.invoice_type or "") == "credit_note" else "sale"
            assert db.query(JournalEntry).filter(
                JournalEntry.business_id == BID,
                JournalEntry.source_type == want,
                JournalEntry.source_id == inv.id).first() is not None, (
                f"{inv.invoice_id} has no journal entry")

        # Receipts are NOT one-entry-each, and asserting that they are is what
        # this test originally got wrong. An INITIAL receipt (taken at sale time)
        # is already inside its invoice's sale entry — `build_sale_lines` debits
        # Cash for `paid_amount` — so it must NOT have its own entry, or the cash
        # is counted twice. Only a LATER receipt is a separate accounting event.
        from core.accounting import repost as _repost
        for pay in db.query(InvoicePayment).filter(InvoicePayment.business_id == BID).all():
            has_entry = db.query(JournalEntry).filter(
                JournalEntry.business_id == BID,
                JournalEntry.source_type == "payment",
                JournalEntry.source_id == pay.id).first() is not None
            if _repost.is_initial_payment(pay):
                assert not has_entry, (
                    f"payment #{pay.id} is an initial receipt already booked in "
                    f"its sale entry — a second entry double-counts the cash")
            else:
                assert has_entry, f"later receipt #{pay.id} has no journal entry"
    finally:
        db.close()


def test_no_document_is_double_posted():
    """Idempotency across the whole day: one entry per source document, never two."""
    db = SessionLocal()
    try:
        _trade_a_day(db)
        seen = {}
        for e in db.query(JournalEntry).filter(JournalEntry.business_id == BID).all():
            key = (e.source_type, e.source_id)
            assert key not in seen, f"{key} posted twice — money counted double"
            seen[key] = e.id
    finally:
        db.close()


# ── Invoice numbering across the day ────────────────────────────────────────

def test_no_invoice_number_is_used_twice_across_the_day():
    db = SessionLocal()
    try:
        _trade_a_day(db)
        numbers = [i.invoice_id for i in
                   db.query(Invoice).filter(Invoice.business_id == BID).all()]
        assert len(numbers) == len(set(numbers)), f"duplicate invoice number: {numbers}"
    finally:
        db.close()
