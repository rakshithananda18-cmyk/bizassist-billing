"""
scripts/quarantine_fk_orphans.py — resolve the rows that lost their parent
=========================================================================
Closes check **G** of ``audit_money_integrity.py``: the 18 foreign-key violations
that accumulated while SQLite had ``PRAGMA foreign_keys`` OFF (review finding
N4/§40). Every declared ``ForeignKey`` and ``ondelete="CASCADE"`` in the models was
inert on local installs while the Postgres cloud enforced them, so deletes left
children pointing at rows that no longer exist.

    python scripts/quarantine_fk_orphans.py            # dry run (default)
    python scripts/quarantine_fk_orphans.py --apply
    python scripts/quarantine_fk_orphans.py --db path\\to\\bizassist.db --apply

EVERY AFFECTED ROW IS EXPORTED TO JSON BEFORE ANYTHING IS WRITTEN, so the action
is reversible. Nothing is touched without ``--apply``.

WHY THERE IS NO SINGLE "FIX ORPHANS" RULE
-----------------------------------------
The tempting shortcut is "delete every row that fails the FK check". That would
destroy money evidence. The disposition depends on whether the dangling column can
be severed and on what the row means, so each group is decided on its own
merits — and the reasoning is recorded here because that is the part worth
reviewing, not the SQL.

Measured on ``backend/bizassist.db``, 26 Jul 2026 (18 rows, 6 groups):

**1. `invoices.customer_id` → deleted customer — SEVER (set NULL).**
   1 row: invoice 809 (biz 7, ``LCL-OW-0015``, ₹527) points at customer 59.
   The column is nullable and the invoice stores the customer NAME separately, so
   nothing is lost. This is precisely what ``purge_business_data`` already does
   ("NULLify any remaining foreign keys to customer/vendor"), so the convention
   already exists in the product — these rows simply predate it.

**2. `register_shifts.user_id` → deleted operator — RE-POINT to the owner.**
   1 row, and it is the one with a real operational consequence beyond the FK:
   shift 4 (biz 7) is **status OPEN with ₹8,113 of opening float**, and its
   operator (user 9) no longer exists. Nobody can ever close it: ``get_open_shift``
   is looked up by ``(business_id, user_id)`` and user 9 cannot log in, so the
   drawer stays open forever and that float is stranded outside every tally.
   ``user_id`` is NOT NULL, so it cannot be severed — but the codebase already has
   the answer for exactly this case: ``sync_map._USER_FK_REPOINT_ENTITIES`` re-points
   ``register_shifts.user_id`` at ``business_id`` when a shift arrives from a
   database whose user ids do not exist locally. Same situation, same remedy. The
   owner can then close the shift.

**3. `invoice_line_items.product_id` → deleted product — SEVER (set NULL).**
   4 rows. Nullable, and the line item carries its own ``product_name``, quantity
   and ``line_total`` snapshot — that is the whole point of a line item: it records
   what was sold at the price it sold for, independent of the catalog. Three of the
   four belong to invoices 456/457, which are **live, Paid invoices**. Deleting
   them would silently change the contents of a settled tax invoice.

**4. `stock_ledger.product_id` → deleted product — SEVER (set NULL).**
   3 rows (biz 8, ``sale -1.0`` each, referencing invoices 456/457). The ledger is
   append-only inventory truth, so the movement itself — type, quantity, reference
   — is left exactly as written; only the dangling pointer is cleared, and
   ``product_name`` is already stored on the row. ``rebuild_inventory_cache``
   aggregates by ``product_id``, and there is no product left to aggregate into, so
   nothing that works today stops working. Noted explicitly because severing a
   column on an append-only table deserves a stated justification rather than a
   silent UPDATE.

**5. `product_barcodes.product_id` → deleted product — EXPORT AND DELETE.**
   5 rows (biz 8, imported barcodes for products 41–45). NOT NULL, so it cannot be
   severed. A barcode is nothing but a lookup key: scanning it can only ever
   resolve to a product that does not exist. No money, no audit value.

**6. `invoice_line_items.invoice_id` → deleted invoice — EXPORT AND DELETE, LOUDLY.**
   4 rows, and these are the ones to look at rather than wave through:

       li 68  -> invoice 455 (absent)  Amoxicillin 500mg   ₹39.20
       li 112 -> invoice 806 (absent)  Sunflower Oil 15L   ₹423.77
       li 113 -> invoice 806 (absent)  Sugar 50kg          ₹186.51
       li 114 -> invoice 806 (absent)  Wheat Flour 10kg    ₹255.45
                                                   total   ₹904.93

   ``invoice_id`` is NOT NULL, so they cannot be detached, and the documents they
   belong to are gone — so they are unreachable by every application query (all
   line-item reads go through the invoice). They are evidence of sales whose
   invoices were deleted, which is a real thing to know about; the script prints
   them and writes them to the export, and **does not attempt to guess which
   invoice they belonged to.** Inventing a parent would attach real goods to the
   wrong customer's bill, which is the mistake this whole review has been about.

ORDER MATTERS: line item 68 is orphaned BOTH ways (missing product and missing
invoice). Group 6 removes it, so group 3 must run afterwards and only on
survivors, or the UPDATE would resurrect a row that is about to be deleted.

WHAT THIS SCRIPT DELIBERATELY DOES NOT DO
-----------------------------------------
It does not touch the 420 zero-value CSV-imported invoices, does not renumber
anything, and does not create or remove a journal entry. Two of the three
businesses here had their journals backfilled separately
(``scripts/backfill_journals.py``); the sale entries for invoices 456/457 already
exist and are unaffected, because a journal references its source by ``source_id``,
which is not a foreign key.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

# ── The groups, in execution order ──────────────────────────────────────────
# Each: (key, description, SELECT for the affected rows, action)
#   action = ("delete", table) | ("null", table, column) | ("repoint", table, column, source_column)

GROUPS = [
    dict(
        key="line_items_missing_invoice",
        title="invoice_line_items whose INVOICE no longer exists",
        detail=("Unreachable by every application query (line items are only ever "
                "read through their invoice). invoice_id is NOT NULL so they "
                "cannot be detached. Exported, then deleted. The parent is NOT "
                "guessed."),
        select="""SELECT li.* FROM invoice_line_items li
                  LEFT JOIN invoices i ON li.invoice_id = i.id
                  WHERE i.id IS NULL""",
        money_sql="""SELECT ROUND(COALESCE(SUM(li.line_total),0),2)
                     FROM invoice_line_items li
                     LEFT JOIN invoices i ON li.invoice_id = i.id
                     WHERE i.id IS NULL""",
        action=("delete", "invoice_line_items"),
    ),
    dict(
        key="barcodes_missing_product",
        title="product_barcodes whose PRODUCT no longer exists",
        detail=("A barcode is a lookup key and can only resolve to a missing "
                "product. product_id is NOT NULL. Exported, then deleted."),
        select="""SELECT b.* FROM product_barcodes b
                  LEFT JOIN products p ON b.product_id = p.id
                  WHERE p.id IS NULL""",
        action=("delete", "product_barcodes"),
    ),
    dict(
        key="line_items_missing_product",
        title="invoice_line_items whose PRODUCT no longer exists",
        detail=("The line item records what was sold at the price it sold for, "
                "independently of the catalog. Nullable, so the dangling pointer "
                "is severed and the sale is preserved."),
        select="""SELECT li.* FROM invoice_line_items li
                  LEFT JOIN products p ON li.product_id = p.id
                  WHERE li.product_id IS NOT NULL AND p.id IS NULL""",
        action=("null", "invoice_line_items", "product_id"),
    ),
    dict(
        key="stock_ledger_missing_product",
        title="stock_ledger movements whose PRODUCT no longer exists",
        detail=("Append-only: the movement (type, quantity, reference) is left "
                "exactly as written and product_name is already on the row. Only "
                "the dangling pointer is cleared."),
        select="""SELECT s.* FROM stock_ledger s
                  LEFT JOIN products p ON s.product_id = p.id
                  WHERE s.product_id IS NOT NULL AND p.id IS NULL""",
        action=("null", "stock_ledger", "product_id"),
    ),
    dict(
        key="invoices_missing_customer",
        title="invoices whose CUSTOMER no longer exists",
        detail=("Nullable, and the customer NAME is stored on the invoice. Same "
                "remedy purge_business_data already applies."),
        select="""SELECT i.id, i.business_id, i.invoice_id, i.customer_id,
                         i.customer, i.total_amount
                  FROM invoices i
                  LEFT JOIN customers c ON i.customer_id = c.id
                  WHERE i.customer_id IS NOT NULL AND c.id IS NULL""",
        action=("null", "invoices", "customer_id"),
    ),
    dict(
        key="shifts_missing_user",
        title="register_shifts whose OPERATOR no longer exists",
        detail=("user_id is NOT NULL. Re-pointed at business_id, the same remedy "
                "sync_map._USER_FK_REPOINT_ENTITIES already applies for shifts "
                "arriving from a database whose user ids do not exist locally. "
                "An OPEN shift with a deleted operator can otherwise never be "
                "closed, stranding its float outside every tally."),
        select="""SELECT s.id, s.business_id, s.user_id, s.status,
                         s.opening_cash, s.closing_cash_actual
                  FROM register_shifts s
                  LEFT JOIN users u ON s.user_id = u.id
                  WHERE u.id IS NULL""",
        action=("repoint", "register_shifts", "user_id", "business_id"),
    ),
]


def _connect(path):
    if not os.path.exists(path):
        sys.exit(f"database not found: {path}")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _rows(c, sql):
    return [dict(r) for r in c.execute(sql)]


def main():
    default_db = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "bizassist.db")
    ap = argparse.ArgumentParser(
        description="Resolve foreign-key orphans (audit check G / review N4).")
    ap.add_argument("--db", default=default_db, help="path to the SQLite database")
    ap.add_argument("--apply", action="store_true",
                    help="actually write. Without it, nothing is modified.")
    ap.add_argument("--export", default=None,
                    help="where to write the JSON export (default: alongside the DB)")
    args = ap.parse_args()

    c = _connect(args.db)
    mode = "APPLYING" if args.apply else "DRY RUN"
    print("=" * 74)
    print(f"FK ORPHAN QUARANTINE  [{mode}]")
    print(f"{args.db}")
    print("=" * 74)

    before = len(c.execute("PRAGMA foreign_key_check").fetchall())
    print(f"foreign_key_check before: {before} violation(s)\n")
    if before == 0:
        print("  nothing to do.")
        return 0

    export = {"generated_at": datetime.now().isoformat(), "database": args.db,
              "violations_before": before, "groups": {}}
    total = 0

    for g in GROUPS:
        rows = _rows(c, g["select"])
        export["groups"][g["key"]] = {"title": g["title"], "action": g["action"],
                                      "rows": rows}
        if not rows:
            print(f"[ none ] {g['title']}")
            continue
        total += len(rows)
        verb = {"delete": "DELETE", "null": "SET NULL", "repoint": "RE-POINT"}[g["action"][0]]
        print(f"[{verb:>8}] {g['title']}  ({len(rows)} row(s))")
        for line in g["detail"].split(". "):
            if line.strip():
                print(f"           {line.strip().rstrip('.')}.")
        if g.get("money_sql"):
            amount = c.execute(g["money_sql"]).fetchone()[0]
            print(f"           >> value of the affected line items: Rs {amount}")
        for r in rows[:20]:
            keys = [k for k in ("id", "business_id", "invoice_id", "product_id",
                                "product_name", "line_total", "barcode", "customer",
                                "customer_id", "user_id", "status", "opening_cash",
                                "movement_type", "qty_delta") if k in r]
            print("             " + "  ".join(f"{k}={r[k]!r}" for k in keys))
        if len(rows) > 20:
            print(f"             … and {len(rows) - 20} more")
        print()

    export_path = args.export or os.path.join(
        os.path.dirname(os.path.abspath(args.db)),
        f"fk_orphans_export_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")

    if not args.apply:
        print("-" * 74)
        print(f"  {total} row(s) would be handled. Nothing was modified.")
        print("  Re-run with --apply to write (an export is saved first).")
        return 0

    # Export BEFORE writing, so the action is reversible.
    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, default=str)
    print(f"  export written: {export_path}\n")

    # Foreign keys stay OFF for this connection on purpose: the repairs
    # themselves must be able to touch rows that currently violate a constraint.
    c.execute("PRAGMA foreign_keys=OFF")
    changed = 0
    for g in GROUPS:
        rows = export["groups"][g["key"]]["rows"]
        if not rows:
            continue
        ids = [r["id"] for r in rows]
        marks = ",".join("?" * len(ids))
        kind = g["action"][0]
        if kind == "delete":
            table = g["action"][1]
            cur = c.execute(f"DELETE FROM {table} WHERE id IN ({marks})", ids)
        elif kind == "null":
            table, col = g["action"][1], g["action"][2]
            cur = c.execute(f"UPDATE {table} SET {col} = NULL WHERE id IN ({marks})", ids)
        else:  # repoint
            table, col, src = g["action"][1], g["action"][2], g["action"][3]
            cur = c.execute(
                f"UPDATE {table} SET {col} = {src} WHERE id IN ({marks})", ids)
        changed += cur.rowcount
        print(f"  {kind:>8}: {cur.rowcount} row(s) in {g['action'][1]}")

    c.commit()

    # Re-pointing a shift at its owner can reveal an OVERLAPPING open shift —
    # which is a finding, not a side effect. It was already there and invisible:
    # `get_open_shift` looks up `(business_id, user_id)`, so a shift carrying a
    # foreign user_id was hidden from the one-open-shift check when it was opened.
    # Say so loudly rather than leaving the owner to notice two drawers.
    overlaps = c.execute(
        "SELECT business_id, user_id, COUNT(*) n FROM register_shifts "
        "WHERE status='OPEN' GROUP BY business_id, user_id HAVING COUNT(*) > 1"
    ).fetchall()
    if overlaps:
        print()
        print("  !! OVERLAPPING OPEN SHIFTS REVEALED (audit check H / M-11)")
        for o in overlaps:
            detail = c.execute(
                "SELECT id, opening_cash, start_time FROM register_shifts "
                "WHERE status='OPEN' AND business_id=? AND user_id=? "
                "ORDER BY start_time", (o["business_id"], o["user_id"])).fetchall()
            print(f"     business {o['business_id']} operator {o['user_id']}: "
                  f"{o['n']} open shifts")
            for d in detail:
                rung = c.execute(
                    "SELECT COUNT(*), ROUND(COALESCE(SUM(amount_paid),0),2) "
                    "FROM invoice_payments WHERE shift_id=?", (d["id"],)).fetchone()
                print(f"       shift {d['id']}  float {d['opening_cash']}  "
                      f"opened {d['start_time']}  "
                      f"receipts {rung[0]} totalling Rs {rung[1]}")
        print("     These were ALREADY open and hidden — re-pointing only made them")
        print("     visible. Close the stale one from the register screen; its")
        print("     expected cash is computed from the payment ledger. This script")
        print("     will NOT close a shift: a closing figure is a COUNT, and")
        print("     inventing one fabricates a cash count that never happened.")

    after = len(c.execute("PRAGMA foreign_key_check").fetchall())
    integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
    print()
    print("-" * 74)
    print(f"  rows changed            : {changed}")
    print(f"  foreign_key_check after : {after} violation(s)")
    print(f"  integrity_check         : {integrity}")
    if after:
        print("  NOTE: violations remain — re-run to see what is still unresolved.")
    print("-" * 74)
    print("  Re-run scripts/audit_money_integrity.py to confirm check G is clean.")
    c.close()
    return 1 if (after or integrity != "ok") else 0


if __name__ == "__main__":
    sys.exit(main())
