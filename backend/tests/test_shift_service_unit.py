"""
tests/test_shift_service_unit.py — direct unit coverage of the cash drawer.
==========================================================================
`core/shifts/service.py` was the largest genuinely-untested money surface left
after the July audit (review §32). Measured, not asserted: of its 13 functions,
**11 had no reference anywhere in the test corpus** — `get_open_shift`,
`require_open_shift`, `suggested_opening_cash`, `open_shift`,
`record_cash_movement`, `_movement_sums`, `compute_tally`, `close_shift`,
`movement_out`, `list_movements`, `shift_out`. `tests/test_shifts.py` exercises
the lifecycle over HTTP, which is valuable and orthogonal, but it asserts on
route payloads: it cannot pin the drawer arithmetic, and it never once names the
functions that do it.

Why the drawer specifically matters, and why it belongs with the M-2/M-7 class of
findings rather than below it: the tally is what a cashier is held to at the end
of a shift. If `expected_cash` is wrong, an honest cashier is short and a
dishonest one is covered, and — like M-2 and M-7 — **nothing looks broken**. The
POS rings up fine, the invoice is correct, the journal balances. The error lives
only in the reconciliation between them.

Deliberate choices in this file:

· Calls go to the SERVICE, not through HTTP. A route test cannot distinguish
  "the tally is right" from "the route happens to return the number the test
  computed the same wrong way".
· Every rule in the module docstring's tally definition gets an assertion,
  including the two that are easiest to get wrong and most expensive to get
  wrong: audit-only movements must NEVER enter the tally, and an unrecognised
  payment mode must NEVER fall into the cash bucket.
· Where a behaviour is defensible-but-surprising it is pinned WITH the reasoning,
  rather than being quietly avoided.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from database.db import SessionLocal
from database.models import Invoice, RegisterShift, ShiftCashMovement, User
from core.models import InvoicePayment, Expense
from core.shifts import service as S
from services.dates import utc_now


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture()
def biz(db):
    """A throwaway business + operator. Uses a real `users` row because
    RegisterShift.user_id is a FK to it."""
    u = User(
        username=f"drawer_{uuid.uuid4().hex[:10]}",
        password="x",
        business_name="Drawer Test Co",
        role="owner",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    yield {"bid": u.id, "uid": u.id}
    # Children first: shifts and movements FK to the user.
    db.query(ShiftCashMovement).filter(ShiftCashMovement.business_id == u.id).delete()
    db.query(InvoicePayment).filter(InvoicePayment.business_id == u.id).delete()
    db.query(Invoice).filter(Invoice.business_id == u.id).delete()
    db.query(RegisterShift).filter(RegisterShift.business_id == u.id).delete()
    db.query(Expense).filter(Expense.business_id == u.id).delete()
    db.commit()
    db.delete(u)
    db.commit()


def _invoice(db, biz, amount):
    """A minimal invoice to hang receipts on.

    `invoice_payments.invoice_id` is NOT NULL — the payment ledger is
    deliberately never free-floating — so a receipt needs a parent even for a
    drawer test. Numbers are allocated by hand rather than through
    `create_sale_invoice` so these stay unit tests of the DRAWER: the tally reads
    `invoice_payments`, and routing through the billing command would make a
    failure here ambiguous between the two modules.
    """
    inv = Invoice(
        business_id=biz["bid"],
        invoice_id=f"DRW-{uuid.uuid4().hex[:8]}",
        customer="Drawer Test Customer",
        amount=amount,
        total_amount=amount,
        status="PAID",
        invoice_date=utc_now().strftime("%Y-%m-%d"),
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def _receipt(db, biz, shift, amount, mode="cash"):
    """A payment stamped with this shift — the only thing the tally reads."""
    inv = _invoice(db, biz, amount)
    p = InvoicePayment(
        business_id=biz["bid"],
        invoice_id=inv.id,
        amount_paid=amount,
        payment_mode=mode,
        payment_date=utc_now(),
        shift_id=shift.id,
    )
    db.add(p)
    db.commit()
    return p


# ── _round2 ──────────────────────────────────────────────────────────────────

def test_round2_handles_none_and_the_float_epsilon():
    """The `+ 1e-9` nudge exists so a value that is a hair under a paisa
    boundary rounds the way a human counting cash would. Pinned because it is
    the kind of line a later cleanup deletes as noise."""
    assert S._round2(None) == 0.0
    assert S._round2(0) == 0.0
    assert S._round2(10.005) == 10.01
    assert S._round2(2.675) == 2.68          # naive round() gives 2.67
    assert S._round2("12.3456") == 12.35     # tolerates a string amount
    assert S._round2(-5.555) == -5.55


def test_round2_never_returns_more_than_two_decimals():
    for v in (1 / 3, 2 / 3, 1e-9, 99999.999, 0.145, 0.155):
        r = S._round2(v)
        assert r == round(r, 2)


# ── _norm_mode ───────────────────────────────────────────────────────────────

def test_norm_mode_buckets_every_known_wallet_as_upi():
    for m in ("upi", "UPI", " GPay ", "phonepe", "PAYTM", "qr"):
        assert S._norm_mode(m) == "upi", m


def test_norm_mode_recognises_cards_separately_from_upi():
    for m in ("card", "Credit Card", "DEBIT CARD"):
        assert S._norm_mode(m) == "card", m


def test_norm_mode_defaults_missing_to_cash_but_unknown_to_other():
    """The single most consequential branch in this module.

    A MISSING mode defaults to cash — correct, because the counter's default
    tender is cash and legacy rows predate the column.

    An UNRECOGNISED mode must go to `other`, NOT cash. If a new tender
    ("wallet", "netbanking", a typo) silently landed in the cash bucket, the
    drawer would be expected to contain money that never entered it and the
    cashier would show a false shortfall every single shift.
    """
    assert S._norm_mode(None) == "cash"
    assert S._norm_mode("") == "cash"
    assert S._norm_mode("   ") == "cash"
    for unknown in ("wallet", "netbanking", "cheque", "bank_transfer", "csh", "store_credit"):
        assert S._norm_mode(unknown) == "other", unknown


def test_norm_mode_output_domain_matches_the_tally_buckets():
    """Whatever `_norm_mode` returns is used directly as a dict key in
    `compute_tally`. A new return value would raise KeyError on a live sale."""
    buckets = {"cash", "upi", "card", "other"}
    samples = [None, "", "cash", "upi", "gpay", "card", "debit card", "wallet", "??"]
    assert {S._norm_mode(s) for s in samples} <= buckets


# ── Category vocabularies ────────────────────────────────────────────────────

def test_category_vocabularies_do_not_overlap():
    """`_movement_sums` excludes AUDIT_ONLY by name. If a category were in both
    an in/out set and the audit-only set, whether it hit the tally would depend
    on set-iteration order."""
    assert not (S.PAID_IN_CATEGORIES & S.AUDIT_ONLY_CATEGORIES)
    assert not (S.PAID_OUT_CATEGORIES & S.AUDIT_ONLY_CATEGORIES)
    assert not (S.PAID_IN_CATEGORIES & S.PAID_OUT_CATEGORIES)


def test_removal_destinations_are_a_subset_of_paid_out():
    """A closing removal is money leaving the drawer, so its destination has to
    be a legitimate paid-out reason."""
    assert S.REMOVAL_DESTINATIONS <= S.PAID_OUT_CATEGORIES


def test_expense_is_a_paid_out_category():
    """`record_cash_movement` special-cases 'expense' to also write an Expense
    row and post it. If it ever left PAID_OUT_CATEGORIES the validation branch
    would reject it before that code could run."""
    assert "expense" in S.PAID_OUT_CATEGORIES


# ── get_open_shift / require_open_shift ──────────────────────────────────────

def test_get_open_shift_returns_none_with_no_history(db, biz):
    assert S.get_open_shift(db, business_id=biz["bid"], user_id=biz["uid"]) is None


def test_require_open_shift_raises_the_exact_sentinel(db, biz):
    """Routes map this string to 409. A reworded message becomes a 500."""
    with pytest.raises(ValueError) as e:
        S.require_open_shift(db, business_id=biz["bid"], user_id=biz["uid"])
    assert str(e.value) == "shift_required"


def test_get_open_shift_is_scoped_to_business_and_user(db, biz):
    """Two operators sharing a counter must not see each other's drawer, and
    neither must a different business."""
    other = User(username=f"drawer_{uuid.uuid4().hex[:10]}", password="x",
                 business_name="Other Co", role="owner")
    db.add(other)
    db.commit()
    db.refresh(other)
    try:
        mine = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=100.0)
        assert S.get_open_shift(db, business_id=biz["bid"], user_id=biz["uid"]).id == mine.id
        # Same user id, different business → nothing.
        assert S.get_open_shift(db, business_id=other.id, user_id=biz["uid"]) is None
        # Same business, different user → nothing.
        assert S.get_open_shift(db, business_id=biz["bid"], user_id=other.id) is None
    finally:
        db.query(ShiftCashMovement).filter(ShiftCashMovement.business_id == other.id).delete()
        db.query(RegisterShift).filter(RegisterShift.business_id == other.id).delete()
        db.commit()
        db.delete(other)
        db.commit()


def test_get_open_shift_ignores_closed_shifts(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=50.0)
    S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"], closing_cash_actual=50.0)
    assert S.get_open_shift(db, business_id=biz["bid"], user_id=biz["uid"]) is None


# ── open_shift ───────────────────────────────────────────────────────────────

def test_open_shift_rejects_negative_and_none_float(db, biz):
    for bad in (-0.01, -100):
        with pytest.raises(ValueError, match="zero or positive"):
            S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=bad)
    with pytest.raises(ValueError, match="zero or positive"):
        S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=None)


def test_open_shift_accepts_a_zero_float(db, biz):
    """Zero is legitimate — a counter that starts empty. Rejecting it would
    force cashiers to invent a number."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0)
    assert sh.opening_cash == 0.0
    assert sh.status == "OPEN"


