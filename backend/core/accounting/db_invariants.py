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
    msg = _sql_literal(f"{inv.name}: {inv.why.split('.')[0]}"[:180])
    for op, name in (("INSERT", f"{inv.name}_ins"), ("UPDATE", f"{inv.name}_upd")):
        conn.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS {name} "
            f"BEFORE {op} ON {inv.table} "
            f"FOR EACH ROW WHEN NOT ({cond}) "
            f"BEGIN SELECT RAISE(ABORT, {msg}); END"
        ))


def _sql_literal(msg: str) -> str:
    """A single-quoted SQL string literal with embedded quotes escaped.

    NOT cosmetic. The trigger body is assembled as text, so one apostrophe in a
    `why` string terminates the literal early and the whole CREATE TRIGGER
    becomes a syntax error — which `ensure_*` catches, files under `errors`, and
    the app boots on without the guard. A rule that silently fails to install is
    the exact failure this module exists to prevent, and it would have been
    triggered by nothing more than writing "another tenant's invoice".

    Caught by test_tenant_fk_invariants.py on the first run. The CHECK-rule
    installer above had the same latent hole; it survived only because none of
    the six existing `why` strings happens to contain an apostrophe in its first
    sentence.
    """
    return "'" + str(msg).replace("'", "''") + "'"


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


# ═════════════════════════════════════════════════════════════════════════════
# TENANT-INTEGRITY REFERENCES
# ═════════════════════════════════════════════════════════════════════════════
#
# WHY THIS IS A SECOND KIND OF RULE AND NOT ANOTHER `Invariant`
# -------------------------------------------------------------
# Everything above is a predicate over ONE row, which is why it compiles to a
# CHECK on Postgres. The rule here is about a row's relationship to its PARENT,
# and `CHECK` on Postgres may not contain a subquery. Expressed as a CHECK it
# would either fail to install or, worse, be rewritten by a future reader into
# something that installs and checks nothing.
#
# So it compiles to what each engine actually offers:
#   · Postgres — a UNIQUE (id, business_id) on the parent plus a COMPOSITE
#     FOREIGN KEY (fk_col, business_id) on the child. The engine then refuses
#     the write. No code path can go around it, including sync apply, imports,
#     and every script in backend/scripts.
#   · SQLite — a BEFORE trigger, same reason the CHECKs above are triggers:
#     a constraint cannot be added to an existing table without rebuilding it,
#     and rebuilding live money tables is the worse trade.
#
# WHAT THIS IS FOR — MEASURED, 2026-08-01
# ---------------------------------------
#     uid e10f6d92-e55a-4b49-9fcb-b4679bdc56dd   Rs 45.00 cash
#       local : invoice 457, business 8  (BA-W9J21Y)  total  45.00  -> correct
#       cloud : invoice 786, business 7  (BA-JABXGD)  total 424.00  -> overpaid
#
# One receipt, two tenants' books. It was possible because
# `invoice_payments.invoice_id` references `invoices.id` ALONE — the tenant is
# not part of the relationship — while `invoices` carries
# UNIQUE (business_id, invoice_id), i.e. invoice NUMBERS are unique only per
# business. So "LCL-OW-0003" names a different document in every tenant, and
# anything resolving a parent by number rather than by uid can land in the wrong
# one and produce a row that is perfectly self-consistent on arrival.
#
# That last part is why detection was never going to be enough:
# `audit_money_integrity` scored BOTH databases clean, correctly. The cloud row
# carries business_id = 7, matching the invoice it hangs off. The defect existed
# only in the comparison between two databases, and no single-database audit can
# see it. A constraint does not have to see it — it makes the write fail.
#
# NOT THE REJECTED `paid_amount <= total_amount`
# ----------------------------------------------
# Stated explicitly because the shapes rhyme. That one was refused because
# overpayment is a REAL EVENT the product must be able to record (see "WHAT IS
# DELIBERATELY NOT HERE" at the top of this file). This one forbids nothing the
# product does: there is no legitimate operation that attaches a child row to
# another tenant's parent. It removes an outcome, not a capability.


class TenantFK(NamedTuple):
    """A child row must belong to the same tenant as its parent.

    ``child``/``parent``  — table names.
    ``fk_column``         — the column on ``child`` pointing at ``parent.id``.
    ``tenant``            — the column carrying the tenant on BOTH tables.
    ``why``               — what goes wrong in the product. Required.
    """
    name: str
    child: str
    parent: str
    fk_column: str
    tenant: str
    why: str


def _tfk(child, fk_column, parent, why, tenant="business_id") -> TenantFK:
    return TenantFK(name=f"fk_tenant_{child}_{fk_column}", child=child,
                    parent=parent, fk_column=fk_column, tenant=tenant, why=why)


