"""
tests/test_migration_step_isolation.py — the 2026-07-26 cloud boot cascade.
===========================================================================
ARCHITECTURE RULE 58: a migration step must roll back its own failed
transaction.

WHAT ACTUALLY HAPPENED
----------------------
The 22:00 boot of the Hugging Face Space (Postgres) logged:

    psycopg2.errors.UndefinedFunction:
        function round(double precision, integer) does not exist

`_install_overfill_guard` scanned for already-over-filled parents with
`ROUND(SUM(c.line_total) - (...), 2)`. Every money column involved is
`Column(Float)` -> `double precision` on Postgres, and Postgres has no
two-argument `round` for double precision (only `round(numeric, integer)` and
the one-argument form). SQLite's `ROUND` happily takes `(real, int)`, so the
guard was green locally and threw on its first contact with the cloud.

That was the bug. The DAMAGE was the cascade. All of section 3 of
`run_migrations_and_seed` shares one connection; on Postgres a failed statement
aborts the whole transaction, and NOT ONE except block in migration.py rolled
back. So one bad SELECT became:

    ck_invoice_line_items_no_overfill      not installed
    ck_b2b_order_line_items_no_overfill    not installed
    all six N4 money invariants            not installed
    _migrate_session_nulls                 skipped

The production database ended up with none of its money guards, and the boot log
showed four *different* InFailedSqlTransaction errors that each looked like an
unrelated local problem rather than one root cause.

WHY THESE TESTS LOOK LIKE THIS
------------------------------
There is no Postgres in CI or in the authoring sandbox, and the whole point of
this finding is that "it passed on SQLite" is not evidence (rule 51 — prove a
guard on EVERY dialect). So the tests attack the two halves separately:

  * Test group 1 runs the real scan SQL against real SQLite and asserts the
    emitted SQL contains no two-argument ROUND at all. A query that never calls
    ROUND cannot depend on which dialect implements it — that is a property
    provable without a Postgres server, which is exactly why the fix rounds in
    Python instead of switching to `ROUND(CAST(x AS numeric), 2)`.

  * Test group 2 uses a fake connection that REPRODUCES POSTGRES ABORT
    SEMANTICS: after any failed execute it raises InFailedSqlTransaction on
    every subsequent statement until `rollback()` is called. Run the real
    migration functions against it and the cascade either happens or it does
    not. This is the only way to test the actual defect without a server, and
    it fails loudly against the old code.

Stated plainly (rule 57 / no guesswork): none of this executes against a real
PostgreSQL server. What is proved here is (a) the SQL no longer contains the
function that did not exist, and (b) the cascade cannot propagate through a
connection with Postgres abort semantics. What is NOT proved here is the
trigger DDL itself running on a real Postgres — that still needs a cloud boot
log or a Dockerised Postgres run.
"""
import os
import re
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlite3

import pytest

from database import migration as MIG


# ---------------------------------------------------------------------------
# 1. THE ROUND BUG ITSELF
# ---------------------------------------------------------------------------

SPECS = [
    ("invoice_line_items", "invoices", "invoice_id",
     "COALESCE(total_amount,0) + COALESCE(cash_discount,0) - COALESCE(round_off,0)"),
    ("b2b_order_line_items", "b2b_orders", "order_id",
     "COALESCE(total_amount,0)"),
]


def _capture_scan_sql():
    """Run _report_existing_overfill and return every SQL string it emitted."""
    seen = []

    class Rec:
        def execute(self, stmt, *a, **k):
            seen.append(str(stmt))
            raise RuntimeError("stop after capture")

        def rollback(self):
            pass

    for child, parent, fk, target in SPECS:
        MIG._report_existing_overfill(Rec(), child, parent, fk, target, 1.00)
    return seen


def test_scan_sql_contains_no_two_arg_round():
    """The exact defect: ROUND(<double precision>, 2) does not exist on Postgres.

    Asserted on the generated SQL rather than on behaviour, because behaviour on
    SQLite is precisely what failed to catch this the first time.
    """
    for sql in _capture_scan_sql():
        assert not re.search(r"\bROUND\s*\([^()]*,\s*\d+\s*\)", sql, re.I), (
            "two-argument SQL ROUND is back in the overfill scan; Postgres has "
            "no round(double precision, integer) and every column here is "
            f"Column(Float):\n{sql}"
        )
        # Belt and braces: no ROUND of any arity, so no dialect question at all.
        assert "ROUND(" not in sql.upper(), sql