def test_open_shift_refuses_a_second_open_shift(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=10.0)
    with pytest.raises(ValueError) as e:
        S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=10.0)
    assert str(e.value) == "shift_already_open"


def test_first_ever_shift_has_no_expectation_and_no_variance(db, biz):
    """With no prior shift there is nothing to carry forward, so
    `opening_expected` must be NULL rather than 0 — 'unknown' and 'the drawer
    was empty' are different claims, and recording a variance against a guess
    would invent a discrepancy."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=750.0)
    assert sh.opening_expected is None
    assert db.query(ShiftCashMovement).filter(
        ShiftCashMovement.shift_id == sh.id).count() == 0


# ── suggested_opening_cash / carry-forward ───────────────────────────────────

def test_suggested_opening_cash_with_no_history(db, biz):
    out = S.suggested_opening_cash(db, business_id=biz["bid"], user_id=biz["uid"])
    assert out == {"suggested": None, "source_shift_id": None, "source_end_time": None}


def test_suggestion_is_the_previous_closing_float_not_the_counted_cash(db, biz):
    """The distinction the whole 3b design turns on: the next shift starts with
    what was LEFT, not with what was counted. Suggesting the full count would
    have the cashier expect money that went to the bank."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=1000.0)
    S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                  closing_cash_actual=5000.0, leave_in_drawer=1200.0)
    out = S.suggested_opening_cash(db, business_id=biz["bid"], user_id=biz["uid"])
    assert out["suggested"] == 1200.0
    assert out["source_shift_id"] == sh.id
    assert out["source_end_time"] is not None


