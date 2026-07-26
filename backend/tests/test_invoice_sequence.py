"""
tests/test_invoice_sequence.py
==============================
Review finding F-3 — invoice numbers must never be reissued.

THE BUG
-------
``_next_invoice_number`` was ``COUNT(invoices in series) + 1``. A count is a
function of the rows that exist RIGHT NOW, so deleting an invoice made the next
sale mint a number that had already been issued. Rule 46 of the CGST Rules
requires a tax invoice's serial number to be unique for the financial year, so
that is a compliance breach — and it silently produces two different bills
sharing one number rather than failing loudly.

WHAT THIS FILE PINS
-------------------
  • a deletion NEVER rewinds the counter (the regression test)
  • an existing install continues its series instead of restarting at 1
  • each counter's series advances independently (§9.3 multi-terminal POS)
  • a counter that rows from elsewhere leapfrogged heals FORWARD, never back
  • a rolled-back sale releases its reservation (a failure leaves no gap)
  • credit notes get the same guarantee on their own ``CN`` series
  • ``peek_number`` previews without consuming

Gaps are deliberately NOT tested as a failure: a gap is legal and auditable, a
reused number is neither. See core/billing/sequence.py.

Pure DB unit test.
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
from core.models import (
    StockLedger, InvoicePayment, JournalEntry, JournalLine, DocumentSequence,
)
from core.billing import commands as billing
from core.billing import sequence as SEQ
from core.stock import ledger as SL

BID = 700900


# ---------------------------------------------------------------------------
# PURE HELPERS — no DB
# ---------------------------------------------------------------------------

def test_normalize_series_folds_the_separator():
    # "C1" and "C1-" are the SAME terminal; if they normalised differently the
    # terminal would silently run two counters and reissue numbers.
    assert SEQ.normalize_series("C1") == "C1"
    assert SEQ.normalize_series("C1-") == "C1"
    assert SEQ.normalize_series("  C1-  ") == "C1"
    # Unspecified callers fall back to the legacy single-counter series.
    assert SEQ.normalize_series(None) == "INV"
    assert SEQ.normalize_series("") == "INV"
    assert SEQ.normalize_series("-") == "INV"


def test_format_number_zero_pads_and_overflows_gracefully():
    assert SEQ.format_number("INV", 1) == "INV-0001"
    assert SEQ.format_number("C1", 42) == "C1-0042"
    # Past the pad width the number simply gets wider — still unique, still sorts.
    assert SEQ.format_number("INV", 123456) == "INV-123456"


def test_suffix_of_is_strict_about_series_membership():
    assert SEQ.suffix_of("INV-0007", "INV") == 7
    assert SEQ.suffix_of("LCL-C1-0005", "LCL-C1") == 5
    # "LCL-C1-0005" belongs to LCL-C1, NOT to C1 — counting it as a C1 member
    # would let one series drag another's counter forward.
    assert SEQ.suffix_of("LCL-C1-0005", "C1") is None
    assert SEQ.suffix_of("INV-0007", "C1") is None
    assert SEQ.suffix_of("INV-2026-A", "INV") is None      # non-numeric tail
    assert SEQ.suffix_of("INV0007", "INV") is None         # no separator
    assert SEQ.suffix_of(None, "INV") is None
    assert SEQ.suffix_of("INV-0007", "") is None


def test_max_suffix_ignores_foreign_and_malformed_numbers():
    numbers = ["INV-0003", "INV-0011", "C1-0099", "INV-BAD", None, "", "INV-0007"]
    assert SEQ.max_suffix(numbers, "INV") == 11
    assert SEQ.max_suffix(numbers, "C1") == 99
    assert SEQ.max_suffix(numbers, "C2") == 0
    assert SEQ.max_suffix([], "INV") == 0
    assert SEQ.max_suffix(None, "INV") == 0


def test_like_prefix_escapes_wildcards_in_owner_configured_series():
    # counter_prefix is owner-typed, so an underscore would otherwise act as a
    # single-character wildcard and scan a neighbouring series.
    assert SEQ.like_prefix("C1") == "C1-%"
    assert SEQ.like_prefix("C_1") == "C\\_1-%"
    assert SEQ.like_prefix("A%B") == "A\\%B-%"


# ---------------------------------------------------------------------------
# DB FIXTURES
# ---------------------------------------------------------------------------

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
        ent = [r.id for r in db.query(JournalEntry.id).filter(JournalEntry.business_id == BID).all()]
        if ent:
            db.query(JournalLine).filter(
                JournalLine.entry_id.in_(ent)).delete(synchronize_session=False)
        db.query(JournalEntry).filter(JournalEntry.business_id == BID).delete()
        db.query(Invoice).filter(Invoice.business_id == BID).delete()
        db.query(StockLedger).filter(StockLedger.business_id == BID).delete()
        db.query(Inventory).filter(Inventory.business_id == BID).delete()
        db.query(Product).filter(Product.business_id == BID).delete()
        db.query(DocumentSequence).filter(DocumentSequence.business_id == BID).delete()
        db.query(User).filter(User.id == BID).delete()
        db.commit()
    finally:
        db.close()


def _product(name="Rice", stock=1000):
    db = SessionLocal()
    try:
        p = Product(business_id=BID, name=name, hsn_sac="1006", unit="Nos",
                    cgst_rate=9.0, sgst_rate=9.0, igst_rate=18.0, track_inventory=True)
        db.add(p)
        db.flush()
        db.add(Inventory(business_id=BID, product_name=name, product_id=p.id, stock=stock))
        SL.record_movement(db, business_id=BID, movement_type=SL.OPENING,
                           qty_delta=stock, product_id=p.id, product_name=name,
                           update_cache=False)
        db.commit()
        return p.id
    finally:
        db.close()


def _sale(db, pid, **kw):
    return billing.create_sale_invoice(
        db, business_id=BID, place_of_supply="29",
        lines=[{"product_id": pid, "quantity": 1, "unit_price": 100}], **kw)


def _delete_invoice(db, inv_id: int):
    """Hard-delete one invoice and its dependents, as a data purge would.

    Evicts the row from the session afterwards. SQLite reuses rowids, so the next
    INSERT can take the deleted id — and if the old object is still in the
    identity map, SQLAlchemy warns ("Identity map already had an identity for
    ...") and the stale object silently starts reflecting the NEW row. That is
    what made an earlier version of the regression test below compare a value
    with itself and pass vacuously.
    """
    db.query(InvoiceLineItem).filter(
        InvoiceLineItem.invoice_id == inv_id).delete(synchronize_session=False)
    db.query(InvoicePayment).filter(
        InvoicePayment.invoice_id == inv_id).delete(synchronize_session=False)
    db.query(Invoice).filter(Invoice.id == inv_id).delete(synchronize_session=False)
    db.commit()
    stale = db.identity_map.get((Invoice, (inv_id,), None))
    if stale is not None:
        db.expunge(stale)


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


# ---------------------------------------------------------------------------
# THE REGRESSION — F-3
# ---------------------------------------------------------------------------

def test_deleting_an_invoice_never_reissues_its_number():
    """THE F-3 bug. Under COUNT-based numbering this returned INV-0003 twice."""
    pid = _product()
    db = SessionLocal()
    try:
        a = _sale(db, pid)
        b = _sale(db, pid)
        c = _sale(db, pid)
        assert [a.invoice_id, b.invoice_id, c.invoice_id] == [
            "INV-0001", "INV-0002", "INV-0003"]

        # Capture the number as a STRING before deleting. SQLite reuses rowids,
        # so the next insert can take the deleted row's id — and `c` is still in
        # the session's identity map, so reading `c.invoice_id` afterwards
        # silently returns the NEW row's number. Comparing two ORM objects across
        # a delete is what made this assertion compare a value with itself.
        deleted_number = str(c.invoice_id)
        deleted_id = c.id

        # The owner voids/purges the last bill. COUNT drops from 3 to 2...
        _delete_invoice(db, deleted_id)
        assert db.query(Invoice).filter(Invoice.business_id == BID).count() == 2

        # ...but the counter is stored, not derived, so the next sale must NOT
        # be handed INV-0003 again. A gap is legal; a reused number is not.
        d = _sale(db, pid)
        assert d.invoice_id == "INV-0004"
        assert d.invoice_id != deleted_number
    finally:
        db.close()


def test_deleting_every_invoice_still_never_rewinds_the_counter():
    """The extreme case: an empty invoices table must not reset numbering."""
    pid = _product()
    db = SessionLocal()
    try:
        first = _sale(db, pid)
        second = _sale(db, pid)
        assert second.invoice_id == "INV-0002"

        _delete_invoice(db, first.id)
        _delete_invoice(db, second.id)
        assert db.query(Invoice).filter(Invoice.business_id == BID).count() == 0

        after = _sale(db, pid)
        assert after.invoice_id == "INV-0003"
        assert SEQ.current_value(db, BID, "INV") == 3
    finally:
        db.close()


# ---------------------------------------------------------------------------
# UPGRADE PATH — an install already carrying numbers
# ---------------------------------------------------------------------------

def test_counter_seeds_from_existing_invoices_instead_of_restarting_at_one():
    """Existing books, no counter row yet — the first allocation must continue
    the series. Restarting at 1 would collide with every number ever issued."""
    pid = _product()
    db = SessionLocal()
    try:
        # Pre-existing rows, written without touching the sequence (the state a
        # mid-life upgrade finds on disk).
        for n in (1, 2, 3, 7):
            db.add(Invoice(business_id=BID, invoice_id=f"INV-{n:04d}",
                           amount=100.0, status="Paid", invoice_date="2026-07-01"))
        db.commit()
        assert SEQ.current_value(db, BID, "INV") == 0    # no counter row yet

        nxt = _sale(db, pid)
        assert nxt.invoice_id == "INV-0008"              # max(7) + 1, not 0001
    finally:
        db.close()


def test_seed_ignores_numbers_from_other_series():
    pid = _product()
    db = SessionLocal()
    try:
        db.add(Invoice(business_id=BID, invoice_id="C1-0099", amount=100.0,
                       status="Paid", invoice_date="2026-07-01"))
        db.add(Invoice(business_id=BID, invoice_id="LCL-INV-0055", amount=100.0,
                       status="Paid", invoice_date="2026-07-01"))
        db.commit()
        # Neither row belongs to the INV series, so INV starts clean at 1.
        assert _sale(db, pid).invoice_id == "INV-0001"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PER-COUNTER SERIES (§9.3)
# ---------------------------------------------------------------------------

def test_each_counter_advances_its_own_series():
    pid = _product()
    db = SessionLocal()
    try:
        assert _sale(db, pid, counter_prefix="C1").invoice_id == "C1-0001"
        assert _sale(db, pid, counter_prefix="C2").invoice_id == "C2-0001"
        assert _sale(db, pid, counter_prefix="C1").invoice_id == "C1-0002"
        # Trailing '-' is the same terminal, not a third counter.
        assert _sale(db, pid, counter_prefix="C2-").invoice_id == "C2-0002"
        assert SEQ.current_value(db, BID, "C1") == 2
        assert SEQ.current_value(db, BID, "C2") == 2
        assert SEQ.current_value(db, BID, "INV") == 0
    finally:
        db.close()


def test_deleting_one_counters_bill_does_not_touch_another_counter():
    pid = _product()
    db = SessionLocal()
    try:
        c1 = _sale(db, pid, counter_prefix="C1")
        _sale(db, pid, counter_prefix="C2")
        _delete_invoice(db, c1.id)
        assert _sale(db, pid, counter_prefix="C1").invoice_id == "C1-0002"
        assert _sale(db, pid, counter_prefix="C2").invoice_id == "C2-0002"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# HEALING — rows the counter never issued
# ---------------------------------------------------------------------------

def test_counter_heals_forward_past_numbers_it_never_issued():
    """A cloud pull / import / hand-typed number can land ahead of the counter.
    The allocator must jump past it in one hop, not reissue it."""
    pid = _product()
    db = SessionLocal()
    try:
        assert _sale(db, pid).invoice_id == "INV-0001"    # counter now at 1

        # Rows arriving from elsewhere, well ahead of the counter.
        for n in (2, 3, 4, 9):
            db.add(Invoice(business_id=BID, invoice_id=f"INV-{n:04d}",
                           amount=100.0, status="Paid", invoice_date="2026-07-01"))
        db.commit()

        nxt = _sale(db, pid)
        assert nxt.invoice_id == "INV-0010"               # healed to max(9) + 1
        assert SEQ.current_value(db, BID, "INV") == 10
    finally:
        db.close()


def test_healing_never_lowers_the_counter():
    """Healing repairs a counter that is BEHIND. It must never drag one back."""
    pid = _product()
    db = SessionLocal()
    try:
        for _ in range(5):
            _sale(db, pid)
        assert SEQ.current_value(db, BID, "INV") == 5

        # Every invoice is purged — the observed max collapses to 0.
        for row in db.query(Invoice).filter(Invoice.business_id == BID).all():
            _delete_invoice(db, row.id)

        assert _sale(db, pid).invoice_id == "INV-0006"
        assert SEQ.current_value(db, BID, "INV") == 6
    finally:
        db.close()


def test_reserve_with_a_floor_only_ever_moves_up():
    db = SessionLocal()
    try:
        SEQ._ensure_row(db, BID, "T1", seed=0)
        assert SEQ._reserve(db, BID, "T1") == 1
        assert SEQ._reserve(db, BID, "T1", floor=50) == 50     # jumped forward
        assert SEQ._reserve(db, BID, "T1", floor=10) == 51     # floor below → +1
        assert SEQ._reserve(db, BID, "T1") == 52
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# TRANSACTION SEMANTICS
# ---------------------------------------------------------------------------

def test_rollback_releases_the_reservation():
    """The reservation lives in the caller's transaction, so a failed sale
    leaves no gap — the number is handed out again on the next attempt."""
    db = SessionLocal()
    try:
        SEQ._ensure_row(db, BID, "INV", seed=0)
        assert SEQ._reserve(db, BID, "INV") == 1
        db.rollback()
    finally:
        db.close()

    db = SessionLocal()
    try:
        assert SEQ.current_value(db, BID, "INV") == 0
    finally:
        db.close()


def test_a_blocked_sale_does_not_burn_a_number():
    """Negative-stock block raises before commit → number not consumed."""
    import json
    pid = _product(stock=1)
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.id == BID).first()
        owner.settings = json.dumps({"transactions": {"prevent_negative_stock": True}})
        db.commit()

        with pytest.raises(ValueError):
            billing.create_sale_invoice(
                db, business_id=BID, place_of_supply="29",
                lines=[{"product_id": pid, "quantity": 99, "unit_price": 100}])
        db.rollback()

        owner = db.query(User).filter(User.id == BID).first()
        owner.settings = None
        db.commit()

        # The rejected sale reserved nothing that survived, so the first
        # successful bill is still INV-0001.
        assert _sale(db, pid).invoice_id == "INV-0001"
    finally:
        db.close()


def test_allocations_are_distinct_and_monotonic_across_sessions():
    """Two sessions interleaving allocations must never see the same value."""
    a, b = SessionLocal(), SessionLocal()
    try:
        SEQ._ensure_row(a, BID, "INV", seed=0)
        a.commit()
        seen = []
        for _ in range(10):
            for db in (a, b):
                seen.append(SEQ._reserve(db, BID, "INV"))
                db.commit()
        assert seen == list(range(1, 21))
        assert len(set(seen)) == len(seen)
    finally:
        a.close()
        b.close()


# ---------------------------------------------------------------------------
# CREDIT NOTES — same guarantee, own series
# ---------------------------------------------------------------------------

def test_credit_note_number_is_not_reused_after_a_deletion():
    pid = _product()
    db = SessionLocal()
    try:
        inv = _sale(db, pid)
        cn1 = billing.create_credit_note(
            db, business_id=BID, original_invoice_id=inv.id,
            lines=[{"product_id": pid, "qty": 1}])
        assert cn1.invoice_id == "CN-0001"

        _delete_invoice(db, cn1.id)
        cn2 = billing.create_credit_note(
            db, business_id=BID, original_invoice_id=inv.id,
            lines=[{"product_id": pid, "qty": 1}])
        assert cn2.invoice_id == "CN-0002"      # not CN-0001 again
    finally:
        db.close()


def test_credit_notes_do_not_consume_sale_numbers():
    pid = _product()
    db = SessionLocal()
    try:
        inv = _sale(db, pid)
        billing.create_credit_note(
            db, business_id=BID, original_invoice_id=inv.id,
            lines=[{"product_id": pid, "qty": 1}])
        assert _sale(db, pid).invoice_id == "INV-0002"
        assert SEQ.current_value(db, BID, "CN") == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# PREVIEW
# ---------------------------------------------------------------------------

def test_peek_previews_without_consuming():
    pid = _product()
    db = SessionLocal()
    try:
        assert SEQ.peek_number(db, BID, "INV") == "INV-0001"
        assert SEQ.peek_number(db, BID, "INV") == "INV-0001"   # still not consumed
        assert _sale(db, pid).invoice_id == "INV-0001"
        assert SEQ.peek_number(db, BID, "INV") == "INV-0002"
    finally:
        db.close()
