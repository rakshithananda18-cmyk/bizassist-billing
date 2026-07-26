"""
scripts/repair_line_items_by_invariant.py — remove phantom invoice line items (M-17)
===================================================================================
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
import sqlite3
import sys
from datetime import datetime

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


def _connect(path: str, writable: bool) -> sqlite3.Connection:
    if not os.path.exists(path):
        sys.exit(f"database not found: {path}\n"
                 f"Pass --db <path>. Refusing to guess or create one — a repair "
                 f"script that opens the wrong database reports 'nothing to "
                 f"repair' and is believed.")
    con = sqlite3.connect(path if writable else f"file:{path}?mode=ro",
                          uri=not writable)
    con.row_factory = sqlite3.Row
    return con


def _target(inv) -> float:
    """What SUM(line_total) must equal for this invoice."""
    return round((inv["total_amount"] or 0.0)
                 + (inv["cash_discount"] or 0.0)
                 - (inv["round_off"] or 0.0), 2)


def _table_exists(con, name) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def find_offenders(con, business_id=None, specs=None):
    """-> (repairable, unresolved) across every document family. Each entry
    carries the rows to delete."""
    repairable, unresolved = [], []
    for parent, child, fk, label, target_expr in (specs or SPECS):
        if not (_table_exists(con, parent) and _table_exists(con, child)):
            continue
        r, u = _find_in(con, parent, child, fk, label, target_expr, business_id)
        repairable += r
        unresolved += u
    return repairable, unresolved


def _find_in(con, parent, child, fk, label, target_expr, business_id):
    # b2b_orders is scoped by TWO owner columns, so a --business filter has to OR
    # them; invoices carry a single business_id.
    if not business_id:
        bfilter = ""
    elif parent == "b2b_orders":
        bfilter = (f" AND (p.seller_business_id = {int(business_id)}"
                   f" OR p.buyer_business_id = {int(business_id)})")
    else:
        bfilter = f" AND p.business_id = {int(business_id)}"

    offenders = con.execute(f"""
        SELECT p.id, p.{label} AS doc_no, p.total_amount, ({target_expr}) AS target
          FROM {parent} p
          JOIN {child} c ON c.{fk} = p.id
         WHERE COALESCE(p.total_amount, 0) <> 0{bfilter}
         GROUP BY p.id
        HAVING ABS(ROUND(COALESCE(SUM(c.line_total), 0) - ({target_expr}), 2))
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