def test_suggestion_falls_back_to_counted_cash_for_legacy_shifts(db, biz):
    """Shifts closed before leave-in-drawer existed have `closing_float` NULL.
    Falling back to the counted cash is right; returning None would make every
    legacy install look like it had no history."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=100.0)
    S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"], closing_cash_actual=880.0)
    sh.closing_float = None                       # simulate the legacy row
    db.commit()
    out = S.suggested_opening_cash(db, business_id=biz["bid"], user_id=biz["uid"])
    assert out["suggested"] == 880.0


def test_suggestion_prefers_the_same_operator_then_falls_back_business_wide(db, biz):
    """Multi-counter: each login owns its own drawer, so the same operator's
    history wins. But an owner taking over a cashier's till must still get a
    sensible number, hence the business-wide fallback."""
    cashier = User(username=f"drawer_{uuid.uuid4().hex[:10]}", password="x",
                   business_name="Drawer Test Co", role="staff",
                   parent_business_id=biz["bid"])
    db.add(cashier)
    db.commit()
    db.refresh(cashier)
    try:
        # Cashier closes leaving 300.
        S.open_shift(db, business_id=biz["bid"], user_id=cashier.id, opening_cash=0.0)
        S.close_shift(db, business_id=biz["bid"], user_id=cashier.id,
                      closing_cash_actual=300.0, leave_in_drawer=300.0)
        # Owner has no history of their own → inherits the cashier's float.
        assert S.suggested_opening_cash(
            db, business_id=biz["bid"], user_id=biz["uid"])["suggested"] == 300.0

        # Owner now has their own history → theirs wins.
        S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=300.0)
        S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                      closing_cash_actual=900.0, leave_in_drawer=450.0)
        assert S.suggested_opening_cash(
            db, business_id=biz["bid"], user_id=biz["uid"])["suggested"] == 450.0
        # …and the cashier still sees their own.
        assert S.suggested_opening_cash(
            db, business_id=biz["bid"], user_id=cashier.id)["suggested"] == 300.0
    finally:
        db.query(ShiftCashMovement).filter(ShiftCashMovement.user_id == cashier.id).delete()
        db.query(RegisterShift).filter(RegisterShift.user_id == cashier.id).delete()
        db.commit()
        db.delete(cashier)
        db.commit()


def test_opening_variance_is_recorded_when_the_float_disagrees(db, biz):
    """A float that changed overnight must be visible, not silent."""
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=1000.0)
    S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                  closing_cash_actual=1000.0, leave_in_drawer=1000.0)

    sh2 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=940.0)
    assert sh2.opening_expected == 1000.0
    var = db.query(ShiftCashMovement).filter(
        ShiftCashMovement.shift_id == sh2.id,
        ShiftCashMovement.category == "opening_variance").one()
    assert var.movement_type == "paid_out"        # 60 short
    assert var.amount == 60.0


def test_opening_variance_direction_is_paid_in_when_over(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=500.0)
    S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                  closing_cash_actual=500.0, leave_in_drawer=500.0)
    sh2 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=575.0)
    var = db.query(ShiftCashMovement).filter(
        ShiftCashMovement.shift_id == sh2.id,
        ShiftCashMovement.category == "opening_variance").one()
    assert var.movement_type == "paid_in"
    assert var.amount == 75.0


def test_sub_paisa_float_difference_records_no_variance(db, biz):
    """The `>= 0.005` threshold. Without it, float representation noise would
    file a variance movement on a drawer that matched exactly — audit noise that
    trains operators to ignore variances."""
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=333.33)
    S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                  closing_cash_actual=333.33, leave_in_drawer=333.33)
    sh2 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                       opening_cash=333.331)
    assert db.query(ShiftCashMovement).filter(
        ShiftCashMovement.shift_id == sh2.id,
        ShiftCashMovement.category == "opening_variance").count() == 0


# ── record_cash_movement ─────────────────────────────────────────────────────

def test_movement_requires_an_open_shift(db, biz):
    with pytest.raises(ValueError) as e:
        S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                               movement_type="paid_in", category="change_top_up",
                               amount=100.0)
    assert str(e.value) == "shift_required"


def test_movement_rejects_non_positive_amounts(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    for bad in (0, -1, None):
        with pytest.raises(ValueError, match="greater than 0"):
            S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                                   movement_type="paid_in",
                                   category="change_top_up", amount=bad)


def test_movement_rejects_a_category_from_the_wrong_direction(db, biz):
    """`bank_deposit` is money leaving; accepting it as a paid_in would ADD it to
    the expected drawer — the sign error that turns a deposit into a surplus."""
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    with pytest.raises(ValueError, match="invalid paid_in category"):
        S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                               movement_type="paid_in", category="bank_deposit",
                               amount=100.0)
    with pytest.raises(ValueError, match="invalid paid_out category"):
        S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                               movement_type="paid_out", category="change_top_up",
                               amount=100.0)


def test_movement_rejects_audit_only_categories_from_the_public_api(db, biz):
    """`opening_variance` / `closing_removal` are written by the service itself
    and never enter the tally. If an operator could file one by hand they would
    have a way to move drawer money that reconciliation cannot see."""
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    for cat in sorted(S.AUDIT_ONLY_CATEGORIES):
        for direction in ("paid_in", "paid_out"):
            with pytest.raises(ValueError, match="invalid"):
                S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                                       movement_type=direction, category=cat,
                                       amount=50.0)


def test_movement_rejects_an_unknown_direction(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    with pytest.raises(ValueError, match="paid_in or paid_out"):
        S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                               movement_type="transfer", category="change_top_up",
                               amount=50.0)


def test_expense_movement_creates_a_real_expense_and_links_it(db, biz):
    """The ₹200 drawer tea has to reach the P&L, not just the drawer tally —
    otherwise cash leaves the business with no expense recorded anywhere."""
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=1000.0)
    mv = S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                                movement_type="paid_out", category="expense",
                                amount=200.0, note="Tea",
                                expense_category="Staff Welfare")
    assert mv.expense_id is not None
    exp = db.query(Expense).filter(Expense.id == mv.expense_id).one()
    assert exp.amount == 200.0
    assert exp.category == "Staff Welfare"
    assert exp.payment_mode == "Cash"
    assert exp.expense_type == "Indirect"

    # And it is posted to the journal.
    from core.models import JournalEntry
    entry = db.query(JournalEntry).filter(
        JournalEntry.business_id == biz["bid"],
        JournalEntry.source_type == "expense",
        JournalEntry.source_id == exp.id).one()
    assert entry is not None


def test_expense_movement_defaults_its_category(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=500.0)
    mv = S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                                movement_type="paid_out", category="expense",
                                amount=50.0)
    exp = db.query(Expense).filter(Expense.id == mv.expense_id).one()
    assert exp.category == "Others"


def test_non_expense_movement_creates_no_expense_row(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=500.0)
    before = db.query(Expense).filter(Expense.business_id == biz["bid"]).count()
    mv = S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                                movement_type="paid_out", category="bank_deposit",
                                amount=400.0)
    assert mv.expense_id is None
    assert db.query(Expense).filter(
        Expense.business_id == biz["bid"]).count() == before


# ── _movement_sums ───────────────────────────────────────────────────────────

def test_movement_sums_are_zero_for_an_empty_shift(db, biz):
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=100.0)
    assert S._movement_sums(db, sh) == {"paid_in": 0.0, "paid_out": 0.0}


def test_movement_sums_exclude_audit_only_categories(db, biz):
    """The load-bearing assertion of this whole module. `closing_removal` is
    recorded AFTER the count snapshot; counting it would subtract the bank
    deposit from the expected drawer a second time and report every closed
    shift as short by exactly the amount deposited."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=100.0)
    S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                           movement_type="paid_in", category="change_top_up",
                           amount=500.0)
    S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                           movement_type="paid_out", category="bank_deposit",
                           amount=200.0)
    # Two audit-only rows written directly, as the service writes them.
    for cat in ("opening_variance", "closing_removal"):
        db.add(ShiftCashMovement(business_id=biz["bid"], shift_id=sh.id,
                                 user_id=biz["uid"], movement_type="paid_out",
                                 category=cat, amount=9999.0))
    db.commit()

    assert S._movement_sums(db, sh) == {"paid_in": 500.0, "paid_out": 200.0}