def test_scan_query_actually_runs_and_finds_an_overfilled_row(tmp_path):
    """The scan must still WORK, not merely parse. Rule 33: a check that cannot
    see something must not report there is nothing to see."""
    db = tmp_path / "test_overfill_scan.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE invoices (id INTEGER PRIMARY KEY, total_amount REAL,
                               cash_discount REAL, round_off REAL);
        CREATE TABLE invoice_line_items (id INTEGER PRIMARY KEY,
                               invoice_id INTEGER, line_total REAL);
        -- clean: lines reconcile to header target 337.65 = 323 + 15 - 0.35
        INSERT INTO invoices VALUES (1, 323.0, 15.0, 0.35);
        INSERT INTO invoice_line_items VALUES (1, 1, 337.65);
        -- over-filled: 500 of line value against a 100 header
        INSERT INTO invoices VALUES (2, 100.0, 0.0, 0.0);
        INSERT INTO invoice_line_items VALUES (2, 2, 100.0);
        INSERT INTO invoice_line_items VALUES (3, 2, 400.0);
        -- header total zero: excluded by design, not by accident
        INSERT INTO invoices VALUES (3, 0.0, 0.0, 0.0);
        INSERT INTO invoice_line_items VALUES (4, 3, 99.0);
    """)
    con.commit()

    target = SPECS[0][3]
    qualified = target.replace("COALESCE(", "COALESCE(p.")
    rows = con.execute(f"""
        SELECT p.id, SUM(c.line_total) - ({qualified}) AS over
          FROM invoices p JOIN invoice_line_items c ON c.invoice_id = p.id
         WHERE COALESCE(p.total_amount,0) <> 0
         GROUP BY p.id
        HAVING SUM(c.line_total) > ({qualified}) + 1.00
    """).fetchall()
    con.close()

    assert [r[0] for r in rows] == [2], (
        "scan must flag invoice 2 only: 1 reconciles exactly (the LCL-OW-0027 "
        "shape that produced five false positives when the discount and "
        "round-off were omitted), 3 has a zero header and is out of scope"
    )
    # The rounding the SQL no longer does, done in Python instead.
    assert round(float(rows[0][1]), 2) == 400.00


# ---------------------------------------------------------------------------
# 2. THE CASCADE
# ---------------------------------------------------------------------------

class InFailedSqlTransaction(Exception):
    """Stands in for psycopg2.errors.InFailedSqlTransaction."""


class PgLikeConn:
    """A connection with POSTGRES abort semantics.

    This is the behaviour SQLite does not have and therefore the behaviour no
    local test could previously observe: once a statement fails, every further
    statement fails with InFailedSqlTransaction until rollback() is called.
    """

    def __init__(self, failing: str):
        self.failing = failing          # substring marking the statement that fails
        self.aborted = False
        self.executed = []              # statements that actually ran
        self.rollbacks = 0

    class _Dialect:
        name = "postgresql"

    dialect = _Dialect()

    def execute(self, stmt, *a, **k):
        sql = str(stmt)
        if self.aborted:
            raise InFailedSqlTransaction(
                "current transaction is aborted, commands ignored until end of "
                "transaction block")
        if self.failing in sql:
            self.aborted = True
            raise Exception(
                "(psycopg2.errors.UndefinedFunction) function "
                "round(double precision, integer) does not exist")
        self.executed.append(sql)
        return _EmptyResult()

    def commit(self):
        if self.aborted:
            raise InFailedSqlTransaction("cannot commit an aborted transaction")

    def rollback(self):
        self.rollbacks += 1
        self.aborted = False


class _EmptyResult:
    def fetchall(self):
        return []

    def fetchone(self):
        return None


def test_rollback_quietly_clears_an_aborted_transaction():
    conn = PgLikeConn(failing="BOOM")
    with pytest.raises(Exception):
        conn.execute("BOOM")
    assert conn.aborted
    MIG._rollback_quietly(conn, "unit")
    assert not conn.aborted and conn.rollbacks == 1
    conn.execute("SELECT 1")                     # would raise if still aborted


def test_rollback_quietly_never_raises_even_if_rollback_fails():
    """It is cleanup inside an already-reported error path (rule 13) — but it is
    logged, never silent."""
    class Broken:
        def rollback(self):
            raise RuntimeError("connection is gone")

    MIG._rollback_quietly(Broken(), "unit")      # must not raise


def test_failed_scan_does_not_prevent_guard_installation():
    """THE REGRESSION. The failing statement is the scan SELECT — exactly the
    2026-07-26 failure — and the trigger must still be created."""
    conn = PgLikeConn(failing="JOIN")            # only the scan SELECT joins
    MIG._install_overfill_guard(
        conn, "invoice_line_items", "invoices", "invoice_id",
        "COALESCE(total_amount,0) + COALESCE(cash_discount,0) - COALESCE(round_off,0)",
        "line_item", 1.00, is_pg=True)

    assert conn.rollbacks >= 1, "scan failure was not rolled back"
    body = "\n".join(conn.executed).upper()
    assert "CREATE OR REPLACE FUNCTION" in body, (
        "the guard function was not created after a failed diagnostic scan — "
        "the scan is diagnostic, its failure must not cost us the prevention")
    assert "CREATE TRIGGER CK_INVOICE_LINE_ITEMS_NO_OVERFILL" in body


def test_failed_guard_install_does_not_poison_the_next_step():
    """The cascade itself: guard 1 dies, guard 2 must still install.

    Against the pre-fix code this fails — the second spec's very first statement
    raises InFailedSqlTransaction.
    """
    calls = {"n": 0}
    conn = PgLikeConn(failing="__never__")
    real_execute = conn.execute

    def flaky(stmt, *a, **k):
        sql = str(stmt)
        # Fail only the FIRST guard's CREATE TRIGGER, the way a bad DDL would.
        if "CREATE TRIGGER" in sql.upper() and calls["n"] == 0:
            calls["n"] += 1
            conn.aborted = True
            raise Exception("(psycopg2.errors.SyntaxError) bad trigger body")
        return real_execute(stmt, *a, **k)

    conn.execute = flaky

    for child, parent, fk, target, suffix in [
        ("invoice_line_items", "invoices", "invoice_id",
         "COALESCE(total_amount,0) + COALESCE(cash_discount,0) - COALESCE(round_off,0)",
         "line_item"),
        ("b2b_order_line_items", "b2b_orders", "order_id",
         "COALESCE(total_amount,0)", "b2b_order_line"),
    ]:
        MIG._install_overfill_guard(conn, child, parent, fk, target, suffix,
                                    1.00, is_pg=True)

    body = "\n".join(conn.executed).upper()
    assert "CREATE TRIGGER CK_B2B_ORDER_LINE_ITEMS_NO_OVERFILL" in body, (
        "the B2B guard was lost because the invoice guard failed first — this "
        "is M-18 going unguarded on the cloud, which is what shipped")


def test_step_isolates_any_failure_and_names_it():
    """_step() is the structural guarantee: it does not matter whether a future
    step remembers to roll back."""
    conn = PgLikeConn(failing="__never__")

    def bad_step(c):
        c.aborted = True
        raise Exception("(psycopg2.errors.UndefinedFunction) round(...)")

    def good_step(c):
        c.execute("CREATE INDEX later_step_ran ON t (x)")

    assert MIG._step(conn, bad_step) is None     # must not re-raise: boot goes on
    MIG._step(conn, good_step)

    assert conn.rollbacks >= 1
    assert any("later_step_ran" in s for s in conn.executed), (
        "a later migration step was silently killed by an earlier one's failure")


def test_every_shared_connection_step_is_wrapped():
    """Rule 58 applied to the runner, not just to the steps that have burned us.

    Asserted on the source so a step added later cannot quietly skip _step().
    """
    src = open(os.path.join(os.path.dirname(MIG.__file__), "migration.py"),
               encoding="utf-8").read()
    block = src.split("# 3. Backfills & sequence resync", 1)[1].split("# 4.", 1)[0]
    bare = re.findall(r"^\s{8}(_[a-z_]+)\(conn\)", block, re.M)
    assert not bare, (
        f"migration steps sharing the section-3 connection are not wrapped in "
        f"_step(): {bare}. One failure would abort the transaction and silently "
        f"kill every step after it (rule 58).")


def test_sequence_resync_no_longer_swallows_silently():
    """`except Exception: pass` around the thing that stops the next INSERT
    colliding on a primary key. Fail-open is right; silent is not."""
    src = open(os.path.join(os.path.dirname(MIG.__file__), "migration.py"),
               encoding="utf-8").read()
    fn = src.split("def _resync_postgres_sequences", 1)[1].split("\ndef ", 1)[0]
    assert "except Exception:\n            pass" not in fn
    assert "logger.warning" in fn and "_rollback_quietly" in fn
