"""
scripts/repair_line_items_by_invariant.py — remove phantom line items
=====================================================================
Two document families, one invariant: `invoices` / `invoice_line_items`
(M-16, M-17) and `b2b_orders` / `b2b_order_line_items` (M-18). The title said
"invoice" alone until 2026-07-27, which made a clean B2B result read like a
B2B family that had never been examined — see `scan_scope`.

Removes `invoice_line_items` rows that a batch process appended to invoices that
were already complete, scoped by **the invariant they break** rather than by the
day the breakage was noticed.

    python scripts/repair_line_items_by_invariant.py                # dry run
    python scripts/repair_line_items_by_invariant.py --apply
    python scripts/repair_line_items_by_invariant.py --db path.db --business 6

WHY THIS EXISTS RATHER THAN A SECOND DATED SCRIPT
-------------------------------------------------
`repair_duplicate_line_items.py` closed M-16 by deleting rows created on
2026-07-17. It worked, and it corrected Brownie Factory's P&L from a Rs-6,715 fake
loss to its real Rs+4,648 profit. But its WHERE clause was::

    WHERE li.created_at >= '2026-07-17' AND li.created_at < '2026-07-18'

so it repaired **one day**, not the defect. Audit check I then found a second,
earlier occurrence of the identical corruption still live in business 6 — rows
dated 2026-06-29, 06-30, 07-01 and 07-03, Rs3,298.26 of phantom line value across
six invoices — which that script cannot see and now reports as "0 rows".
Architecture rule 44: scope a repair by the invariant it restores.

THE INVARIANT
-------------
For any invoice, the rows it is made of must sum to what the customer was billed::

    SUM(line_total) == total_amount + cash_discount - round_off

The post-tax cash discount and the round-off sit on the HEADER, not on the lines.
(Getting this wrong produced five false positives on business 7 the first time
audit check I was written — LCL-OW-0027 is 337.65 == 323 + 15 - 0.35.)

HOW THE SPURIOUS ROWS ARE IDENTIFIED — and why this is safe
-----------------------------------------------------------
Not by date, and not by "looks like a duplicate". Line items are written with
their invoice, so **insertion order is evidence**: the genuine rows are the ones
that came first. So we walk the line items in `id` order, accumulating
`line_total`, and look for the PREFIX whose cumulative total reconciles to the
header. Rows after that prefix are the intruders.

This rule is self-validating, which is the whole reason to prefer it:

  * it only ever acts when the surviving rows **exactly** reconcile to a figure
    the invoice already stored independently — the header was written by the
    billing command at sale time and the intruders never touched it;
  * if no prefix reconciles, the script **deletes nothing** and flags the invoice
    for a human. It does not fall back to guessing.

Verified against all six affected invoices in business 6, including the two where
date-batching is useless because both the genuine and the phantom rows share a
calendar day:

    C1-0001  target  991.96  prefix of 4 = 991.98   -> 3 rows spurious
    C1-0002  target 3033.44  prefix of 4 = 3033.40  -> 1 row  spurious
    C1-0003  target  395.87  prefix of 1 =  395.86  -> 1 row  spurious
    C1-0004  target  565.66  prefix of 3 =  565.66  -> 8 rows spurious
    OW-0001  target  186.51  prefix of 1 =  186.51  -> 1 row  spurious
    OW-0003  target  123.71  prefix of 1 =  123.70  -> 1 row  spurious

WHAT IT DOES NOT TOUCH
----------------------
* Invoice headers, payments, journal entries, the stock ledger. Only
  `invoice_line_items` rows are removed. The journal already agrees with the
  headers (it is posted from them), which is exactly why this corruption was
  invisible — so no re-posting is needed and none is done.
* Invoices whose lines already reconcile.
* Zero-value CSV-imported invoices (no totals, nothing to compare).

SAFETY
------
Dry-run by default. Every row that would be deleted is written to a timestamped
JSON export BEFORE the first write. Single transaction, rolled back on any error.
Prints a before/after money diff (invoice value, line value, journal Dr/Cr,
receivables) and re-runs the invariant, because "the audit is clean afterwards" is
not the same as "nothing else moved" (rule 29).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dbcompat import (connect, ensure, resolve_target,  # noqa: E402
                       is_postgres_target, out, use_utf8_stdout, POSTGRES)

TOLERANCE = 1.00      # paise-level rounding only

# (parent table, child table, FK column, id label, target expression)
#
# TWO document families, because the same corruption was found on both:
#   invoices / invoice_line_items        -> M-16, M-17 (single-tenant)
#   b2b_orders / b2b_order_line_items    -> M-18 (TWO-PARTY: both live orders)
#
# b2b_orders has no cash_discount / round_off column, so its target is the plain
# total. Driven from one spec so the prefix rule cannot drift between them.
SPECS = [
    ("invoices", "invoice_line_items", "invoice_id", "invoice_id",
     "COALESCE(p.total_amount,0) + COALESCE(p.cash_discount,0) - COALESCE(p.round_off,0)"),
    ("b2b_orders", "b2b_order_line_items", "order_id", "order_number",
     "COALESCE(p.total_amount,0)"),
]


def _default_db() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "bizassist.db")


def _target(inv) -> float:
    """What SUM(line_total) must equal for this invoice."""
    return round((inv["total_amount"] or 0.0)
                 + (inv["cash_discount"] or 0.0)
                 - (inv["round_off"] or 0.0), 2)


def _table_exists(con, name) -> bool:
    return con.table_exists(name)


def find_offenders(con, business_id=None, specs=None):
    """-> (repairable, unresolved) across every document family. Each entry
    carries the rows to delete."""
    repairable, unresolved, _ = find_offenders_with_scope(con, business_id, specs)
    return repairable, unresolved


def scan_scope(con, business_id=None, specs=None):
    """What this run actually EXAMINED, per document family.

    Exists because a clean verdict has to name its subject. This script drives
    two families (invoices and b2b_orders) but announced only the first: it
    printed "Every INVOICE's line items reconcile to its header" after checking
    both, and "PHANTOM LINE-ITEM REPAIR (M-17)" after M-18 generalised it. A
    reader who wanted to know whether the B2B orders had been looked at could
    not tell from the output, and in the 2026-07-27 session that is exactly the
    wrong conclusion the output invited.

    Rule 33 says a check that cannot see something must not report there is
    nothing to see. The converse is owed too: a check that DID look must say
    what it looked at, and a family whose tables are absent must be reported as
    NOT SCANNED rather than folded into "clean".
    """
    con = ensure(con)
    scope = []
    for parent, child, fk, label, target_expr in (specs or SPECS):
        if not (_table_exists(con, parent) and _table_exists(con, child)):
            scope.append({"parent": parent, "child": child, "present": False,
                          "parents_scanned": 0, "children_scanned": 0})
            continue
        bfilter = _business_filter(parent, business_id)
        n_parent = con.execute(
            f"SELECT COUNT(*) FROM {parent} p "
            f"WHERE COALESCE(p.total_amount,0) <> 0{bfilter}").fetchone()[0]
        n_child = con.execute(
            f"SELECT COUNT(*) FROM {child} c JOIN {parent} p ON c.{fk} = p.id "
            f"WHERE COALESCE(p.total_amount,0) <> 0{bfilter}").fetchone()[0]
        scope.append({"parent": parent, "child": child, "present": True,
                      "parents_scanned": n_parent, "children_scanned": n_child})
    return scope


def find_offenders_with_scope(con, business_id=None, specs=None):
    """-> (repairable, unresolved, scope). Same scan, plus what it covered."""
    con = ensure(con)
    repairable, unresolved = [], []
    for parent, child, fk, label, target_expr in (specs or SPECS):
        if not (_table_exists(con, parent) and _table_exists(con, child)):
            continue
        r, u = _find_in(con, parent, child, fk, label, target_expr, business_id)
        repairable += r
        unresolved += u
    return repairable, unresolved, scan_scope(con, business_id, specs)


def _business_filter(parent, business_id):
    """The --business predicate for one family. Extracted so the scan and the
    scope report cannot disagree about what was in scope."""
    if not business_id:
        return ""
    if parent == "b2b_orders":
        # b2b_orders is scoped by TWO owner columns, so a --business filter has
        # to OR them; invoices carry a single business_id.
        return (f" AND (p.seller_business_id = {int(business_id)}"
                f" OR p.buyer_business_id = {int(business_id)})")
    return f" AND p.business_id = {int(business_id)}"


def _find_in(con, parent, child, fk, label, target_expr, business_id):
    bfilter = _business_filter(parent, business_id)

    offenders = con.execute(f"""
        SELECT p.id, p.{label} AS doc_no, p.total_amount, ({target_expr}) AS target
          FROM {parent} p
          JOIN {child} c ON c.{fk} = p.id
         WHERE COALESCE(p.total_amount, 0) <> 0{bfilter}
         GROUP BY p.id
        HAVING ABS(COALESCE(SUM(c.line_total), 0) - ({target_expr}))
               > {TOLERANCE}
         ORDER BY p.id""").fetchall()

    repairable, unresolved = [], []
    for inv in offenders:
        target = round(inv["target"] or 0.0, 2)
        lines = con.execute(
            f"SELECT id, product_name, quantity, unit_price, line_total, created_at "
            f"FROM {child} WHERE {fk} = ? ORDER BY id",
            (inv["id"],)).fetchall()

        # Walk insertion order; find the prefix that reconciles to the header.
        running, cut = 0.0, None
        for idx, l in enumerate(lines):
            running = round(running + (l["line_total"] or 0.0), 2)
            if abs(running - target) <= TOLERANCE:
                cut = idx + 1
                break

        entry = {
            "parent_table": parent,
            "child_table": child,
            "invoice_db_id": inv["id"],
            "invoice_no": inv["doc_no"],
            "header_total": inv["total_amount"],
            "target_line_sum": target,
            "actual_line_sum": round(sum(l["line_total"] or 0.0 for l in lines), 2),
            "line_count": len(lines),
        }

        if cut is None or cut == len(lines):
            # No prefix reconciles (or the whole set does, which contradicts the
            # HAVING clause). Either way this is not ours to decide.
            entry["reason"] = ("no prefix of the line items reconciles to the "
                              "header — the header may be the wrong side")
            entry["lines"] = [dict(l) for l in lines]
            unresolved.append(entry)
            continue

        entry["keep_count"] = cut
        entry["keep"] = [dict(l) for l in lines[:cut]]
        entry["delete"] = [dict(l) for l in lines[cut:]]
        entry["delete_value"] = round(
            sum(l["line_total"] or 0.0 for l in lines[cut:]), 2)
        repairable.append(entry)

    return repairable, unresolved


MISSING = "TABLE ABSENT"

# The ONLY figures this repair may move are the line-item counts and values of
# the families it touches. Anything else changing is a bug in the repair, so it
# both aborts the transaction and is labelled loudly (rule 29). Keeping this
# list in step with SPECS matters: mislabelling a correct change as UNEXPECTED
# trains the operator to ignore the label.
_MAY_MOVE = ("line_items", "line_value", "b2b_lines", "b2b_line_value")


def money_snapshot(con) -> dict:
    """The before/after money diff (rule 29).

    Every figure is guarded on the table existing. It was not: a database
    without `b2b_order_line_items` — any install predating the B2B mirror —
    crashed the script with `no such table` BEFORE it repaired a single invoice.
    A repair script that dies on an older schema is a repair script that does not
    run where it is most likely to be needed.

    A missing table reports the sentinel ``TABLE ABSENT``, never 0. Zero is a
    measurement; absent is not, and the diff must not be able to claim a
    quantity it could not read (rule 33).
    """
    con = ensure(con)

    def g(sql, table):
        if not _table_exists(con, table):
            return None
        return con.execute(sql).fetchone()[0] or 0.0

    def count(table):
        v = g(f"SELECT COUNT(*) FROM {table}", table)
        return MISSING if v is None else int(v)

    def total(col, table):
        v = g(f"SELECT SUM(COALESCE({col},0)) FROM {table}", table)
        return MISSING if v is None else round(v, 2)

    return {
        "invoices": count("invoices"),
        "invoice_value": total("total_amount", "invoices"),
        "paid_total": total("paid_amount", "invoices"),
        "payments": count("invoice_payments"),
        "payments_sum": total("amount_paid", "invoice_payments"),
        "journal_dr": total("debit", "journal_lines"),
        "journal_cr": total("credit", "journal_lines"),
        "line_items": count("invoice_line_items"),
        "line_value": total("line_total", "invoice_line_items"),
        "b2b_lines": count("b2b_order_line_items"),
        "b2b_line_value": total("line_total", "b2b_order_line_items"),
        "stock_rows": count("stock_ledger"),
    }


def c_label(con) -> str:
    """The connection's identity, with any password already redacted."""
    return con.label


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Remove phantom line items from invoices AND b2b_orders "
                    "(M-16 / M-17 / M-18).")
    ap.add_argument("--db", default=None,
                    help="SQLite file path OR a postgresql:// URL. Defaults to "
                         "$BIZASSIST_AUDIT_DATABASE_URL, then backend/bizassist.db.")
    ap.add_argument("--business", type=int, default=None)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete. Without it, nothing is modified.")
    ap.add_argument("--export", default=None)
    ap.add_argument("--i-have-a-restorable-backup", action="store_true",
                    dest="backup_ack",
                    help="required with --apply against a REMOTE (Postgres) "
                         "database. There is no .bak next to a cloud DB.")
    args = ap.parse_args()

    target = resolve_target(args.db)

    # ── Production rail — BEFORE the connection is opened ───────────────────
    # A local SQLite run sits next to bizassist.db.bak and can be undone by
    # copying a file back. A cloud Postgres run cannot. The transaction-level
    # verification below makes a BAD repair safe; it does nothing about a
    # CORRECT repair aimed at the wrong database, and only the operator knows
    # whether a restore point exists. So --apply on Postgres is refused unless
    # that is stated explicitly. Deliberately not a y/n prompt: this must be
    # answerable in a runbook and visible in shell history.
    #
    # Checked on the TARGET STRING, not on `con.dialect`, so the refusal does
    # not depend on the connection succeeding. Ordered the other way round, the
    # operator's first response is "psycopg2 is not installed" — they install it,
    # re-run the same command, and the rail is the only thing that was ever
    # standing between them and a live delete.
    if args.apply and is_postgres_target(target) and not args.backup_ack:
        sys.exit(
            "\n  REFUSING to --apply against a PostgreSQL database without "
            "--i-have-a-restorable-backup.\n"
            "  This deletes rows from a live database that has no .bak beside "
            "it.\n\n"
            "  Do this first:\n"
            "    1. Take a restorable snapshot / pg_dump of the database.\n"
            "    2. Run the DRY RUN (no --apply) and read every line it lists.\n"
            "    3. Run scripts/audit_money_integrity.py and confirm which\n"
            "       checks are dirty BEFORE changing anything.\n"
            "  Then re-run with --i-have-a-restorable-backup.\n")

    con = connect(target, readonly=not args.apply)
    mode = "APPLYING" if args.apply else "DRY RUN"
    out("=" * 78)
    out(f"PHANTOM LINE-ITEM REPAIR  [{mode}]   (M-16 / M-17 / M-18)")
    out(f"{c_label(con)}   engine: {con.dialect}"
          + ("" if args.apply else "   mode: read-only"))
    out("=" * 78)

    before = money_snapshot(con)
    repairable, unresolved, scope = find_offenders_with_scope(con, args.business)

    # Say what was examined BEFORE saying whether it was clean. A verdict with no
    # named subject is how "nothing to do" gets read as "never looked".
    out("\n  Scanned:")
    for s in scope:
        if not s["present"]:
            out(f"      {s['parent']:<14} NOT SCANNED - table absent from this database")
        else:
            out(f"      {s['parent']:<14} {s['parents_scanned']:>5} document(s) "
                  f"with a non-zero total, {s['children_scanned']:>5} line item(s)")
    if any(not s["present"] for s in scope):
        out("      ^ an absent family is NOT a clean family (rule 33).")

    if not repairable and not unresolved:
        scanned = sum(s["parents_scanned"] for s in scope)
        if scanned == 0:
            # "Clean" over an empty scan is not a clean result (rule 33). The
            # commonest cause is a --business that matches nothing, which
            # otherwise prints the same reassuring line as a real all-clear.
            out("\n  NOTHING WAS SCANNED - 0 documents matched"
                  + (f" --business {args.business}" if args.business else "")
                  + ".\n  This is NOT an all-clear. Nothing was examined.")
            return 2
        out(f"\n  All {scanned} document(s) above reconcile to their headers. "
              f"Nothing to do.")
        return 0

    total_del = sum(len(e["delete"]) for e in repairable)
    total_val = round(sum(e["delete_value"] for e in repairable), 2)

    for e in repairable:
        out(f"\n  {e['parent_table']}  {e['invoice_no']}")
        out(f"      header {e['header_total']}  ->  lines must total "
              f"{e['target_line_sum']}")
        out(f"      {e['line_count']} line(s) totalling {e['actual_line_sum']}; "
              f"first {e['keep_count']} reconcile — KEEPING those")
        for l in e["delete"]:
            out(f"        DELETE li={l['id']:<5} {str(l['product_name'])[:26]:<26} "
                  f"{l['line_total']:>9}  created {str(l['created_at'])[:10]}")

    for e in unresolved:
        out(f"\n  [REVIEW] {e['parent_table']}  {e['invoice_no']}: {e['reason']}")
        out(f"      header target {e['target_line_sum']} vs "
              f"lines {e['actual_line_sum']} ({e['line_count']} rows)")

    out("\n" + "-" * 78)
    out(f"  repairable invoices : {len(repairable)}")
    out(f"  rows to delete      : {total_del}  (phantom line value {total_val})")
    out(f"  needing review      : {len(unresolved)}")

    if not args.apply:
        out("\n  DRY RUN — nothing modified. Re-run with --apply.")
        return 0

    # Where to put the export. "Next to the database" only means something for a
    # file; a Postgres URL has no directory, and joining on it produced a path
    # under `postgresql:/` that would never be found again. Falls back to the
    # current directory, and says where it went either way.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.export:
        export_path = args.export
    elif con.dialect == POSTGRES:
        export_path = os.path.abspath(f"phantom_line_items_export_{stamp}.json")
    else:
        export_path = os.path.join(os.path.dirname(os.path.abspath(target)),
                                   f"phantom_line_items_export_{stamp}.json")
    with open(export_path, "w", encoding="utf-8") as f:
        # `con.label` and NOT the raw target: a Postgres DSN carries the
        # password, and this file is written to disk and often pasted into a
        # ticket. Redacted at the source in _dbcompat so no caller can leak it.
        json.dump({"generated_at": datetime.now().isoformat(),
                   "database": con.label, "engine": con.dialect,
                   "repairable": repairable, "unresolved": unresolved},
                  f, indent=2, default=str)
    out(f"\n  export written: {export_path}")

    # ── The write, VERIFIED BEFORE IT IS COMMITTED ──────────────────────────
    #
    # The old shape was: delete, COMMIT, then re-check the invariant and print
    # the money diff. If the re-check came back dirty there was nothing left to
    # do about it — the rows were gone. That was survivable against a local
    # SQLite file next to a `.bak`; it is not the right shape for a cloud
    # Postgres database serving live businesses.
    #
    # Now every check runs INSIDE the transaction, and the commit happens only
    # if all of them pass:
    #   * the invariant re-scan finds nothing repairable left;
    #   * no money figure outside the line-item counts moved.
    # Anything else rolls back and exits non-zero, having changed nothing.
    deleted = 0
    try:
        if con.dialect != POSTGRES:
            # psycopg2 already opens a transaction implicitly; SQLite needs it.
            con.execute("BEGIN")
        # Grouped by child table: the two families live in different tables and a
        # single DELETE cannot span them.
        by_table = {}
        for e in repairable:
            by_table.setdefault(e["child_table"], []).extend(
                l["id"] for l in e["delete"])
        for tbl, ids in by_table.items():
            marks = ",".join("?" * len(ids))
            deleted += con.execute(
                f"DELETE FROM {tbl} WHERE id IN ({marks})", ids).rowcount

        after = money_snapshot(con)
        still, still_unres = find_offenders(con, args.business)
        problems = []
        if still:
            problems.append(f"{len(still)} document(s) still violate the invariant")
        for k in before:
            if before[k] == MISSING or after[k] == MISSING:
                continue
            if k not in _MAY_MOVE and round(after[k] - before[k], 2) != 0:
                problems.append(
                    f"{k} moved {before[k]} -> {after[k]}, and this repair is "
                    f"only allowed to change line-item counts and values")
        if problems:
            con.rollback()
            out("\n  ROLLED BACK — the post-delete verification failed:")
            for p in problems:
                out(f"      - {p}")
            out("  Nothing was changed. The export above records what would "
                  "have been deleted.")
            con.close()
            return 1
        con.commit()
    except Exception as exc:
        con.rollback()
        sys.exit(f"  FAILED, rolled back: {exc}")

    out(f"  deleted {deleted} row(s)\n")
    out("  " + "-" * 74)
    out(f"  {'metric':<18}{'before':>14}{'after':>14}   delta")
    for k in before:
        if before[k] == MISSING or after[k] == MISSING:
            # Not measurable, so no delta may be asserted either way.
            out(f"  {k:<18}{str(before[k]):>14}{str(after[k]):>14}   "
                  f"n/a  <== NOT MEASURED")
            continue
        d = round(after[k] - before[k], 2)
        flag = "" if d == 0 else ("  <== expected" if k in _MAY_MOVE
                                  else "  <== UNEXPECTED")
        out(f"  {k:<18}{before[k]:>14}{after[k]:>14}   {d}{flag}")

    out(f"\n  invariant re-checked BEFORE commit: {len(still)} repairable, "
          f"{len(still_unres)} needing review")
    integ = con.integrity_report()
    out(f"  integrity: {integ['integrity']}   "
          f"fk: {integ['fk_violations']} violation(s)")
    out(f"  ({integ['note']})")
    out("\n  Re-run scripts/audit_money_integrity.py to confirm check I is clean.")
    con.close()
    ok = (not still
          and integ["integrity"] in ("ok", "n/a (engine-enforced)")
          and integ["fk_violations"] == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