def test_movement_sums_are_scoped_to_one_shift(db, biz):
    sh1 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                           movement_type="paid_in", category="change_top_up",
                           amount=111.0)
    S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                  closing_cash_actual=111.0, leave_in_drawer=111.0)
    sh2 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=111.0)
    S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                           movement_type="paid_in", category="change_top_up",
                           amount=222.0)

    assert S._movement_sums(db, sh1)["paid_in"] == 111.0
    assert S._movement_sums(db, sh2)["paid_in"] == 222.0


# ── compute_tally ────────────────────────────────────────────────────────────

def test_tally_of_a_fresh_shift_is_just_the_float(db, biz):
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=1500.0)
    t = S.compute_tally(db, sh)
    assert t["opening_cash"] == 1500.0
    assert t["expected_cash"] == 1500.0
    assert t["expected_upi"] == 0.0
    assert (t["sales_cash"], t["sales_upi"], t["sales_card"], t["sales_other"]) == \
           (0.0, 0.0, 0.0, 0.0)


def test_tally_matches_the_documented_formula(db, biz):
    """expected_cash = opening + Σcash receipts + Σpaid_in − Σpaid_out.
    Computed independently here, not copied from the implementation."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=1000.0)
    _receipt(db, biz, sh, 2500.0, "cash")
    _receipt(db, biz, sh, 400.0, "cash")
    _receipt(db, biz, sh, 1800.0, "upi")
    S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                           movement_type="paid_in", category="change_top_up",
                           amount=300.0)
    S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                           movement_type="paid_out", category="owner_withdrawal",
                           amount=700.0)

    t = S.compute_tally(db, sh)
    assert t["sales_cash"] == 2900.0
    assert t["sales_upi"] == 1800.0
    assert t["paid_in"] == 300.0
    assert t["paid_out"] == 700.0
    assert t["expected_cash"] == 1000.0 + 2900.0 + 300.0 - 700.0
    assert t["expected_upi"] == 1800.0


def test_upi_and_card_never_enter_the_cash_drawer(db, biz):
    """A card swipe puts nothing in the till. If it did, the cashier would be
    expected to produce cash the customer never handed over."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    _receipt(db, biz, sh, 5000.0, "upi")
    _receipt(db, biz, sh, 3000.0, "card")
    t = S.compute_tally(db, sh)
    assert t["expected_cash"] == 0.0
    assert t["sales_card"] == 3000.0
    assert t["expected_upi"] == 5000.0


