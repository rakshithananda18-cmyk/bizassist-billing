#!/usr/bin/env python
"""
clear_foreign_godown_ids.py — drop godown links that point at another database.

WHY
---
`godown_id` was a plain `Column(Integer)` on invoices, inventory,
purchase_invoices, stock_ledger and both ends of stock_transfers — NOT a
declared ForeignKey. `_serialize_orm_obj` only emits a portable `*_uid` for
declared FKs, and `resolve_parent_fk_uids` only inspects declared ones on the
way in, so neither side ever looked at these columns. The LOCAL godown id was
pushed verbatim and written straight through, unverified.

Both databases number their godowns independently from small integers for the
same business, so the value did not go stale upstream — it landed on a REAL,
UNRELATED warehouse. Rows show stock in a godown they were never in.

Declaring the FK fixes every row written from now on. It does nothing for rows
already pushed, which is what this script is for.

WHAT IT DOES
------------
Finds rows whose `godown_id` does not resolve to a `godowns` row OWNED BY THE
SAME BUSINESS, and NULLs the link.

It does not try to guess the right godown. That information was destroyed the
moment an id from another database was written here — matching on name would
invent an attribution nobody recorded, and a confidently wrong warehouse is
worse than a missing one. This is the same choice `resolve_parent_fk_uids`
already makes for a nullable FK it cannot verify (M-9): keep the row, drop the
link, say so.

`stock_transfers.from_godown_id` / `to_godown_id` are NOT NULL, so they cannot
be cleared. They are REPORTED and left alone — a transfer with an unresolvable
endpoint needs a human, not a default.

RUN IT ON BOTH DATABASES. It writes over raw DB-API, so no mapper events fire
and nothing syncs; each database has its own wrong values and must be repaired
in place.

    python scripts/clear_foreign_godown_ids.py                     # dry run, local
    python scripts/clear_foreign_godown_ids.py --apply
    python scripts/clear_foreign_godown_ids.py --db "$CLOUD_URL" --apply \
        --i-have-a-restorable-backup
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from _dbcompat import (connect, is_postgres_target, out,      # noqa: E402
                       resolve_target, use_utf8_stdout)

# table -> nullable godown columns we may clear
NULLABLE = {
    "invoices": ["godown_id"],
    "inventory": ["godown_id"],
    "purchase_invoices": ["godown_id"],
    "stock_ledger": ["godown_id"],
}
# table -> NOT NULL godown columns we may only report
REPORT_ONLY = {
    "stock_transfers": ["from_godown_id", "to_godown_id"],
}


def _dangling(con, table: str, col: str):
    """Rows whose godown link resolves to nothing this business owns.

    The business check is the point, not an extra: an id that exists but belongs
    to ANOTHER business is the worst case — a valid-looking cross-tenant link.
    """
    return con.execute(
        f'SELECT t.id AS row_id, t.business_id AS business_id, t."{col}" AS godown_id '
        f'FROM "{table}" t '
        f'WHERE t."{col}" IS NOT NULL '
        f'  AND NOT EXISTS (SELECT 1 FROM "godowns" g '
        f'                  WHERE g.id = t."{col}" AND g.business_id = t.business_id) '
        f'ORDER BY t.id'
    ).fetchall()


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Clear godown links that point at another database's warehouse.")
    ap.add_argument("--db", default=None,
                    help="SQLite file path OR a postgresql:// URL. Defaults to "
                         "$BIZASSIST_AUDIT_DATABASE_URL, then backend/bizassist.db.")
    ap.add_argument("--apply", action="store_true",
                    help="actually write the change (default is a dry run)")
    ap.add_argument("--i-have-a-restorable-backup", action="store_true",
                    dest="backup_ack",
                    help="required with --apply against a Postgres database")
    args = ap.parse_args()

    target = resolve_target(args.db)
    if args.apply and is_postgres_target(target) and not args.backup_ack:
        sys.exit(
            "\n  Refusing to --apply against Postgres without "
            "--i-have-a-restorable-backup.\n"
            "  This clears a column on live stock and financial documents.\n\n"
            "  Take a backup first, then re-run with "
            "--i-have-a-restorable-backup.\n")

    con = connect(target, readonly=not args.apply)
    mode = "APPLYING" if args.apply else "DRY RUN"
    out(f"\n  clear_foreign_godown_ids — {mode} against {con.label}\n")

    if not con.table_exists("godowns"):
        out("  No `godowns` table on this database. Nothing to do.\n")
        return 0

    total_cleared = 0
    for table, cols in NULLABLE.items():
        if not con.table_exists(table):
            continue
        for col in cols:
            rows = _dangling(con, table, col)
            if not rows:
                out(f"  {table}.{col}: clean")
                continue
            out(f"  {table}.{col}: {len(rows)} row(s) point at a godown this "
                f"business does not own")
            for r in rows[:5]:
                out(f"      id={r['row_id']} business={r['business_id']} "
                    f"godown_id={r['godown_id']} -> NULL")
            if len(rows) > 5:
                out(f"      … and {len(rows) - 5} more")
            if args.apply:
                con.execute(
                    f'UPDATE "{table}" SET "{col}" = NULL WHERE id IN '
                    f'({",".join(str(r["row_id"]) for r in rows)})'
                )
            total_cleared += len(rows)

    flagged = 0
    for table, cols in REPORT_ONLY.items():
        if not con.table_exists(table):
            continue
        for col in cols:
            rows = _dangling(con, table, col)
            if not rows:
                out(f"  {table}.{col}: clean")
                continue
            flagged += len(rows)
            out(f"\n  {table}.{col}: {len(rows)} row(s) unresolvable and NOT NULL "
                f"— left alone, these need a human:")
            for r in rows[:10]:
                out(f"      transfer id={r['row_id']} business={r['business_id']} "
                    f"{col}={r['godown_id']}")

    if args.apply:
        con.commit()
        out(f"\n  Cleared {total_cleared} link(s).")
    else:
        out(f"\n  Would clear {total_cleared} link(s). Re-run with --apply.")
    if flagged:
        out(f"  {flagged} stock_transfer endpoint(s) need manual attention.")
    out("  Remember: run this against BOTH databases — raw writes do not sync.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