# Scanned against the local database 2026-08-01: every one of these has ZERO
# existing violations there. The cloud has at least one (invoice_payments →
# invoices, the row above); `ensure_tenant_fks` will therefore SKIP that rule
# and log it until the row is repaired, then install on the next boot. That
# skip is the designed behaviour, not a failure — see the module docstring.
TENANT_FKS: List[TenantFK] = [
    _tfk("invoice_payments", "invoice_id", "invoices",
         "A receipt on another tenant's invoice is money on the wrong books. It "
         "inflates that tenant's paid_amount, settles an invoice nobody paid, "
         "and removes a real receipt from the payer's own ledger. This is the "
         "defect measured on 2026-08-01 and the reason this rule exists."),
    _tfk("invoice_payments", "customer_id", "customers",
         "A receipt attributed to another tenant's customer puts the payment on "
         "a stranger's party ledger and corrupts both businesses' statements."),
    _tfk("invoices", "customer_id", "customers",
         "An invoice billed to another tenant's customer leaks the buyer's "
         "identity across a tenant boundary and misfiles the receivable."),
    _tfk("payments", "invoice_id", "invoices",
         "The legacy payments table has the same shape as invoice_payments and "
         "therefore the same failure mode; leaving it unguarded would move the "
         "defect rather than close it."),
    _tfk("inventory", "product_id", "products",
         "Stock counted against another tenant's product silently moves "
         "inventory value between two businesses' balance sheets."),
    _tfk("inventory", "vendor_id", "vendors",
         "A stock line sourced from another tenant's vendor misstates purchase "
         "history and the payable it implies."),
    _tfk("stock_ledger", "product_id", "products",
         "The stock ledger is the audit trail behind every valuation; a movement "
         "on another tenant's product makes both tenants' valuations wrong and "
         "the trail unreconcilable."),
    _tfk("product_barcodes", "product_id", "products",
         "A barcode pointing at another tenant's product sells the wrong item at "
         "the counter — the failure surfaces as a sale, not as a data error."),
    _tfk("products", "variant_of", "products",
         "A variant parented to another tenant's product exposes that tenant's "
         "catalogue through the variant tree."),
    _tfk("purchase_invoices", "supplier_id", "vendors",
         "A purchase invoice against another tenant's supplier misstates the "
         "payable and the party ledger it posts to."),
    _tfk("purchase_orders", "vendor_id", "vendors",
         "An order raised on another tenant's vendor sends a commitment on "
         "behalf of a business that never made it."),
    _tfk("shift_cash_movements", "shift_id", "register_shifts",
         "Cash moved into another tenant's shift breaks the drawer count for "
         "both — and a drawer that does not reconcile is a cashier accused."),
    _tfk("shift_cash_movements", "expense_id", "expenses",
         "An expense drawn against another tenant's record puts the cost on the "
         "wrong P&L."),
]


def _tenant_violation_sql(fk: TenantFK, select: str) -> str:
    """Portable join between child and parent where the tenants disagree.

    Deliberately calls NO dialect-specific function (rules 51 and 59). NULLs on
    either side are excluded rather than compared: SQL three-valued logic makes
    `NULL <> 7` neither true nor false, and a rule that silently passes on NULL
    is the M-1 mistake in a different costume.
    """
    return (
        f"SELECT {select} FROM {fk.child} c "
        f"JOIN {fk.parent} p ON p.id = c.{fk.fk_column} "
        f"WHERE c.{fk.tenant} IS NOT NULL AND p.{fk.tenant} IS NOT NULL "
        f"AND c.{fk.tenant} <> p.{fk.tenant}"
    )


def find_tenant_violations(conn, fk: TenantFK) -> int:
    """Rows already pointing across a tenant boundary. -1 if unscannable."""
    try:
        return conn.execute(text(_tenant_violation_sql(fk, "COUNT(*)"))).scalar() or 0
    except Exception as e:
        logger.warning("[N4-T] could not scan %s for %s: %s", fk.child, fk.name, e)
        return -1


def tenant_violation_sample(conn, fk: TenantFK, limit: int = 10) -> list:
    """(child id, child tenant, parent tenant) for the ERROR log.

    Acceptable swallow (rule 13): decorates a finding already established by
    :func:`find_tenant_violations`. Losing it degrades the message; it cannot
    hide the finding.
    """
    try:
        rows = conn.execute(text(_tenant_violation_sql(
            fk, f"c.id, c.{fk.tenant}, p.{fk.tenant}") + f" LIMIT {int(limit)}")
        ).fetchall()
        return [tuple(r) for r in rows]
    except Exception as e:
        logger.warning("[N4-T] could not sample offenders for %s: %s", fk.name, e)
        return []


# ── Postgres ────────────────────────────────────────────────────────────────

def _pg_parent_unique_name(fk: TenantFK) -> str:
    return f"uq_{fk.parent}_id_{fk.tenant}"