def test_unrecognised_mode_lands_in_other_and_not_in_expected_cash(db, biz):
    """The `_norm_mode` guarantee, asserted end-to-end through the tally."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=100.0)
    _receipt(db, biz, sh, 1234.0, "netbanking")
    t = S.compute_tally(db, sh)
    assert t["sales_other"] == 1234.0
    assert t["sales_cash"] == 0.0
    assert t["expected_cash"] == 100.0


def test_tally_treats_a_missing_payment_mode_as_cash(db, biz):
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    _receipt(db, biz, sh, 250.0, None)
    assert S.compute_tally(db, sh)["expected_cash"] == 250.0


def test_tally_counts_credit_collections_taken_during_the_shift(db, biz):
    """A payment against an OLD invoice still lands in today's drawer. The tally
    keys on shift_id, not on invoice date — asserted because keying on the
    invoice would leave collected cash unaccounted for."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    _receipt(db, biz, sh, 4000.0, "cash")     # settlement of an earlier credit sale
    assert S.compute_tally(db, sh)["expected_cash"] == 4000.0


def test_tally_ignores_receipts_stamped_with_another_shift(db, biz):
    sh1 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    _receipt(db, biz, sh1, 900.0, "cash")
    S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"], closing_cash_actual=900.0,
                  leave_in_drawer=0.0)
    sh2 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    _receipt(db, biz, sh2, 50.0, "cash")
    assert S.compute_tally(db, sh1)["expected_cash"] == 900.0
    assert S.compute_tally(db, sh2)["expected_cash"] == 50.0


