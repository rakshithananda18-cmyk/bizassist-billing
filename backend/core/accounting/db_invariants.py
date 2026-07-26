"""
core/accounting/db_invariants.py — money invariants enforced BY THE DATABASE.
============================================================================
Closes the long-standing N4 item ("DB-level financial invariants"), which has
been open since the baseline review.

THE ARGUMENT
------------
Architecture rule 11 already states it: *application-level uniqueness is not
uniqueness.* The same is true of every other money invariant. The command layer
(`core/billing`, `core/accounting`) is correct, and `post_entry` genuinely refuses
to write an entry that does not foot — but that only protects writers who go
through it. An import, a sync apply, a repair script or a future route can write
an `Invoice` or a `journal_line` directly, and then the first symptom is a wrong
number on a report.

`core/accounting/integrity.py` already defines what "intact" means and audits it
on a schedule. That is detection. This module is prevention: the same rules,
pushed down to where no code path can go around them.

ONE DEFINITION, TWO DIALECTS
----------------------------
Each invariant is declared ONCE, as a boolean SQL expression that must hold, and
the DDL is generated per dialect:

  · **Postgres** — a real ``CHECK`` constraint.
  · **SQLite** — ``CREATE TRIGGER … WHEN NOT (<expr>) … RAISE(ABORT)``, because
    SQLite cannot add a CHECK to an existing table without rebuilding it, and
    rebuilding live money tables to add a guard is a worse trade than a trigger.

Writing the rule twice, once per dialect, is exactly the drift that rule 12 was
recorded for — so the rule exists in one place and the translation is mechanical.
``tests/test_db_invariants.py`` then proves enforcement *behaviourally* on
whichever dialect is running, by attempting a violating write. Emitting DDL is
not evidence that anything is enforced.

REFUSES TO INSTALL OVER EXISTING VIOLATIONS
-------------------------------------------
Same discipline as the M-3 unique index. If rows already break a rule, the
constraint is skipped and the offending rows are logged at ERROR with their ids.
Silently "correcting" historical money data is not a migration's decision, and a
constraint that fails to install must say so rather than disappear.

WHAT IS DELIBERATELY *NOT* HERE
-------------------------------
The baseline review suggested ``CHECK (paid_amount <= total_amount)``. That
constraint is **wrong for this product** and is omitted on purpose, with the
reason recorded so it is not "fixed" later by someone reading the older review:

``core/sync/apply_hooks.reconcile_invoice_paid_state`` sets
``paid_amount = SUM(invoice_payments.amount_paid)`` with no cap, because an
overpayment is a real event — a customer settles a round figure, the excess is
booked to Customer Advances (``post_advance_receipt``), and the invoice honestly
records what was received against it. Constraining ``paid_amount`` would reject
that receipt at the counter. The invariant that actually matters here — that
overpayment must not produce a negative receivable — is a property of the journal
builders and is already pinned in ``tests/test_money_pure_functions.py``.
"""
from __future__ import annotations

import logging
from typing import List, NamedTuple, Optional

from sqlalchemy import text

logger = logging.getLogger("bizassist.db_invariants")


class Invariant(NamedTuple):
    """One money rule.

    ``condition``  — SQL boolean over the row that must be TRUE. Written so that
                     NULL-tolerance is explicit; a NULL comparison is neither
                     true nor false, and a rule that silently passes on NULL is
                     the M-1 mistake in a different costume.
    ``columns``    — the columns the trigger must watch (SQLite triggers are
                     per-statement, so this documents intent rather than
                     narrowing the trigger).
    ``why``        — what goes wrong in the product if this is violated. Required.
    """
    name: str
    table: str
    condition: str
    columns: tuple
    why: str