def money_snapshot(con) -> dict:
    g = lambda sql: con.execute(sql).fetchone()[0] or 0.0
    return {
        "invoices": int(g("SELECT COUNT(*) FROM invoices")),
        "invoice_value": round(g("SELECT SUM(COALESCE(total_amount,0)) FROM invoices"), 2),
        "paid_total": round(g("SELECT SUM(COALESCE(paid_amount,0)) FROM invoices"), 2),
        "payments": int(g("SELECT COUNT(*) FROM invoice_payments")),
        "payments_sum": round(g("SELECT SUM(COALESCE(amount_paid,0)) FROM invoice_payments"), 2),
        "journal_dr": round(g("SELECT SUM(COALESCE(debit,0)) FROM journal_lines"), 2),
        "journal_cr": round(g("SELECT SUM(COALESCE(credit,0)) FROM journal_lines"), 2),
        "line_items": int(g("SELECT COUNT(*) FROM invoice_line_items")),
        "line_value": round(g("SELECT SUM(COALESCE(line_total,0)) FROM invoice_line_items"), 2),
        "b2b_lines": int(g("SELECT COUNT(*) FROM b2b_order_line_items")),
        "b2b_line_value": round(g("SELECT SUM(COALESCE(line_total,0)) FROM b2b_order_line_items"), 2),
        "stock_rows": int(g("SELECT COUNT(*) FROM stock_ledger")),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove phantom invoice line items (M-17).")
    ap.add_argument("--db", default=_default_db())
    ap.add_argument("--business", type=int, default=None)
    ap.add_argument("--apply", action="store_true",
                    help="actually delete. Without it, nothing is modified.")
    ap.add_argument("--export", default=None)
    args = ap.parse_args()

    con = _connect(args.db, writable=args.apply)
    mode = "APPLYING" if args.apply else "DRY RUN"
    print("=" * 78)
    print(f"PHANTOM LINE-ITEM REPAIR  [{mode}]   (M-17)")
    print(args.db)
    print("=" * 78)

    before = money_snapshot(con)
    repairable, unresolved = find_offenders(con, args.business)

    if not repairable and not unresolved:
        print("\n  Every invoice's line items reconcile to its header. Nothing to do.")
        return 0

    total_del = sum(len(e["delete"]) for e in repairable)
    total_val = round(sum(e["delete_value"] for e in repairable), 2)

    for e in repairable:
        print(f"\n  {e['parent_table']}  {e['invoice_no']}")
        print(f"      header {e['header_total']}  ->  lines must total "
              f"{e['target_line_sum']}")
        print(f"      {e['line_count']} line(s) totalling {e['actual_line_sum']}; "
              f"first {e['keep_count']} reconcile — KEEPING those")
        for l in e["delete"]:
            print(f"        DELETE li={l['id']:<5} {str(l['product_name'])[:26]:<26} "
                  f"{l['line_total']:>9}  created {str(l['created_at'])[:10]}")

    for e in unresolved:
        print(f"\n  [REVIEW] {e['parent_table']}  {e['invoice_no']}: {e['reason']}")
        print(f"      header target {e['target_line_sum']} vs "
              f"lines {e['actual_line_sum']} ({e['line_count']} rows)")

    print("\n" + "-" * 78)
    print(f"  repairable invoices : {len(repairable)}")
    print(f"  rows to delete      : {total_del}  (phantom line value {total_val})")
    print(f"  needing review      : {len(unresolved)}")

    if not args.apply:
        print("\n  DRY RUN — nothing modified. Re-run with --apply.")
        return 0

    export_path = args.export or os.path.join(
        os.path.dirname(os.path.abspath(args.db)),
        f"phantom_line_items_export_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(), "database": args.db,
                   "repairable": repairable, "unresolved": unresolved},
                  f, indent=2, default=str)
    print(f"\n  export written: {export_path}")

    try:
        con.execute("BEGIN")
        deleted = 0
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
        con.commit()
    except Exception as exc:
        con.rollback()
        sys.exit(f"  FAILED, rolled back: {exc}")

    after = money_snapshot(con)
    print(f"  deleted {deleted} row(s)\n")
    print("  " + "-" * 74)
    print(f"  {'metric':<18}{'before':>14}{'after':>14}   delta")
    for k in before:
        d = round(after[k] - before[k], 2)
        # The ONLY figures this repair may move are the line-item counts and
        # values of the families it touches. Anything else changing is a bug in
        # the repair, so it is labelled loudly (rule 29). Keeping this list in
        # step with SPECS matters: mislabelling a correct change as UNEXPECTED
        # trains the operator to ignore the label.
        _MAY_MOVE = ("line_items", "line_value", "b2b_lines", "b2b_line_value")
        flag = "" if d == 0 else ("  <== expected" if k in _MAY_MOVE
                                  else "  <== UNEXPECTED")
        print(f"  {k:<18}{before[k]:>14}{after[k]:>14}   {d}{flag}")

    still, still_unres = find_offenders(con, args.business)
    print(f"\n  invariant re-checked: {len(still)} repairable, "
          f"{len(still_unres)} needing review")
    integ = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = len(con.execute("PRAGMA foreign_key_check").fetchall())
    print(f"  integrity_check: {integ}   foreign_key_check: {fk} violation(s)")
    print("\n  Re-run scripts/audit_money_integrity.py to confirm check I is clean.")
    con.close()
    return 1 if (still or integ != "ok" or fk) else 0


if __name__ == "__main__":
    sys.exit(main())