def test_tally_has_no_side_effects(db, biz):
    """It is documented as a QUERY. A tally that mutated anything would change
    the number a cashier is reconciling against just by being displayed."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=200.0)
    _receipt(db, biz, sh, 300.0, "cash")
    before = (db.query(ShiftCashMovement).count(), db.query(InvoicePayment).count(),
              sh.status, sh.closing_cash_expected)
    for _ in range(3):
        S.compute_tally(db, sh)
    after = (db.query(ShiftCashMovement).count(), db.query(InvoicePayment).count(),
             sh.status, sh.closing_cash_expected)
    assert before == after


def test_tally_is_deterministic(db, biz):
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=77.77)
    _receipt(db, biz, sh, 22.23, "cash")
    assert S.compute_tally(db, sh) == S.compute_tally(db, sh)


# ── close_shift ──────────────────────────────────────────────────────────────

def test_close_requires_an_open_shift(db, biz):
    with pytest.raises(ValueError) as e:
        S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"], closing_cash_actual=0.0)
    assert str(e.value) == "no_open_shift"


def test_close_rejects_negative_or_missing_count(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    for bad in (-1, None):
        with pytest.raises(ValueError, match="zero or positive"):
            S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                          closing_cash_actual=bad)


def test_close_rejects_an_unknown_removal_destination(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    with pytest.raises(ValueError, match="bank_deposit or owner_withdrawal"):
        S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                      closing_cash_actual=100.0, leave_in_drawer=0.0,
                      removal_destination="pocket")


def test_close_rejects_leaving_more_than_was_counted(db, biz):
    """Leaving 900 out of a counted 500 is not a data-entry slip to absorb — it
    would make the next shift's expected float exceed the cash that exists."""
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    with pytest.raises(ValueError, match="between 0 and the counted cash"):
        S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                      closing_cash_actual=500.0, leave_in_drawer=900.0)
    with pytest.raises(ValueError, match="between 0 and the counted cash"):
        S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                      closing_cash_actual=500.0, leave_in_drawer=-1.0)


