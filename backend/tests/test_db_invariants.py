"""
tests/test_db_invariants.py — review finding N4.
===============================================
Proves the money invariants are enforced BY THE DATABASE, on whatever dialect is
running, by attempting a violating write and requiring it to fail.

This distinction is the whole point of the file. Asserting that a migration
emitted some DDL proves nothing: the SQLite path installs triggers and the
Postgres path installs CHECK constraints, and either could be syntactically valid
and semantically inert. So every rule in ``db_invariants.INVARIANTS`` is tested
the only way that constitutes evidence — write a row that breaks it, and assert
the database refuses.

The writes go through raw SQL on purpose. Going through the ORM command layer
would prove that `core/billing` validates its inputs, which is already tested and
is not the claim here. The claim is that a path which BYPASSES the command layer
— an import, a sync apply, a repair script — cannot write a row the books cannot
represent. So the test bypasses it too.

There is also a coverage test: every declared invariant must be exercised. A rule
added to the list without a behavioural test would look enforced on the strength
of this file's existence.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError, OperationalError

from database.db import engine
from core.accounting import db_invariants as DBI

REFUSALS = (IntegrityError, OperationalError, DatabaseError)


@pytest.fixture(scope="module", autouse=True)
def installed():
    """Install the guards once for this module and report what landed."""
    with engine.connect() as conn:
        report = DBI.ensure_invariants(conn)
    return report


@pytest.fixture()
def conn():
    with engine.connect() as c:
        yield c
        try:
            c.rollback()
        except Exception:
            pass


def _biz(conn):
    """A users row to own the test rows. Needed now that FKs are enforced."""
    uname = f"inv_{uuid.uuid4().hex[:10]}"
    # Explicit id, derived from MAX(id), rather than leaning on the PK default.
    #
    # On Postgres `users.id` is backed by a SEQUENCE, and sibling suites in the
    # same session insert users with EXPLICIT ids — which does not advance it.
    # The sequence therefore hands back an id that already exists and the insert
    # dies on `pk_users` (observed in CI 2026-08-03: "Key (id)=(2) already
    # exists"). SQLite's rowid picks MAX+1, so this never showed locally.
    #
    # The application path does not have this problem — the importer no longer
    # inserts explicit ids at all. `_import_with_remap` lets the destination
    # allocate every id from its own sequence and rewrites the FKs, so there is
    # nothing to realign afterwards. (`_reset_sequences` existed for the
    # id-preserving importer and was deleted with it.) This is a fixture-only
    # gap, so it is fixed here rather than in product code.
    next_id = (conn.execute(text("SELECT MAX(id) FROM users")).scalar() or 0) + 1
    conn.execute(text(
        "INSERT INTO users (id, username, password, business_name, role) "
        "VALUES (:i, :u, 'x', 'Invariant Co', 'owner')"), {"i": next_id, "u": uname})
    conn.commit()
    return conn.execute(text(
        "SELECT id FROM users WHERE username = :u"), {"u": uname}).scalar()


def _refuses(conn, sql, params=None):
    """Assert the database rejects this write, then leave the session usable."""
    with pytest.raises(REFUSALS):
        conn.execute(text(sql), params or {})
        conn.commit()
    conn.rollback()


# ── The guards are actually present ──────────────────────────────────────────

def test_every_invariant_installed_or_explained(installed):
    """Nothing may be silently absent. A rule that is skipped has to appear in
    one of the explanatory buckets — never just vanish."""
    accounted = (set(installed["installed"]) | set(installed["already"])
                 | set(installed["skipped_missing_table"])
                 | set(installed["skipped_violations"]) | set(installed["errors"]))
    declared = {i.name for i in DBI.INVARIANTS}
    assert declared == accounted, f"unaccounted invariants: {declared - accounted}"


def test_no_invariant_failed_to_install(installed):
    assert not installed["errors"], installed["errors"]


def test_no_existing_rows_violate_any_invariant(installed):
    """If this fires, the test database itself contains money rows the books
    cannot represent — which is a finding, not a test-setup problem."""
    assert not installed["skipped_violations"], installed["skipped_violations"]


def test_every_invariant_has_a_substantive_rationale():
    for inv in DBI.INVARIANTS:
        assert len(inv.why) > 80, (
            f"{inv.name} needs a written reason: a constraint nobody can "
            "justify is the one that gets dropped when it becomes inconvenient"
        )
        assert inv.columns, f"{inv.name} declares no columns"


def test_paid_amount_ceiling_is_deliberately_absent():
    """The baseline review asked for CHECK (paid_amount <= total_amount). It is
    omitted on purpose and this test says so, so nobody re-adds it from the older
    document: `reconcile_invoice_paid_state` sets paid_amount to the uncapped sum
    of the payment ledger, because overpayment is a real event whose excess is
    booked to Customer Advances. The constraint would reject a legitimate
    counter receipt."""
    conditions = " ".join(i.condition for i in DBI.INVARIANTS)
    assert "total_amount" not in conditions, (
        "an invariant now constrains paid_amount against total_amount — see "
        "core/accounting/db_invariants.py's 'WHAT IS DELIBERATELY NOT HERE'"
    )


# ── Behavioural: each rule refuses a violating write ─────────────────────────

def test_negative_payment_is_refused(conn):
    """A refund is a credit note, not a negative receipt. A negative row here
    would reduce paid_amount and put a settled customer back on the dues list."""
    bid = _biz(conn)
    conn.execute(text(
        "INSERT INTO invoices (business_id, invoice_id, customer, amount, "
        "total_amount, status, invoice_date) VALUES "
        "(:b, :n, 'C', 100, 100, 'Pending', '2026-07-26')"),
        {"b": bid, "n": f"INVT-{uuid.uuid4().hex[:6]}"})
    conn.commit()
    inv_id = conn.execute(text(
        "SELECT id FROM invoices WHERE business_id = :b"), {"b": bid}).scalar()

    _refuses(conn,
             "INSERT INTO invoice_payments (business_id, invoice_id, amount_paid, "
             "payment_mode) VALUES (:b, :i, -50, 'cash')",
             {"b": bid, "i": inv_id})


def test_zero_payment_is_refused(conn):
    bid = _biz(conn)
    conn.execute(text(
        "INSERT INTO invoices (business_id, invoice_id, customer, amount, "
        "total_amount, status, invoice_date) VALUES "
        "(:b, :n, 'C', 100, 100, 'Pending', '2026-07-26')"),
        {"b": bid, "n": f"INVT-{uuid.uuid4().hex[:6]}"})
    conn.commit()
    inv_id = conn.execute(text(
        "SELECT id FROM invoices WHERE business_id = :b"), {"b": bid}).scalar()
    _refuses(conn,
             "INSERT INTO invoice_payments (business_id, invoice_id, amount_paid, "
             "payment_mode) VALUES (:b, :i, 0, 'cash')",
             {"b": bid, "i": inv_id})


def test_a_positive_payment_is_still_accepted(conn):
    """The guard must not be a blanket refusal. Asserted because a trigger with
    an inverted condition would pass every 'is it refused' test in this file."""
    bid = _biz(conn)
    conn.execute(text(
        "INSERT INTO invoices (business_id, invoice_id, customer, amount, "
        "total_amount, status, invoice_date) VALUES "
        "(:b, :n, 'C', 100, 100, 'Pending', '2026-07-26')"),
        {"b": bid, "n": f"INVT-{uuid.uuid4().hex[:6]}"})
    conn.commit()
    inv_id = conn.execute(text(
        "SELECT id FROM invoices WHERE business_id = :b"), {"b": bid}).scalar()
    conn.execute(text(
        "INSERT INTO invoice_payments (business_id, invoice_id, amount_paid, "
        "payment_mode) VALUES (:b, :i, 250.50, 'cash')"),
        {"b": bid, "i": inv_id})
    conn.commit()
    got = conn.execute(text(
        "SELECT amount_paid FROM invoice_payments WHERE invoice_id = :i"),
        {"i": inv_id}).scalar()
    assert float(got) == 250.50


def test_updating_a_payment_to_negative_is_refused(conn):
    """INSERT and UPDATE both need a guard. A rule enforced only on insert is
    bypassed by writing a legal row and then editing it — which is exactly what
    a repair script does."""
    bid = _biz(conn)
    conn.execute(text(
        "INSERT INTO invoices (business_id, invoice_id, customer, amount, "
        "total_amount, status, invoice_date) VALUES "
        "(:b, :n, 'C', 100, 100, 'Pending', '2026-07-26')"),
        {"b": bid, "n": f"INVT-{uuid.uuid4().hex[:6]}"})
    conn.commit()
    inv_id = conn.execute(text(
        "SELECT id FROM invoices WHERE business_id = :b"), {"b": bid}).scalar()
    conn.execute(text(
        "INSERT INTO invoice_payments (business_id, invoice_id, amount_paid, "
        "payment_mode) VALUES (:b, :i, 100, 'cash')"), {"b": bid, "i": inv_id})
    conn.commit()
    _refuses(conn,
             "UPDATE invoice_payments SET amount_paid = -1 WHERE invoice_id = :i",
             {"i": inv_id})


def test_two_sided_journal_line_is_refused(conn):
    """The error that BALANCES and is still wrong: a line carrying both a debit
    and a credit passes post_entry's footing guard, then makes the trial balance
    and the P&L disagree because each reads one column."""
    bid = _biz(conn)
    conn.execute(text(
        "INSERT INTO journal_entries (business_id, entry_date, source_type, "
        "source_id, ref_no, narration, entry_hash, prev_hash) VALUES "
        "(:b, '2026-07-26', 'sale', 991001, 'T1', 'test', 'h', 'p')"), {"b": bid})
    conn.commit()
    entry_id = conn.execute(text(
        "SELECT id FROM journal_entries WHERE business_id = :b"), {"b": bid}).scalar()
    _refuses(conn,
             "INSERT INTO journal_lines (entry_id, account, debit, credit) "
             "VALUES (:e, 'Cash & Bank', 100, 100)", {"e": entry_id})


def test_negative_journal_amounts_are_refused(conn):
    bid = _biz(conn)
    conn.execute(text(
        "INSERT INTO journal_entries (business_id, entry_date, source_type, "
        "source_id, ref_no, narration, entry_hash, prev_hash) VALUES "
        "(:b, '2026-07-26', 'sale', 991002, 'T2', 'test', 'h', 'p')"), {"b": bid})
    conn.commit()
    entry_id = conn.execute(text(
        "SELECT id FROM journal_entries WHERE business_id = :b"), {"b": bid}).scalar()
    _refuses(conn,
             "INSERT INTO journal_lines (entry_id, account, debit, credit) "
             "VALUES (:e, 'Sales', -100, 0)", {"e": entry_id})
    _refuses(conn,
             "INSERT INTO journal_lines (entry_id, account, debit, credit) "
             "VALUES (:e, 'Sales', 0, -100)", {"e": entry_id})


def test_a_normal_single_sided_journal_line_is_accepted(conn):
    bid = _biz(conn)
    conn.execute(text(
        "INSERT INTO journal_entries (business_id, entry_date, source_type, "
        "source_id, ref_no, narration, entry_hash, prev_hash) VALUES "
        "(:b, '2026-07-26', 'sale', 991003, 'T3', 'test', 'h', 'p')"), {"b": bid})
    conn.commit()
    entry_id = conn.execute(text(
        "SELECT id FROM journal_entries WHERE business_id = :b"), {"b": bid}).scalar()
    for dr, cr in ((100.0, 0.0), (0.0, 100.0)):
        conn.execute(text(
            "INSERT INTO journal_lines (entry_id, account, debit, credit) "
            "VALUES (:e, 'Cash & Bank', :d, :c)"),
            {"e": entry_id, "d": dr, "c": cr})
    conn.commit()
    assert conn.execute(text(
        "SELECT COUNT(*) FROM journal_lines WHERE entry_id = :e"),
        {"e": entry_id}).scalar() == 2


def test_negative_invoice_paid_amount_is_refused(conn):
    bid = _biz(conn)
    _refuses(conn,
             "INSERT INTO invoices (business_id, invoice_id, customer, amount, "
             "total_amount, paid_amount, status, invoice_date) VALUES "
             "(:b, :n, 'C', 100, 100, -5, 'Pending', '2026-07-26')",
             {"b": bid, "n": f"INVT-{uuid.uuid4().hex[:6]}"})


def test_negative_document_sequence_is_refused(conn):
    bid = _biz(conn)
    _refuses(conn,
             "INSERT INTO document_sequences (business_id, series, last_number) "
             "VALUES (:b, 'NEGTEST', -1)", {"b": bid})


def test_negative_opening_cash_is_refused(conn):
    bid = _biz(conn)
    _refuses(conn,
             "INSERT INTO register_shifts (business_id, user_id, opening_cash, "
             "status, start_time) VALUES (:b, :b, -100, 'OPEN', '2026-07-26 09:00:00')",
             {"b": bid})


# ── Coverage of the rule list itself ─────────────────────────────────────────

_EXERCISED = {
    "ck_invoice_payments_amount_positive",
    "ck_journal_lines_single_sided",
    "ck_journal_lines_non_negative",
    "ck_invoices_paid_amount_non_negative",
    "ck_document_sequences_monotonic_floor",
    "ck_register_shifts_opening_cash_non_negative",
}


def test_every_declared_invariant_has_a_behavioural_test():
    """A rule added to INVARIANTS without a violating-write test would inherit
    this file's credibility without earning it."""
    declared = {i.name for i in DBI.INVARIANTS}
    assert declared == _EXERCISED, (
        f"invariants with no behavioural test: {declared - _EXERCISED}; "
        f"tests for invariants that no longer exist: {_EXERCISED - declared}"
    )