# ── The rules ────────────────────────────────────────────────────────────────
# Every one of these was checked against the real databases in this repo before
# being added (`bizassist.db`, `test_bizassist.db`): zero existing violations.
INVARIANTS: List[Invariant] = [
    Invariant(
        name="ck_invoice_payments_amount_positive",
        table="invoice_payments",
        condition="amount_paid IS NOT NULL AND amount_paid > 0",
        columns=("amount_paid",),
        why=(
            "A receipt of zero or a negative amount is not a receipt. The refund "
            "path is a credit note, which is its own document with its own "
            "journal entry. A negative payment row would silently reduce "
            "`paid_amount`, flip a settled invoice back to Pending, and put a "
            "paid customer back on the chasing list."
        ),
    ),
    Invariant(
        name="ck_journal_lines_single_sided",
        table="journal_lines",
        condition="NOT (COALESCE(debit,0) <> 0 AND COALESCE(credit,0) <> 0)",
        columns=("debit", "credit"),
        why=(
            "A journal line is a debit or a credit, never both. A two-sided line "
            "still foots, so `post_entry`'s balance guard passes it — but the "
            "trial balance, the P&L and the party ledger all read the columns "
            "separately and would each disagree. This is the shape of error that "
            "balances and is still wrong."
        ),
    ),
    Invariant(
        name="ck_journal_lines_non_negative",
        table="journal_lines",
        condition="COALESCE(debit,0) >= 0 AND COALESCE(credit,0) >= 0",
        columns=("debit", "credit"),
        why=(
            "Negative amounts are how an unbalanced entry is made to look "
            "balanced. Double entry expresses direction with the COLUMN, not the "
            "sign; allowing both gives every amount two representations and makes "
            "the hash chain's tamper-evidence argument weaker than it reads."
        ),
    ),
    Invariant(
        name="ck_invoices_paid_amount_non_negative",
        table="invoices",
        condition="COALESCE(paid_amount,0) >= 0",
        columns=("paid_amount",),
        why=(
            "`paid_amount` is a projection of the payment ledger, and the ledger "
            "cannot sum below zero once payments themselves are positive. A "
            "negative value here means the projection was written by something "
            "other than the projection — the M-7 class of defect."
        ),
    ),
    Invariant(
        name="ck_document_sequences_monotonic_floor",
        table="document_sequences",
        condition="COALESCE(last_number,0) >= 0",
        columns=("last_number",),
        why=(
            "The stored counter that replaced COUNT-based numbering (F-3) is only "
            "safe because it never moves backwards. A negative value would let it "
            "reissue numbers already printed on customers' invoices."
        ),
    ),
    Invariant(
        name="ck_register_shifts_opening_cash_non_negative",
        table="register_shifts",
        condition="COALESCE(opening_cash,0) >= 0",
        columns=("opening_cash",),
        why=(
            "A drawer cannot start with negative cash. `open_shift` rejects it, "
            "but a sync apply or an import writes the row directly, and a "
            "negative float understates `expected_cash` for the whole shift — so "
            "the cashier appears to have a surplus exactly equal to the error."
        ),
    ),
]


# ── Introspection helpers ────────────────────────────────────────────────────

def _tables(conn) -> set:
    from sqlalchemy import inspect as sa_inspect
    return set(sa_inspect(conn).get_table_names())


def _columns(conn, table: str) -> set:
    """Column names on ``table``.

    Deliberately does NOT swallow. It used to ``return set()`` on any exception,
    which made an introspection FAILURE indistinguishable from "the table has
    none of the columns this rule needs" — so the invariant was filed under
    `skipped_missing_table` and the operator was told a table was absent when in
    fact the check had broken. A guard that fails to install must say which of the
    two happened. The caller records the real error instead.
    """
    from sqlalchemy import inspect as sa_inspect
    return {c["name"] for c in sa_inspect(conn).get_columns(table)}


def find_violations(conn, inv: Invariant) -> int:
    """How many existing rows already break this rule. -1 if it can't be checked."""
    try:
        return conn.execute(text(
            f"SELECT COUNT(*) FROM {inv.table} WHERE NOT ({inv.condition})"
        )).scalar() or 0
    except Exception as e:
        logger.warning("[N4] could not scan %s for %s: %s", inv.table, inv.name, e)
        return -1


def violation_sample(conn, inv: Invariant, limit: int = 10) -> list:
    """Ids of some offending rows, for the ERROR log.

    This swallow IS deliberate and is the acceptable kind (rule 13): it decorates
    a message that has already been decided on, and the caller has independently
    established via :func:`find_violations` that rows are bad. Losing the sample
    degrades the log; it cannot hide the finding. Logged at WARNING so a failure
    here is still visible rather than absent.
    """
    try:
        rows = conn.execute(text(
            f"SELECT id FROM {inv.table} WHERE NOT ({inv.condition}) LIMIT {int(limit)}"
        )).fetchall()
        return [r[0] for r in rows]
    except Exception as e:
        logger.warning("[N4] could not sample offending rows for %s: %s", inv.name, e)
        return []


# ── Postgres: real CHECK constraints ────────────────────────────────────────

def _pg_constraint_exists(conn, inv: Invariant) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": inv.name}).fetchone())


def _pg_install(conn, inv: Invariant) -> None:
    conn.execute(text(
        f"ALTER TABLE {inv.table} ADD CONSTRAINT {inv.name} CHECK ({inv.condition})"))


# ── SQLite: triggers, because CHECK cannot be added in place ─────────────────
#
# One trigger per (invariant, operation). BEFORE, so the write never lands, and
# RAISE(ABORT) so the transaction is rolled back with a message the developer can
# read — the same failure shape a Postgres CHECK produces.