def test_close_defaults_to_leaving_everything(db, biz):
    """`leave_in_drawer=None` means "no removal", not "remove everything". The
    opposite default would silently bank the till."""
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=100.0)
    sh = S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                       closing_cash_actual=640.0)
    assert sh.closing_float == 640.0
    assert db.query(ShiftCashMovement).filter(
        ShiftCashMovement.shift_id == sh.id,
        ShiftCashMovement.category == "closing_removal").count() == 0


def test_close_records_the_removal_with_its_destination(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=500.0)
    _receipt(db, biz, S.get_open_shift(db, business_id=biz["bid"], user_id=biz["uid"]),
             4500.0, "cash")
    sh = S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                       closing_cash_actual=5000.0, leave_in_drawer=500.0,
                       removal_destination="owner_withdrawal")
    mv = db.query(ShiftCashMovement).filter(
        ShiftCashMovement.shift_id == sh.id,
        ShiftCashMovement.category == "closing_removal").one()
    assert mv.amount == 4500.0
    assert mv.movement_type == "paid_out"
    assert "Owner withdrawal" in mv.note
    assert "500.00" in mv.note


def test_close_snapshots_the_expectation_before_the_removal(db, biz):
    """Order of operations. Reconciliation happens on the FULL count; the
    removal is recorded afterwards and is audit-only. If the removal were
    counted, `closing_cash_expected` would come out short by the deposit and
    every well-run shift would look like a theft."""
    sh0 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=1000.0)
    _receipt(db, biz, sh0, 9000.0, "cash")
    sh = S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                       closing_cash_actual=10000.0, leave_in_drawer=1000.0)
    assert sh.closing_cash_expected == 10000.0     # NOT 10000 − 9000
    assert sh.closing_cash_actual == 10000.0
    assert sh.closing_float == 1000.0


def test_close_stores_expected_actual_and_status(db, biz):
    sh0 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=200.0)
    _receipt(db, biz, sh0, 800.0, "cash")
    _receipt(db, biz, sh0, 1500.0, "upi")
    sh = S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                       closing_cash_actual=990.0, closing_upi_actual=1500.0)
    assert sh.status == "CLOSED"
    assert sh.end_time is not None
    assert sh.closing_cash_expected == 1000.0
    assert sh.closing_cash_actual == 990.0
    assert sh.closing_upi_expected == 1500.0
    assert sh.closing_upi_actual == 1500.0


def test_close_appends_notes_rather_than_replacing_them(db, biz):
    """Append-only spirit: the opening note is part of the audit trail."""
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0,
                 notes="opened by owner")
    sh = S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                       closing_cash_actual=0.0, notes="drawer short, checked twice")
    assert "opened by owner" in sh.notes
    assert "drawer short, checked twice" in sh.notes


def test_closing_a_shift_twice_is_refused(db, biz):
    """Append-only: a closed shift is never reopened or re-closed."""
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"], closing_cash_actual=0.0)
    with pytest.raises(ValueError) as e:
        S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"], closing_cash_actual=0.0)
    assert str(e.value) == "no_open_shift"


# ── Serializers ──────────────────────────────────────────────────────────────

def test_movement_out_shape(db, biz):
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    mv = S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                                movement_type="paid_in", category="change_top_up",
                                amount=25.5, note="coins")
    out = S.movement_out(mv)
    assert out["movement_type"] == "paid_in"
    assert out["category"] == "change_top_up"
    assert out["amount"] == 25.5
    assert out["note"] == "coins"
    assert out["expense_id"] is None
    assert isinstance(out["created_at"], str)


def test_list_movements_includes_audit_only_rows_in_insertion_order(db, biz):
    """`_movement_sums` excludes audit-only rows from the ARITHMETIC; the
    listing must still SHOW them, or the opening variance and the closing
    deposit become invisible and the drawer's history has holes in it."""
    S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=1000.0)
    S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                  closing_cash_actual=1000.0, leave_in_drawer=1000.0)
    sh2 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=900.0)
    S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                           movement_type="paid_in", category="change_top_up",
                           amount=100.0)
    rows = S.list_movements(db, sh2)
    cats = [r["category"] for r in rows]
    assert cats == ["opening_variance", "change_top_up"]
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids)