# ── SQLite foreign keys (the other half of N4) ───────────────────────────────

def test_sqlite_foreign_keys_are_enforced(conn):
    """SQLite defaults `PRAGMA foreign_keys = OFF`, per connection. Every
    ForeignKey and every ondelete="CASCADE" in the models was declared and not
    enforced on local installs, while the Postgres cloud enforced them — the two
    halves of a hybrid install disagreed about what a legal row is."""
    if conn.dialect.name != "sqlite":
        pytest.skip("Postgres enforces foreign keys unconditionally")
    assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_orphan_child_row_is_refused(conn):
    """Behavioural proof, not a pragma reading: a payment pointing at an invoice
    that does not exist must be rejected. Before the fix this row inserted
    happily on a local install, then failed forever on push to the cloud."""
    bid = _biz(conn)
    _refuses(conn,
             "INSERT INTO invoice_payments (business_id, invoice_id, amount_paid, "
             "payment_mode) VALUES (:b, 99999999, 100, 'cash')", {"b": bid})


def test_foreign_keys_are_enforced_on_every_new_connection(conn):
    """The pragma is per CONNECTION. A listener attached to the wrong event (or
    to the pool rather than the DBAPI connect) would set it once and leave every
    subsequent pooled connection unprotected."""
    if conn.dialect.name != "sqlite":
        pytest.skip("sqlite-specific pragma")
    for _ in range(3):
        with engine.connect() as fresh:
            assert fresh.execute(text("PRAGMA foreign_keys")).scalar() == 1