def _pg_named_constraint_exists(conn, name: str) -> bool:
    return bool(conn.execute(text(
        "SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}).fetchone())


def _pg_install_tenant_fk(conn, fk: TenantFK) -> None:
    # The composite FK needs a matching UNIQUE on the parent. Several children
    # share one parent, so this is created once and reused — hence the existence
    # check rather than IF NOT EXISTS, which ADD CONSTRAINT does not support.
    uq = _pg_parent_unique_name(fk)
    if not _pg_named_constraint_exists(conn, uq):
        conn.execute(text(
            f"ALTER TABLE {fk.parent} ADD CONSTRAINT {uq} "
            f"UNIQUE (id, {fk.tenant})"))
    # MATCH SIMPLE (the default) means the constraint does not apply when either
    # column is NULL. That is what we want: a child with no parent set, or no
    # tenant set, is governed by the existing single-column FK and by the rules
    # above, and tightening it here would reject rows the product legitimately
    # writes today.
    conn.execute(text(
        f"ALTER TABLE {fk.child} ADD CONSTRAINT {fk.name} "
        f"FOREIGN KEY ({fk.fk_column}, {fk.tenant}) "
        f"REFERENCES {fk.parent} (id, {fk.tenant})"))


# ── SQLite ──────────────────────────────────────────────────────────────────

def _sqlite_tenant_trigger_names(fk: TenantFK) -> List[str]:
    return [f"{fk.name}_ins", f"{fk.name}_upd"]


def _sqlite_install_tenant_fk(conn, fk: TenantFK) -> None:
    msg = _sql_literal(f"{fk.name}: {fk.why.split('.')[0]}"[:180])
    lookup = (f"(SELECT p.{fk.tenant} FROM {fk.parent} p "
              f"WHERE p.id = NEW.{fk.fk_column})")
    # Fires only when there IS a parent and both tenants are known — same
    # NULL semantics as the Postgres MATCH SIMPLE path above, so the two engines
    # accept and reject exactly the same rows.
    when = (f"NEW.{fk.fk_column} IS NOT NULL AND NEW.{fk.tenant} IS NOT NULL "
            f"AND {lookup} IS NOT NULL AND {lookup} <> NEW.{fk.tenant}")
    for op, name in (("INSERT", f"{fk.name}_ins"), ("UPDATE", f"{fk.name}_upd")):
        conn.execute(text(
            f"CREATE TRIGGER IF NOT EXISTS {name} "
            f"BEFORE {op} ON {fk.child} "
            f"FOR EACH ROW WHEN {when} "
            f"BEGIN SELECT RAISE(ABORT, {msg}); END"))


# ── Entry point ─────────────────────────────────────────────────────────────

def ensure_tenant_fks(conn, fks: Optional[List[TenantFK]] = None) -> dict:
    """Install every tenant-integrity reference the database can hold.

    Same contract as :func:`ensure_invariants`: never raises, returns a report,
    and REFUSES to install over existing violations — a constraint that would
    silently reinterpret historical money data is worse than an absent one, and
    the operator needs to be told which rows are blocking it.
    """
    fks = TENANT_FKS if fks is None else fks
    report = {"installed": [], "already": [], "skipped_missing_table": [],
              "skipped_violations": {}, "errors": {}}

    is_pg = conn.dialect.name == "postgresql"
    present = _tables(conn)

    for fk in fks:
        try:
            if fk.child not in present or fk.parent not in present:
                report["skipped_missing_table"].append(fk.name)
                continue
            try:
                child_cols = _columns(conn, fk.child)
                parent_cols = _columns(conn, fk.parent)
            except Exception as e:
                report["errors"][fk.name] = f"column introspection failed: {e}"
                logger.error("[N4-T] could not introspect for %s: %s",
                             fk.name, e, exc_info=True)
                continue
            if ({fk.fk_column, fk.tenant} - child_cols) or (
                    {fk.tenant} - parent_cols):
                report["skipped_missing_table"].append(fk.name)
                continue

            if is_pg:
                if _pg_named_constraint_exists(conn, fk.name):
                    report["already"].append(fk.name)
                    continue
            else:
                if all(_sqlite_trigger_exists(conn, n)
                       for n in _sqlite_tenant_trigger_names(fk)):
                    report["already"].append(fk.name)
                    continue

            bad = find_tenant_violations(conn, fk)
            if bad > 0:
                report["skipped_violations"][fk.name] = bad
                logger.error(
                    "[N4-T] NOT enforcing %s — %s existing row(s) already point "
                    "across a tenant boundary (id, child_tenant, parent_tenant: "
                    "%s). Why this rule matters: %s Resolve the rows on EVERY "
                    "database; the guard installs on the next boot. They are NOT "
                    "being corrected automatically.",
                    fk.name, bad, tenant_violation_sample(conn, fk), fk.why,
                )
                continue
            if bad < 0:
                report["errors"][fk.name] = "violation scan failed"
                continue

            if is_pg:
                _pg_install_tenant_fk(conn, fk)
            else:
                _sqlite_install_tenant_fk(conn, fk)
            conn.commit()
            report["installed"].append(fk.name)

        except Exception as e:                     # never block boot on a guard
            report["errors"][fk.name] = str(e)
            logger.error("[N4-T] could not install %s: %s", fk.name, e,
                         exc_info=True)
            try:
                conn.rollback()
            except Exception as rb:
                logger.warning("[N4-T] rollback after %s failed: %s", fk.name, rb)

    if report["installed"]:
        logger.info("[N4-T] tenant-integrity references enforced: %s",
                    ", ".join(report["installed"]))
    return report
