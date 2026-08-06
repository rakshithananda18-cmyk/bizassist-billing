#!/usr/bin/env python
"""
backfill_batch_price_tiers.py — give pre-existing batches their trade tiers.

WHY
---
`inventory` rows are per-batch stock records, and they gained
`wholesale_price` / `distributor_price` so a delivery arriving at a different
trade rate could record that on the BATCH instead of overwriting the product.

The migration is an additive `ALTER TABLE ADD COLUMN`, so every row that already
existed reads NULL. `getPriceOptions` drops any tier that is not > 0, so POS
offers no batch wholesale or distributor price for historic stock until an
intake happens to touch that batch. This seeds them from the batch's own
product, which is exactly what a fresh batch inherits today
(core/stock/ledger.py).

NULL vs 0 IS THE WHOLE DISCRIMINATOR
------------------------------------
· NULL  → the column did not exist when the row was written. Never set.
· 0.0   → written by the ORM (the column default) or typed by the owner, who
          means "this tier does not apply to this batch".

So by default this touches ONLY NULL rows. It cannot silently undo a deliberate
zero, and it stays safe to run at any time — not just immediately after the
migration. `--include-zero` widens it to zeros as well; that CANNOT tell a
never-set value from a deliberate one, so it is opt-in and prints a warning.

Rows are only seeded where the PRODUCT has a tier above zero — there is nothing
useful to copy otherwise, and writing 0 over NULL changes nothing POS can see.

RUN IT ON BOTH DATABASES. It writes over raw DB-API, so no mapper events fire
and nothing syncs; each database holds its own inventory rows.

    python scripts/backfill_batch_price_tiers.py                     # dry run, local
    python scripts/backfill_batch_price_tiers.py --apply
    python scripts/backfill_batch_price_tiers.py --db "$CLOUD_URL" --apply \
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

TIERS = ("wholesale_price", "distributor_price")


def _candidates(con, col: str, include_zero: bool):
    """Batch rows whose tier is unset, where the product has one to give."""
    unset = f'(i."{col}" IS NULL OR i."{col}" = 0)' if include_zero else f'i."{col}" IS NULL'
    return con.execute(
        f'SELECT i.id AS inv_id, i.business_id AS business_id, i.batch_no AS batch_no, '
        f'       i.product_id AS product_id, p.name AS product_name, '
        f'       p."{col}" AS product_tier '
        f'FROM "inventory" i '
        f'JOIN "products" p ON p.id = i.product_id AND p.business_id = i.business_id '
        f'WHERE {unset} AND p."{col}" IS NOT NULL AND p."{col}" > 0 '
        f'ORDER BY i.id'
    ).fetchall()


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Seed batch wholesale/distributor tiers from their product.")
    ap.add_argument("--db", default=None,
                    help="SQLite file path OR a postgresql:// URL. Defaults to "
                         "$BIZASSIST_AUDIT_DATABASE_URL, then backend/bizassist.db.")
    ap.add_argument("--apply", action="store_true",
                    help="actually write the values (default is a dry run)")
    ap.add_argument("--include-zero", action="store_true",
                    help="also seed rows already at 0 — CANNOT tell a never-set "
                         "value from a deliberate 'this tier does not apply'")
    ap.add_argument("--i-have-a-restorable-backup", action="store_true",
                    dest="backup_ack",
                    help="required with --apply against a Postgres database")
    args = ap.parse_args()

    target = resolve_target(args.db)
    if args.apply and is_postgres_target(target) and not args.backup_ack:
        sys.exit(
            "\n  Refusing to --apply against Postgres without "
            "--i-have-a-restorable-backup.\n"
            "  This writes prices onto live stock records.\n\n"
            "  Take a backup first, then re-run with "
            "--i-have-a-restorable-backup.\n")

    con = connect(target, readonly=not args.apply)
    mode = "APPLYING" if args.apply else "DRY RUN"
    out(f"\n  backfill_batch_price_tiers — {mode} against {con.label}\n")

    for table in ("inventory", "products"):
        if not con.table_exists(table):
            out(f"  No `{table}` table on this database. Nothing to do.\n")
            return 0

    if args.include_zero:
        out("  --include-zero: rows already at 0 are in scope. A 0 typed by the")
        out("  owner to mean 'this tier does not apply' will be overwritten.\n")

    total = 0
    for col in TIERS:
        try:
            rows = _candidates(con, col, args.include_zero)
        except Exception as e:
            out(f"  {col}: could not query ({e}) — has the migration run on this DB?")
            continue

        if not rows:
            out(f"  {col}: nothing to seed")
            continue

        out(f"  {col}: {len(rows)} batch row(s) to seed from their product")
        for r in rows[:5]:
            label = r["batch_no"] or "(no batch)"
            out(f"      inventory#{r['inv_id']} {r['product_name']} [{label}] "
                f"-> {r['product_tier']}")
        if len(rows) > 5:
            out(f"      … and {len(rows) - 5} more")

        if args.apply:
            # ONE set-based statement, not a loop of parameterised updates.
            #
            # Two reasons. It is atomic — a partial backfill leaves batches
            # priced inconsistently with no record of where it stopped. And
            # `_dbcompat.translate` only rewrites `?` placeholders; named
            # `:value` binds are NOT translated, so a per-row update written
            # that way runs fine on SQLite and fails on Postgres — which is the
            # database this script exists to repair.
            #
            # The correlated subquery is portable to both engines and carries no
            # parameters at all, so there is nothing to bind wrongly.
            unset = (f'(i."{col}" IS NULL OR i."{col}" = 0)' if args.include_zero
                     else f'i."{col}" IS NULL')
            con.execute(
                f'UPDATE "inventory" AS i SET "{col}" = ('
                f'  SELECT p."{col}" FROM "products" p '
                f'  WHERE p.id = i.product_id AND p.business_id = i.business_id) '
                f'WHERE {unset} AND EXISTS ('
                f'  SELECT 1 FROM "products" p '
                f'  WHERE p.id = i.product_id AND p.business_id = i.business_id '
                f'    AND p."{col}" IS NOT NULL AND p."{col}" > 0)'
            )
        total += len(rows)

    if args.apply:
        con.commit()
        out(f"\n  Seeded {total} value(s).")
    else:
        out(f"\n  Would seed {total} value(s). Re-run with --apply.")
    out("  Remember: run this against BOTH databases — raw writes do not sync.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