# ── Idempotency ──────────────────────────────────────────────────────────────

def test_installing_twice_is_a_no_op():
    """Runs on every boot, so a second pass must report 'already' rather than
    erroring or duplicating triggers."""
    with engine.connect() as c:
        again = DBI.ensure_invariants(c)
    assert not again["installed"], "second install created guards again"
    assert not again["errors"], again["errors"]
    assert set(again["already"]) | set(again["skipped_missing_table"]) == \
        {i.name for i in DBI.INVARIANTS}


# ── M-11: one OPEN shift per operator, enforced by the DB ────────────────────
#
# The rule is the first line of `core/shifts/service.py`'s documentation, and
# `open_shift` enforces it via `get_open_shift`. Both are keyed on
# `(business_id, user_id)` — and `user_id` is a column SYNC CAN POPULATE WRONGLY,
# which is precisely why `register_shifts` is in
# `sync_map._USER_FK_REPOINT_ENTITIES`.
#
# Found in real data (business 7): shift 4 opened FOUR MINUTES into shift 3 and
# was accepted, because with a foreign `user_id` the check was asking about a
# different operator. Nobody could see it, nobody could close it, and three cash
# sales totalling Rs 2,485 were rung against it — money that never reached a
# drawer tally anyone could reconcile.
#
# Architecture rule 11: application-level uniqueness is not uniqueness.

