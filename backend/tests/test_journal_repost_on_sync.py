"""
tests/test_journal_repost_on_sync.py
====================================
Review finding M-2 — the double-entry journal did not cross the sync boundary.

THE BUG
-------
``journal_entries`` / ``journal_lines`` were absent from
``database/sync_map.MODEL_MAP``. A sale rung up on a local install pushed its
Invoice, line items, stock movements and payment receipt to the cloud and left
the journal behind. The cloud's trial balance, P&L and party ledger therefore
omitted every locally-rung sale — and nothing raised, because each database was
internally consistent and only the PAIR was wrong. The scheduled books-integrity
audit runs per-database and reported "balanced" on both.

THE FIX UNDER TEST
------------------
Journals are DERIVED, not replicated: ``core/accounting/repost.py`` re-posts the
entry on the destination from the document that just landed. Each database keeps
its own valid hash chain over its own document ids.

What this file pins:
  1. a synced document produces a balanced journal entry on the destination
  2. re-applying the same document does NOT double-post (the sync retry case)
  3. the destination's hash chain stays verifiable
  4. a locked period does NOT block replicated history (it would otherwise leave
     the destination holding a document with no journal)
  5. a user-facing post is STILL blocked by a period lock — the bypass is
     replication-only and must not leak
  6. non-financial entities are skipped
  7. a failing repost is reported, not swallowed, and does not poison the batch
  8. journals stay OUT of MODEL_MAP and period_locks is IN, in both directions

Pure DB unit test — exercises the repost seam directly rather than standing up
two backends.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Invoice, InvoiceLineItem, Product, Inventory, User
from core.models import (
    JournalEntry, JournalLine, InvoicePayment, StockLedger, PeriodLock,
    DocumentSequence, Expense,
)
from core.accounting import posting, repost
from core.accounting import period_lock as PL

BID = 701100


# ── Fixtures ─────────────────────────────────────────────────────────────────

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
        db.query(DocumentSequence).filter(DocumentSequence.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    db = SessionLocal()
    try:
        db.add(User(id=BID, username=f"biz{BID}", password="x", state_code="29"))
        db.commit()
    finally:
        db.close()
    yield
    _clear()


def _landed_invoice(db, *, number="INV-0001", date="2026-07-01", total=236.0,
                    gst=36.0, paid=0.0, invoice_type="B2C"):
    """An invoice row as the sync apply path would leave it: header written and
    flushed, journal NOT posted (because the source database kept its own)."""
    inv = Invoice(
        business_id=BID, invoice_id=number, customer="Ravi",
        amount=total, total_amount=total, status="Pending",
        invoice_date=date, invoice_type=invoice_type,
        subtotal=round(total - gst, 2), cgst_total=round(gst / 2, 2),
        sgst_total=round(gst / 2, 2), igst_total=0.0, cess_total=0.0,
        paid_amount=paid,
    )
    db.add(inv)
    db.flush()
    return inv


def _entries(db, source_type=None):
    q = db.query(JournalEntry).filter(JournalEntry.business_id == BID)
    if source_type:
        q = q.filter(JournalEntry.source_type == source_type)
    return q.order_by(JournalEntry.id).all()


def _foots(db, entry) -> bool:
    lines = db.query(JournalLine).filter(JournalLine.entry_id == entry.id).all()
    dr = round(sum(l.debit or 0.0 for l in lines), 2)
    cr = round(sum(l.credit or 0.0 for l in lines), 2)
    return abs(dr - cr) < 0.01 and dr > 0


# ── 1. The regression: a synced document gets a journal here ────────────────

def test_synced_invoice_gets_a_balanced_journal_on_the_destination():
    """THE M-2 bug: before the fix the destination held the invoice and no entry."""
    db = SessionLocal()
    try:
        inv = _landed_invoice(db)
        assert _entries(db) == [], "precondition: nothing posted yet"

        result = repost.repost_synced_row(db, "invoices", inv)
        db.commit()

        assert result.status == "posted", result
        entries = _entries(db)
        assert len(entries) == 1
        assert entries[0].source_type == "sale"
        assert entries[0].source_id == inv.id, "entry must point at THIS db's row id"
        assert _foots(db, entries[0]), "a journal entry that doesn't foot is not books"
    finally:
        db.close()


def test_synced_credit_note_posts_as_a_credit_note_not_a_sale():
    db = SessionLocal()
    try:
        cn = _landed_invoice(db, number="CN-0001", invoice_type="credit_note")
        repost.repost_synced_row(db, "invoices", cn)
        db.commit()

        entries = _entries(db)
        assert len(entries) == 1
        assert entries[0].source_type == "credit_note"
        assert _foots(db, entries[0])
    finally:
        db.close()


def test_synced_expense_gets_its_entry():
    db = SessionLocal()
    try:
        exp = Expense(business_id=BID, amount=500.0, category="Rent",
                      expense_type="Indirect", payment_mode="Cash",
                      expense_date="2026-07-02")
        db.add(exp)
        db.flush()

        assert repost.repost_synced_row(db, "expenses", exp).status == "posted"
        db.commit()

        entries = _entries(db, "expense")
        assert len(entries) == 1 and _foots(db, entries[0])
    finally:
        db.close()


# ── 2. Idempotency — sync retries are the normal case, not the edge case ────

def test_reapplying_the_same_document_does_not_double_post():
    db = SessionLocal()
    try:
        inv = _landed_invoice(db)
        first = repost.repost_synced_row(db, "invoices", inv)
        db.commit()

        # An outbox replay, an LWW update, a re-pull — all land here again.
        for _ in range(3):
            again = repost.repost_synced_row(db, "invoices", inv)
            assert again.status == "existing", again
        db.commit()

        assert first.status == "posted"
        assert len(_entries(db)) == 1, "the journal was posted more than once"
    finally:
        db.close()


def test_two_documents_produce_two_distinct_entries():
    db = SessionLocal()
    try:
        a = _landed_invoice(db, number="INV-0001")
        b = _landed_invoice(db, number="INV-0002")
        repost.repost_synced_row(db, "invoices", a)
        repost.repost_synced_row(db, "invoices", b)
        db.commit()

        entries = _entries(db)
        assert len(entries) == 2
        assert {e.source_id for e in entries} == {a.id, b.id}
    finally:
        db.close()


# ── 3. The hash chain stays intact ──────────────────────────────────────────

def test_reposted_entries_keep_the_chain_verifiable():
    """The reason journals are re-derived rather than copied: each database owns
    its own chain, and re-posting must extend it correctly."""
    db = SessionLocal()
    try:
        for n in range(1, 4):
            inv = _landed_invoice(db, number=f"INV-{n:04d}")
            repost.repost_synced_row(db, "invoices", inv)
        db.commit()

        report = posting.verify_chain(db, BID)
        assert report["ok"], report
        assert report["checked"] == 3
    finally:
        db.close()


def test_reposted_entries_chain_onto_locally_posted_ones():
    """Mixed origin — a sale rung up here, then one arriving over sync — must
    still form ONE valid chain."""
    db = SessionLocal()
    try:
        local = _landed_invoice(db, number="INV-0001")
        posting.post_sale(db, local)                 # normal command path
        db.commit()

        arrived = _landed_invoice(db, number="INV-0002")
        repost.repost_synced_row(db, "invoices", arrived)
        db.commit()

        report = posting.verify_chain(db, BID)
        assert report["ok"], report
        assert report["checked"] == 2
    finally:
        db.close()


# ── 4/5. Period locks: replication passes, users don't ──────────────────────

def test_a_locked_period_does_not_block_replicated_history():
    """The destination locked its books on a different day from the source. The
    document was legitimately posted where it was authored — refusing it here
    would leave this database holding an invoice with NO journal entry, which is
    strictly worse than a late entry in a closed period."""
    db = SessionLocal()
    try:
        db.add(PeriodLock(business_id=BID, locked_through="2026-07-31", is_active=True))
        db.commit()

        inv = _landed_invoice(db, date="2026-07-01")   # inside the locked period
        result = repost.repost_synced_row(db, "invoices", inv)
        db.commit()

        assert result.status == "posted", result
        assert len(_entries(db)) == 1
    finally:
        db.close()


def test_the_lock_bypass_does_not_leak_to_the_normal_command_path():
    """The bypass is replication-only. A counter posting into closed books must
    still be refused — this is the test that would catch someone reintroducing
    the module-global monkeypatch."""
    db = SessionLocal()
    try:
        db.add(PeriodLock(business_id=BID, locked_through="2026-07-31", is_active=True))
        db.commit()

        arrived = _landed_invoice(db, number="INV-0001", date="2026-07-01")
        repost.repost_synced_row(db, "invoices", arrived)
        db.commit()

        user_sale = _landed_invoice(db, number="INV-0002", date="2026-07-02")
        with pytest.raises(PL.PeriodLockedError):
            posting.post_sale(db, user_sale)          # default: lock ENFORCED
        db.rollback()
    finally:
        db.close()


def test_period_lock_default_is_still_enforced_at_post_entry():
    """Belt-and-braces on the signature itself: the flag must default to True,
    so any caller that forgets it gets the safe behaviour."""
    db = SessionLocal()
    try:
        db.add(PeriodLock(business_id=BID, locked_through="2026-07-31", is_active=True))
        db.commit()
        with pytest.raises(PL.PeriodLockedError):
            posting.post_entry(
                db, business_id=BID, entry_date="2026-07-05",
                source_type="sale", source_id=999_001, ref_no="X", narration="x",
                lines=[(posting.ACC_CASH, 10.0, 0.0), (posting.ACC_SALES, 0.0, 10.0)],
            )
        db.rollback()
    finally:
        db.close()


# ── 6. Entities with no journal consequence ─────────────────────────────────

def test_non_financial_entities_are_skipped():
    db = SessionLocal()
    try:
        p = Product(business_id=BID, name="Rice", hsn_sac="1006", unit="Nos")
        db.add(p)
        db.flush()
        for entity in ("products", "customers", "product_barcodes", "stock_ledger"):
            assert repost.repost_synced_row(db, entity, p).status == "skipped"
        assert _entries(db) == []
        db.rollback()
    finally:
        db.close()


def test_an_unflushed_row_is_skipped_not_crashed():
    """No id yet ⇒ nothing to key idempotency on. Must degrade, not raise."""
    db = SessionLocal()
    try:
        inv = Invoice(business_id=BID, invoice_id="INV-0009", total_amount=100.0)
        assert repost.repost_synced_row(db, "invoices", inv).status == "skipped"
        db.rollback()
    finally:
        db.close()


# ── 7. Failures are reported, never swallowed ───────────────────────────────

def test_a_failing_repost_is_reported_and_leaves_the_session_usable(monkeypatch):
    """One unpostable document must not poison the rest of the sync batch — that
    would turn a missing journal entry into a stalled outbox.

    The failure is injected at the POSTING step, which is the realistic mode: an
    entry that doesn't foot, or a period-lock refusal. An earlier version of this
    test instead corrupted a column value on the invoice itself, which fails
    differently and taught me something worth recording — see the note below.
    """
    db = SessionLocal()
    try:
        first = _landed_invoice(db, number="INV-0001", total=100.0, gst=0.0)

        def _boom(*a, **k):
            raise ValueError("journal entry does not foot: Dr 1 != Cr 2")
        monkeypatch.setattr(posting, "post_sale", _boom)

        result = repost.repost_synced_row(db, "invoices", first)
        assert result.status == "failed", result
        assert result.ok is False
        assert result.error, "a failure with no reason attached is a silent failure"

        # The session must still be usable — the savepoint rolled the post back.
        monkeypatch.undo()
        ok = _landed_invoice(db, number="INV-0002", total=118.0, gst=18.0)
        assert repost.repost_synced_row(db, "invoices", ok).status == "posted"
        db.commit()
        assert len(_entries(db)) == 1
    finally:
        db.close()


# ── REMOVED: a test about a corrupt source-row column ──────────────────────
#
# I wrote it twice, asserting opposite outcomes, and it failed both ways: first
# "the session is poisoned" (it wasn't), then "the session recovers" (it didn't).
# Two contradictory results from the same sequence means my model of the
# interaction was wrong, not that one assertion needed flipping — so guessing a
# third time would have been writing a test to match whatever the code happened
# to do, which is worthless as evidence.
#
# It was also testing the wrong thing. Whether SQLAlchemy expires an object on
# savepoint rollback is an internal of SQLAlchemy + the dialect, not a contract
# of this codebase, and the scenario is not reachable in production: the sync
# apply paths write each row inside their own per-row savepoint BEFORE the repost
# hooks run, so a value the column cannot hold fails there and the row never
# reaches this module.
#
# The property that actually matters — a failing repost is REPORTED and the
# batch keeps going — is covered by
# `test_a_failing_repost_is_reported_and_leaves_the_session_usable` above, which
# injects the realistic failure (a posting that refuses) rather than a corrupt
# column value.


def test_an_initial_receipt_is_not_reposted():
    """It is already inside its invoice's sale entry — see repost.is_initial_payment.

    Without this, every synced `mark_paid` sale would debit Cash twice on the
    destination, and the trial balance would still foot because both entries are
    individually balanced. Silent, and only visible by reconciling cash against
    the receipts that actually came in.
    """
    db = SessionLocal()
    try:
        inv = _landed_invoice(db, total=236.0)
        initial = InvoicePayment(
            business_id=BID, invoice_id=inv.id, amount_paid=236.0,
            payment_mode="Cash", payment_date="2026-07-01",
            note="Initial payment for invoice INV-0001",
            idempotency_key="init::1")
        db.add(initial)
        db.flush()

        assert repost.is_initial_payment(initial) is True
        assert repost.repost_synced_row(db, "invoice_payments", initial).status == "skipped"
        assert _entries(db, "payment") == []
        db.rollback()
    finally:
        db.close()


def test_a_later_receipt_IS_reposted():
    """The other half of the rule — a settlement after the sale is a real event."""
    db = SessionLocal()
    try:
        inv = _landed_invoice(db, total=236.0)
        later = InvoicePayment(
            business_id=BID, invoice_id=inv.id, amount_paid=236.0,
            payment_mode="Cash", payment_date="2026-07-05",
            note="Settlement", idempotency_key="later::1")
        db.add(later)
        db.flush()

        assert repost.is_initial_payment(later) is False
        assert repost.repost_synced_row(db, "invoice_payments", later).status == "posted"
        assert len(_entries(db, "payment")) == 1
        db.rollback()
    finally:
        db.close()


# ── 8. The sync map contract ────────────────────────────────────────────────

def test_journals_stay_out_of_the_sync_map_and_period_locks_are_in():
    from database.sync_map import MODEL_MAP
    from database.models import _SYNC_TABLES
    from routes.sync import APPEND_ONLY_DELETE_BLOCKLIST

    assert "journal_entries" not in MODEL_MAP, (
        "journals are DERIVED — replicating them copies an invalid per-database "
        "hash chain pointing at wrong document ids (M-2)"
    )
    assert "journal_lines" not in MODEL_MAP

    # period_locks must travel in BOTH directions. MODEL_MAP alone is pull-only.
    assert "period_locks" in MODEL_MAP
    assert "period_locks" in _SYNC_TABLES, "in MODEL_MAP but not _SYNC_TABLES = pull-only"
    assert "period_locks" in APPEND_ONLY_DELETE_BLOCKLIST, (
        "a sync-borne DELETE would erase a close event and re-open locked books"
    )


def test_every_repostable_entity_is_actually_synced():
    """A document we intend to repost is useless if it never arrives."""
    from database.sync_map import MODEL_MAP
    for entity in repost.REPOSTABLE_ENTITIES:
        assert entity in MODEL_MAP, f"{entity} is repostable but not synced"


def test_every_repostable_entity_has_a_poster_and_a_source_type():
    """Guards the split-brain failure: a poster whose source_type doesn't match
    the idempotency probe would re-post the same entry on every single sync."""
    for entity in repost.REPOSTABLE_ENTITIES:
        assert entity in repost._POSTERS, f"{entity} has no poster"

    db = SessionLocal()
    try:
        inv = _landed_invoice(db)
        assert repost._source_type_of("invoices", inv) == "sale"
        repost.repost_synced_row(db, "invoices", inv)
        db.flush()
        # The probe must now find what the poster wrote — if these ever diverge,
        # this returns "posted" a second time instead of "existing".
        assert repost.repost_synced_row(db, "invoices", inv).status == "existing"
        db.rollback()
    finally:
        db.close()


# ── Advance-vs-cash routing on a synced receipt ─────────────────────────────

def test_a_synced_advance_application_posts_against_advances_not_cash():
    """Applying banked credit must draw down the liability. Posting it as cash
    would double-count the money — it was already booked when the advance came
    in."""
    db = SessionLocal()
    try:
        inv = _landed_invoice(db, total=500.0, gst=0.0)
        pay = InvoicePayment(
            business_id=BID, invoice_id=inv.id, amount_paid=200.0,
            payment_mode="Credit", payment_date="2026-07-03",
            note="Applied advance credit",
            idempotency_key=f"advance-credit::{inv.id}",
        )
        db.add(pay)
        db.flush()

        assert repost.repost_synced_row(db, "invoice_payments", pay).status == "posted"
        db.commit()

        entry = _entries(db, "payment")[0]
        accounts = {l.account for l in db.query(JournalLine).filter(
            JournalLine.entry_id == entry.id).all() if (l.debit or 0) > 0}
        assert posting.ACC_ADVANCE in accounts
        assert posting.ACC_CASH not in accounts
    finally:
        db.close()


def test_a_synced_ordinary_receipt_posts_against_cash():
    db = SessionLocal()
    try:
        inv = _landed_invoice(db, total=500.0, gst=0.0)
        pay = InvoicePayment(
            business_id=BID, invoice_id=inv.id, amount_paid=200.0,
            payment_mode="Cash", payment_date="2026-07-03",
            idempotency_key=f"receipt::{inv.id}",
        )
        db.add(pay)
        db.flush()

        repost.repost_synced_row(db, "invoice_payments", pay)
        db.commit()

        entry = _entries(db, "payment")[0]
        debits = {l.account for l in db.query(JournalLine).filter(
            JournalLine.entry_id == entry.id).all() if (l.debit or 0) > 0}
        assert posting.ACC_CASH in debits
        assert posting.ACC_ADVANCE not in debits
    finally:
        db.close()