def _sqlite_trigger_names(inv: Invariant) -> List[str]:
    return [f"{inv.name}_ins", f"{inv.name}_upd"]


def _sqlite_trigger_exists(conn, name: str) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name = :n"),
        {"n": name}).fetchone())


def _sqlite_install(conn, inv: Invariant) -> None:
    # The condition is written against bare column names; inside a trigger the
    # candidate row is `NEW`, so qualify every column reference.
    cond = inv.condition
    for col in sorted(_columns(conn, inv.table), key=len, reverse=True):
        cond = _requalify(cond, col)
    msg = f"{inv.name}: {inv.why.split('.')[0]}"
    for op, name in (("INSERT", f"{inv.name}_ins"), ("UPDATE", f"{inv.name}_upd")):
        conn.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS {name} "
            f"BEFORE {op} ON {inv.table} "
            f"FOR EACH ROW WHEN NOT ({cond}) "
            f"BEGIN SELECT RAISE(ABORT, '{msg[:180]}'); END"
        ))


def _requalify(cond: str, col: str) -> str:
    """Prefix bare occurrences of `col` with `NEW.`, leaving SQL keywords and
    already-qualified references alone. Word-boundary matched so `debit` inside
    `debit_note` is not rewritten."""
    import re
    return re.sub(rf"(?<![\w.]){re.escape(col)}\b", f"NEW.{col}", cond)


# ── Entry point ─────────────────────────────────────────────────────────────

def ensure_invariants(conn, invariants: Optional[List[Invariant]] = None) -> dict:
    """Install every invariant the database can hold. Never raises.

    Returns a report: ``{installed, already, skipped_missing_table,
    skipped_violations, errors}``. Returned rather than logged-and-forgotten so
    the boot path and the tests can both assert on it — a migration that reports
    nothing is indistinguishable from one that did nothing.
    """
    invariants = INVARIANTS if invariants is None else invariants
    report = {"installed": [], "already": [], "skipped_missing_table": [],
              "skipped_violations": {}, "errors": {}}

    is_pg = conn.dialect.name == "postgresql"
    present = _tables(conn)

    for inv in invariants:
        try:
            if inv.table not in present:
                report["skipped_missing_table"].append(inv.name)
                continue

            try:
                present_cols = _columns(conn, inv.table)
            except Exception as e:
                # NOT "assume the columns are missing". An introspection failure
                # is an error, and reporting it as a missing table would tell the
                # operator the guard was skipped for a benign reason.
                report["errors"][inv.name] = f"column introspection failed: {e}"
                logger.error("[N4] could not introspect %s for %s: %s",
                             inv.table, inv.name, e, exc_info=True)
                continue
            missing_cols = set(inv.columns) - present_cols
            if missing_cols:
                # An older schema that has not caught up. Not an error — the
                # column-add migration runs in the same boot, and the next boot
                # installs the guard.
                report["skipped_missing_table"].append(inv.name)
                continue

            if is_pg:
                if _pg_constraint_exists(conn, inv):
                    report["already"].append(inv.name)
                    continue
            else:
                if all(_sqlite_trigger_exists(conn, n) for n in _sqlite_trigger_names(inv)):
                    report["already"].append(inv.name)
                    continue

            bad = find_violations(conn, inv)
            if bad > 0:
                report["skipped_violations"][inv.name] = bad
                logger.error(
                    "[N4] NOT enforcing %s on %s — %s existing row(s) already "
                    "violate it (ids: %s). Why this rule matters: %s "
                    "Resolve the rows; the guard installs on the next boot. "
                    "They are NOT being corrected automatically: rewriting "
                    "historical money data is not a migration's decision.",
                    inv.name, inv.table, bad,
                    violation_sample(conn, inv), inv.why,
                )
                continue
            if bad < 0:
                report["errors"][inv.name] = "violation scan failed"
                continue

            if is_pg:
                _pg_install(conn, inv)
            else:
                _sqlite_install(conn, inv)
            conn.commit()
            report["installed"].append(inv.name)

        except Exception as e:                     # never block boot on a guard
            report["errors"][inv.name] = str(e)
            logger.error("[N4] could not install %s: %s", inv.name, e, exc_info=True)
            try:
                conn.rollback()
            except Exception as rb:
                # Acceptable swallow (rule 13): this is cleanup INSIDE an error
                # path whose failure is already recorded above. Logged anyway so
                # a broken connection is not invisible.
                logger.warning("[N4] rollback after %s failed: %s", inv.name, rb)

    if report["installed"]:
        logger.info("[N4] DB-level money invariants enforced: %s",
                    ", ".join(report["installed"]))
    return report