_OPEN_SHIFT_INDEX = "uix_register_shifts_one_open_per_user"


def _open_shift_index_exists(conn) -> bool:
    if conn.dialect.name == "postgresql":
        return bool(conn.execute(text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :n"),
            {"n": _OPEN_SHIFT_INDEX}).fetchone())
    return bool(conn.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name = :n"),
        {"n": _OPEN_SHIFT_INDEX}).fetchone())


@pytest.fixture()
def open_shift_guard(conn):
    """Install the M-11 index for this test, cleaning up any leftover rows first."""
    from database.migration import _ensure_single_open_shift_index
    _ensure_single_open_shift_index(conn)
    if not _open_shift_index_exists(conn):
        pytest.skip("index not installed (pre-existing overlapping shifts in this DB)")
    return conn


def test_second_open_shift_for_the_same_operator_is_refused(open_shift_guard, conn):
    bid = _biz(conn)
    conn.execute(text(
        "INSERT INTO register_shifts (business_id, user_id, status, opening_cash, "
        "start_time) VALUES (:b, :b, 'OPEN', 100, '2026-07-26 09:00:00')"), {"b": bid})
    conn.commit()
    _refuses(conn,
             "INSERT INTO register_shifts (business_id, user_id, status, "
             "opening_cash, start_time) VALUES "
             "(:b, :b, 'OPEN', 200, '2026-07-26 09:04:00')", {"b": bid})


