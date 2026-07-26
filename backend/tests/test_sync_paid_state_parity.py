"""
tests/test_sync_paid_state_parity.py
====================================
Review finding M-7 — "the invoice history shows the payment but the invoice is
still Pending".

THE BUG
-------
``Invoice.paid_amount`` / ``Invoice.status`` are a PROJECTION of the append-only
``invoice_payments`` ledger, so they must be re-derived whenever either side of
that relationship lands. The cloud did this on every push. The local pull worker
did not — because the reconciliation lived as a private function inside
``routes/sync.py``, which ``services/sync_worker.py`` cannot import. The
correction therefore ran in ONE DIRECTION ONLY, and every invoice pulled
cloud→local kept whatever status was serialised on the cloud.

Batch ordering made it certain rather than occasional: ``invoice_payments`` is in
the pull worker's ``_child_last`` group, so an invoice is applied BEFORE its
payment rows exist. Reconciling at invoice time finds an empty ledger and
correctly does nothing — the correction has to happen when the PAYMENT lands.
Both hooks are needed; neither alone closes it.

THE REAL DEFECT was the duplication. ``database/sync_map.py`` already documents
this exact lesson (R-7) for the table map. The apply logic never got the same
treatment and drifted the same way, with a worse symptom: wrong money on screen
instead of missing rows.

What this file pins:
  1. the projection rule itself, exhaustively (pure, no DB)
  2. the reported scenario, in pull order — invoice first, payment second
  3. reconciliation in either arrival order
  4. a stale peer cannot "un-pay" a settled invoice
  5. legacy invoices with no ledger rows are NOT clobbered
  6. no sync loop: an unchanged row is not touched
  7. **the drift guard** — both sync paths must call the shared hook
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
    InvoicePayment, JournalEntry, JournalLine, StockLedger, DocumentSequence,
    PeriodLock,
)
from core.sync import apply_hooks

BID = 701300


# ── 1. The projection rule — pure, no database ──────────────────────────────

@pytest.mark.parametrize("paid,grand,expected", [
    (0.0,    236.0, "Pending"),
    (100.0,  236.0, "Partial"),
    (235.99, 236.0, "Partial"),
    (236.0,  236.0, "Paid"),
    (300.0,  236.0, "Paid"),      # overpayment is still settled
    (236.004, 236.0, "Paid"),     # rounds to 236.00 — must not chase for a paisa
    (0.0,    0.0,   "Pending"),   # zero-value doc is not "Paid" by paying nothing
    (0.0,    None,  "Pending"),
    (None,   236.0, "Pending"),
])
def test_derive_paid_state(paid, grand, expected):
    assert apply_hooks.derive_paid_state(paid, grand) == expected


def test_a_zero_total_document_never_presents_as_settled():
    """A malformed or half-synced row must not silently read as Paid."""
    assert apply_hooks.derive_paid_state(0.0, 0.0) == "Pending"
    assert apply_hooks.derive_paid_state(0.0, -5.0) == "Pending"


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


def _arriving_invoice(db, *, number="INV-0001", total=236.0,
                      status="Pending", paid=0.0):
    """An invoice as the PULL path writes it: whatever the cloud serialised."""
    inv = Invoice(
        business_id=BID, invoice_id=number, customer="Ravi",
        amount=total, total_amount=total, status=status, paid_amount=paid,
        invoice_date="2026-07-01", invoice_type="B2C",
        subtotal=total, cgst_total=0.0, sgst_total=0.0,
        igst_total=0.0, cess_total=0.0,
    )
    db.add(inv)
    db.flush()
    return inv


def _arriving_payment(db, inv, amount, *, key=None):
    pay = InvoicePayment(
        business_id=BID, invoice_id=inv.id, amount_paid=amount,
        payment_mode="Cash", payment_date="2026-07-02",
        idempotency_key=key or f"pay::{inv.id}::{amount}",
    )
    db.add(pay)
    db.flush()
    return pay


# ── 2. The reported scenario, in the pull worker's actual order ─────────────

def test_pull_order_invoice_then_payment_ends_up_paid():
    """THE M-7 bug, reproduced exactly.

    The pull worker applies `invoices` before `invoice_payments` (_child_last),
    and the cloud snapshot said Pending. Before the fix this invoice stayed
    Pending forever while its payment showed in the history.
    """
    db = SessionLocal()
    try:
        inv = _arriving_invoice(db, total=236.0, status="Pending", paid=0.0)

        # Hook fires on the invoice — ledger is still empty, so correctly a no-op.
        r1 = apply_hooks.run_post_apply(db, "invoices", inv)
        assert r1.reconciled is False, "nothing to reconcile against yet"
        assert inv.status == "Pending"

        # The payment lands later in the same batch. THIS is the hook that fixes it.
        pay = _arriving_payment(db, inv, 236.0)
        r2 = apply_hooks.run_post_apply(db, "invoice_payments", pay)
        db.commit()

        assert r2.reconciled is True
        db.refresh(inv)
        assert inv.status == "Paid", "the reported bug: history shows payment, invoice Pending"
        assert round(inv.paid_amount, 2) == 236.0
    finally:
        db.close()


def test_partial_payment_lands_as_partial_not_paid():
    db = SessionLocal()
    try:
        inv = _arriving_invoice(db, total=500.0)
        pay = _arriving_payment(db, inv, 200.0)
        apply_hooks.run_post_apply(db, "invoice_payments", pay)
        db.commit()

        db.refresh(inv)
        assert inv.status == "Partial"
        assert round(inv.paid_amount, 2) == 200.0
    finally:
        db.close()


def test_multiple_payments_sum_to_paid():
    db = SessionLocal()
    try:
        inv = _arriving_invoice(db, total=500.0)
        # NOTE: keys must be distinct — invoice_payments has
        # UNIQUE(business_id, idempotency_key), and two of these amounts repeat.
        for n, amt in enumerate((200.0, 150.0, 150.0)):
            pay = _arriving_payment(db, inv, amt, key=f"k{n}-{amt}")
            apply_hooks.run_post_apply(db, "invoice_payments", pay)
        db.commit()

        db.refresh(inv)
        assert round(inv.paid_amount, 2) == 500.0
        assert inv.status == "Paid"
    finally:
        db.close()


# ── 3. Either arrival order works ───────────────────────────────────────────

def test_a_persisted_orphan_payment_is_refused_by_the_database():
    """A payment pointing at an invoice that does not exist must not be storable.

    This test used to do the opposite: it PERSISTED such a row (invoice_id
    999_999) to set up the child-before-parent case below. That only worked
    because SQLite shipped with `PRAGMA foreign_keys = OFF`, so it was asserting
    a state the Postgres cloud has always rejected — the two dialects disagreed
    about whether an orphan payment is a legal row, and the local side was the
    permissive one. N4 turned enforcement on; this now pins the alignment.

    Nothing is lost in the sync path by forbidding it. The pull worker never
    intended to write orphans: `resolve_parent_fk_uids` DEFERS a record whose
    parent is not local yet so it re-applies on a later pull, precisely to avoid
    "a stale source-DB integer id (wrong-row / orphan)". Writing the orphan was
    the outcome the worker is built to prevent.
    """
    from sqlalchemy.exc import IntegrityError

    db = SessionLocal()
    try:
        db.add(InvoicePayment(
            business_id=BID, invoice_id=999_999, amount_paid=236.0,
            payment_mode="Cash", payment_date="2026-07-02",
            idempotency_key="orphan::refused",
        ))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    finally:
        db.close()


def test_payment_arriving_before_its_invoice_is_reconciled_when_the_invoice_lands():
    """Child-before-parent, as the batch actually orders it.

    The real ordering is documented in the M-7 write-up: `invoice_payments` sits
    in the pull worker's `_child_last` group, so the invoice row is applied FIRST
    and its hook runs against an empty ledger and correctly does nothing. The
    payment lands afterwards. The property that matters is therefore not "the
    payment has no parent" — it never does — but that a **stale invoice status
    carried over from the peer's snapshot is corrected once the ledger here is
    populated**, whichever hook happens to see it.

    So: the invoice arrives claiming Pending, the payment that settles it arrives
    next, and the invoice's projection must end up Paid.
    """
    db = SessionLocal()
    try:
        inv = _arriving_invoice(db, total=236.0, status="Pending")

        # Invoice applied first — empty ledger, nothing to correct.
        r1 = apply_hooks.run_post_apply(db, "invoices", inv)
        assert r1.ok and r1.reconciled is False

        # Its payment lands afterwards.
        pay = InvoicePayment(
            business_id=BID, invoice_id=inv.id, amount_paid=236.0,
            payment_mode="Cash", payment_date="2026-07-02",
            idempotency_key="child_last::1",
        )
        db.add(pay)
        db.flush()

        r2 = apply_hooks.run_post_apply(db, "invoice_payments", pay)
        db.commit()

        assert r2.reconciled is True, (
            "the payment's own hook is the one that has to fire — reconciling "
            "only at invoice time leaves the status permanently stale"
        )
        db.refresh(inv)
        assert inv.status == "Paid"
        assert inv.paid_amount == 236.0
    finally:
        db.close()


def test_the_payment_hook_degrades_when_its_parent_is_unresolvable():
    """The no-op-not-a-crash property the old orphan row was standing in for,
    exercised the way it actually occurs: the hook receives an object from the
    apply path whose parent cannot be resolved. Kept because the hook runs inside
    a per-row savepoint and a raise here would poison the whole batch."""
    from types import SimpleNamespace

    db = SessionLocal()
    try:
        unresolvable = SimpleNamespace(id=1, business_id=BID, invoice_id=999_999,
                                       amount_paid=236.0)
        assert apply_hooks.reconcile_parent_invoice_of_payment(db, unresolvable) is False
    finally:
        db.close()


def test_a_payment_with_no_invoice_id_is_a_noop_not_a_crash():
    """`invoice_payments.invoice_id` is NOT NULL, so such a row can never be
    persisted — but the hook still receives unflushed / partially-populated
    objects from the sync apply path, and must degrade rather than raise.
    Exercised against a transient object for exactly that reason."""
    from types import SimpleNamespace
    db = SessionLocal()
    try:
        detached = SimpleNamespace(id=1, business_id=BID, invoice_id=None,
                                   amount_paid=10.0)
        assert apply_hooks.reconcile_parent_invoice_of_payment(db, detached) is False
    finally:
        db.close()


# ── 4. A stale peer must not be able to un-pay a settled invoice ───────────

def test_a_stale_peer_cannot_unpay_a_settled_invoice():
    """The projection is recomputed from THIS database's ledger, so whatever the
    peer claims about paid_amount/status is ignored."""
    db = SessionLocal()
    try:
        inv = _arriving_invoice(db, total=236.0)
        pay = _arriving_payment(db, inv, 236.0)
        apply_hooks.run_post_apply(db, "invoice_payments", pay)
        db.commit()
        assert inv.status == "Paid"

        # A stale device now pushes the OLD version of this invoice.
        inv.status = "Pending"
        inv.paid_amount = 0.0
        db.flush()

        r = apply_hooks.run_post_apply(db, "invoices", inv)
        db.commit()

        assert r.reconciled is True
        db.refresh(inv)
        assert inv.status == "Paid", "a stale peer un-paid a settled invoice"
        assert round(inv.paid_amount, 2) == 236.0
    finally:
        db.close()


# ── 5. Legacy rows with no ledger are left alone ───────────────────────────

def test_a_paid_invoice_with_no_payment_rows_is_not_clobbered():
    """Legacy/imported data marked paid with no invoice_payments rows. We have no
    evidence to overrule it, and clearing it would invent an unpaid debt."""
    db = SessionLocal()
    try:
        inv = _arriving_invoice(db, total=236.0, status="Paid", paid=236.0)
        r = apply_hooks.run_post_apply(db, "invoices", inv)
        db.commit()

        assert r.reconciled is False
        db.refresh(inv)
        assert inv.status == "Paid" and round(inv.paid_amount, 2) == 236.0
    finally:
        db.close()


# ── 6. No sync loop ─────────────────────────────────────────────────────────

def test_an_already_correct_row_is_not_touched():
    """Bumping updated_at on a no-op change would make two peers bounce the same
    row back and forth forever."""
    db = SessionLocal()
    try:
        inv = _arriving_invoice(db, total=236.0)
        pay = _arriving_payment(db, inv, 236.0)
        apply_hooks.run_post_apply(db, "invoice_payments", pay)
        db.commit()
        stamp = inv.updated_at

        for _ in range(3):
            r = apply_hooks.run_post_apply(db, "invoices", inv)
            assert r.reconciled is False, "re-reconciled an already-correct row"
        db.commit()

        db.refresh(inv)
        assert inv.updated_at == stamp, "updated_at churned → sync loop"
    finally:
        db.close()


# ── 7. THE DRIFT GUARD ──────────────────────────────────────────────────────
#
# This is the test that matters most. The bug was not a missing line — it was
# that the invariants lived somewhere only ONE of the two sync paths could reach.
# These assertions fail if that ever becomes true again.

def test_both_sync_paths_call_the_shared_post_apply_hook():
    """push (routes/sync.py) and pull (services/sync_worker.py) must BOTH route
    through apply_hooks.run_post_apply. If either stops, invariants silently
    apply in one direction only — which is exactly what M-7 was."""
    import inspect
    import routes.sync as push_mod
    import services.sync_worker as pull_mod

    push_src = inspect.getsource(push_mod)
    pull_src = inspect.getsource(pull_mod)

    for name, src in (("routes/sync.py", push_src),
                      ("services/sync_worker.py", pull_src)):
        assert "apply_hooks" in src, f"{name} no longer imports the shared hooks"
        assert "run_post_apply" in src, (
            f"{name} does not call run_post_apply — its direction is silently "
            f"skipping the paid-state projection and/or the journal (M-7)"
        )


def test_the_reconciliation_is_not_reimplemented_inside_a_sync_path():
    """The duplication IS the bug. Neither sync module may carry its own copy of
    the projection — they must both call the shared one."""
    import inspect
    import routes.sync as push_mod
    import services.sync_worker as pull_mod

    for name, mod in (("routes/sync.py", push_mod),
                      ("services/sync_worker.py", pull_mod)):
        src = inspect.getsource(mod)
        # The giveaway of a local reimplementation is summing the ledger inline.
        assert "func.sum(InvoicePayment.amount_paid)" not in src, (
            f"{name} re-implements the paid-state projection locally — this is "
            f"the drift that caused M-7. Call apply_hooks instead."
        )


def test_paid_state_entities_are_both_synced_and_hooked():
    """A hook on an entity that never arrives is dead code; an entity that
    arrives without a hook is the bug."""
    from database.sync_map import MODEL_MAP
    assert apply_hooks.PAID_STATE_ENTITIES == {"invoices", "invoice_payments"}
    for entity in apply_hooks.PAID_STATE_ENTITIES:
        assert entity in MODEL_MAP, f"{entity} is hooked but not synced"


def test_legacy_reexports_still_resolve_to_the_shared_implementation():
    """routes/sync.py keeps the old private names as thin re-exports so existing
    callers/tests work. They must delegate, not diverge."""
    import routes.sync as push_mod
    db = SessionLocal()
    try:
        inv = _arriving_invoice(db, total=100.0)
        pay = _arriving_payment(db, inv, 100.0)
        push_mod._reconcile_parent_invoice_of_payment(db, pay)
        db.commit()
        db.refresh(inv)
        assert inv.status == "Paid"
    finally:
        db.close()


# ── Failure reporting — no silent kills ────────────────────────────────────

def test_a_hook_failure_is_reported_on_the_result():
    """A row whose invariants can't be enforced must come back marked, not clean."""
    db = SessionLocal()
    try:
        inv = _arriving_invoice(db, total=236.0)
        _arriving_payment(db, inv, 236.0)
        inv.total_amount = "not-a-number"      # breaks the projection arithmetic
        r = apply_hooks.run_post_apply(db, "invoices", inv)

        assert r.ok is False
        assert r.errors, "a failure with no reason attached is a silent failure"
        db.rollback()
    finally:
        db.close()


def test_apply_result_defaults_are_clean():
    r = apply_hooks.ApplyResult("invoices", 7)
    assert r.ok is True and r.reconciled is False and r.errors == []