def test_shift_out_omits_discrepancies_while_open(db, biz):
    """An open shift has not been counted, so a discrepancy would be a number
    invented from a NULL."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=100.0)
    out = S.shift_out(sh)
    assert out["status"] == "OPEN"
    assert "cash_discrepancy" not in out
    assert "upi_discrepancy" not in out
    assert "tally" not in out and "movements" not in out


def test_shift_out_reports_discrepancy_sign_as_over_positive(db, biz):
    """actual − expected. Positive is OVER, negative is SHORT. Getting the
    subtraction backwards would accuse every cashier with a surplus."""
    sh0 = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=500.0)
    _receipt(db, biz, sh0, 1000.0, "cash")
    sh = S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                       closing_cash_actual=1450.0)     # 50 SHORT of 1500
    out = S.shift_out(sh)
    assert out["cash_discrepancy"] == -50.0
    assert out["upi_discrepancy"] == 0.0


def test_shift_out_discrepancy_handles_null_actuals(db, biz):
    """A closed legacy row may have NULL actuals; `_round2(None)` is 0.0 so this
    must produce 0.0, not a TypeError, or the shift report 500s."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    sh.status = "CLOSED"
    sh.closing_cash_actual = None
    sh.closing_cash_expected = None
    sh.closing_upi_actual = None
    sh.closing_upi_expected = None
    db.commit()
    out = S.shift_out(sh)
    assert out["cash_discrepancy"] == 0.0
    assert out["upi_discrepancy"] == 0.0


def test_shift_out_attaches_tally_and_movements_when_given(db, biz):
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=10.0)
    tally = S.compute_tally(db, sh)
    movements = S.list_movements(db, sh)
    out = S.shift_out(sh, tally=tally, movements=movements)
    assert out["tally"] == tally
    assert out["movements"] == movements


def test_shift_out_distinguishes_empty_movements_from_absent(db, biz):
    """`movements=[]` means "we looked, there are none"; omitting the key means
    "not loaded". The `is not None` check in the serializer is what keeps those
    apart, and a truthiness check would collapse them."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=0.0)
    assert S.shift_out(sh, movements=[])["movements"] == []
    assert "movements" not in S.shift_out(sh)


# ── Cross-cutting: the drawer reconciles against the ledger ──────────────────

def test_full_shift_reconciles_cash_upi_and_movements_together(db, biz):
    """One shift, every kind of event, reconciled in a single assertion — the
    shift-level analogue of tests/test_money_reconciliation.py. This is the test
    that would catch a sign error anywhere in the module."""
    sh = S.open_shift(db, business_id=biz["bid"], user_id=biz["uid"], opening_cash=2000.0)

    _receipt(db, biz, sh, 3000.0, "cash")      # counter sale
    _receipt(db, biz, sh, 1200.0, "cash")      # credit collection
    _receipt(db, biz, sh, 2500.0, "upi")
    _receipt(db, biz, sh, 800.0, "card")
    _receipt(db, biz, sh, 600.0, "netbanking")  # unknown → other

    S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                           movement_type="paid_in", category="change_top_up",
                           amount=500.0)
    S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                           movement_type="paid_out", category="expense",
                           amount=250.0, expense_category="Staff Welfare")
    S.record_cash_movement(db, business_id=biz["bid"], user_id=biz["uid"],
                           movement_type="paid_out", category="bank_deposit",
                           amount=1000.0)

    expected_cash = 2000.0 + (3000.0 + 1200.0) + 500.0 - (250.0 + 1000.0)
    t = S.compute_tally(db, sh)
    assert t["expected_cash"] == expected_cash
    assert t["expected_upi"] == 2500.0
    assert t["sales_card"] == 800.0
    assert t["sales_other"] == 600.0

    # Close counting exactly the expectation → zero discrepancy, and the
    # closing removal must NOT retro-change the snapshot.
    closed = S.close_shift(db, business_id=biz["bid"], user_id=biz["uid"],
                           closing_cash_actual=expected_cash,
                           closing_upi_actual=2500.0,
                           leave_in_drawer=2000.0,
                           removal_destination="bank_deposit")
    out = S.shift_out(closed, tally=S.compute_tally(db, closed))
    assert out["cash_discrepancy"] == 0.0
    assert out["upi_discrepancy"] == 0.0
    assert closed.closing_cash_expected == expected_cash
    assert closed.closing_float == 2000.0

    # The next shift's suggestion is what was LEFT.
    assert S.suggested_opening_cash(
        db, business_id=biz["bid"], user_id=biz["uid"])["suggested"] == 2000.0