def test_a_closed_shift_does_not_block_a_new_one(open_shift_guard, conn):
    """The index is PARTIAL (`WHERE status = 'OPEN'`) precisely so the normal
    open-close-open cycle keeps working. A full unique index would let an
    operator work exactly one shift, ever."""
    bid = _biz(conn)
    conn.execute(text(
        "INSERT INTO register_shifts (business_id, user_id, status, opening_cash, "
        "start_time, end_time) VALUES "
        "(:b, :b, 'CLOSED', 100, '2026-07-25 09:00:00', '2026-07-25 21:00:00')"),
        {"b": bid})
    conn.execute(text(
        "INSERT INTO register_shifts (business_id, user_id, status, opening_cash, "
        "start_time) VALUES (:b, :b, 'OPEN', 100, '2026-07-26 09:00:00')"), {"b": bid})
    conn.commit()
    assert conn.execute(text(
        "SELECT COUNT(*) FROM register_shifts WHERE business_id = :b"),
        {"b": bid}).scalar() == 2


def test_two_operators_may_each_hold_an_open_shift(open_shift_guard, conn):
    """Multi-counter is the product's flagship case — the constraint is per
    OPERATOR, not per business."""
    bid_a = _biz(conn)
    bid_b = _biz(conn)
    for owner in (bid_a, bid_b):
        conn.execute(text(
            "INSERT INTO register_shifts (business_id, user_id, status, "
            "opening_cash, start_time) VALUES "
            "(:b, :u, 'OPEN', 100, '2026-07-26 09:00:00')"),
            {"b": bid_a, "u": owner})
    conn.commit()
    assert conn.execute(text(
        "SELECT COUNT(*) FROM register_shifts WHERE business_id = :b "
        "AND status = 'OPEN'"), {"b": bid_a}).scalar() == 2


def test_index_refuses_to_install_over_existing_overlaps(conn):
    """Same discipline as the M-3 index: a migration must not resolve this by
    closing a shift, because `closing_cash_actual` is a COUNTED figure and
    inventing one fabricates evidence. It reports and waits."""
    from database.migration import _ensure_single_open_shift_index

    # Drop the guard so we can plant the violation the migration must refuse.
    conn.execute(text(f"DROP INDEX IF EXISTS {_OPEN_SHIFT_INDEX}"))
    conn.commit()
    bid = _biz(conn)
    for t in ("09:00:00", "09:04:00"):
        conn.execute(text(
            "INSERT INTO register_shifts (business_id, user_id, status, "
            "opening_cash, start_time) VALUES "
            "(:b, :b, 'OPEN', 100, :t)"), {"b": bid, "t": f"2026-07-26 {t}"})
    conn.commit()

    _ensure_single_open_shift_index(conn)
    assert not _open_shift_index_exists(conn), (
        "the migration created the index over overlapping open shifts — it must "
        "refuse and report instead"
    )

    # Resolve the overlap; now it installs.
    # Match the timestamp by equality, not LIKE. `start_time` is a DateTime, and
    # on Postgres `timestamp LIKE text` has no operator (`~~`) — it raises
    # UndefinedFunction. SQLite stores it as text so LIKE happened to work, which
    # is exactly the kind of SQLite-only assumption this suite now runs on
    # Postgres to catch.
    conn.execute(text(
        "UPDATE register_shifts SET status='CLOSED', end_time='2026-07-26 21:00:00' "
        "WHERE business_id = :b AND start_time = :t"),
        {"b": bid, "t": "2026-07-26 09:00:00"})
    conn.commit()
    _ensure_single_open_shift_index(conn)
    assert _open_shift_index_exists(conn)
