#!/usr/bin/env python
"""
migrate_clean_ids.py — move one business into a FRESH database so its ids start
from 1 again, and refuse to call it done unless the numbers match.

WHY
---
Ids in the working database are not sequential any more and never will be again.
Measured 2026-08-08 on the dev SQLite:

    users      clean 1..133, then 9999 (seed_load_test.py, explicit id),
               so the next two REAL businesses signed up as 10000 and 10001
    customers  clean 1..62, then a block starting 31,416,123 — five
               `random.randint(10_000_000, 99_000_000)` draws from a test
               fixture, after which EVERY real customer is that max + 1
               (A to Z Bazar is 67,874,276)

Nothing is corrupt: `public_id` (the BizID) is what crosses database
boundaries, not `id`. But the id space never recovers, and load-test rows sit in
the same tables as real books.

RENUMBERING IN PLACE IS NOT AN OPTION. Those integers are live foreign keys
across ~20 tables and every queued sync payload; on Postgres the sequences would
need realigning too. The supported route is to let a fresh destination allocate
every id itself — which is exactly what `_import_with_remap` does:

    "Import rows WITHOUT forcing their source ids. The destination assigns fresh
     ids; we record old→new per table and rewrite every foreign key."

WHY THIS DRIVES THE HTTP ENDPOINTS RATHER THAN THE FUNCTIONS
------------------------------------------------------------
`/api/data-transfer/export` + `/api/data-transfer/import?remap_ids=true` are the
tested path, and they carry things a hand-rolled loop would quietly get wrong:
`_upsert_users` (identity-matched by username, never id-remapped), the two-sided
B2B tables (re-resolved by BizID, skips reported), `_detect_source_owner_id`,
and the canonical `_EXPORT_ORDER`. This script orchestrates them and adds the
three things they do not do: choosing which businesses go, the journal backfill,
and a parity gate.

THE TEST BUSINESSES EXCLUDE THEMSELVES
--------------------------------------
Export is scoped to ONE business (`_resolve_owner_id_by_username`). Business 9999
and the biz-1 fixture customers are left behind by simply not being exported —
no DELETE, no `WHERE id NOT IN (…)`, nothing to get wrong.

WHAT THIS DOES NOT CARRY (verified against _EXPORT_ORDER, 2026-08-08)
---------------------------------------------------------------------
  journal_entries / journal_lines   10,066 / 30,177 rows — NOT exported.
      Trial balance, P&L and party ledgers read from these. `--backfill-journals`
      runs scripts/backfill_journals.py on the destination afterwards; that is a
      REQUIRED step, not a nicety.
  register_shifts                   not exported. Close open shifts BEFORE
      migrating — a closing cash figure is a physical count.
  table_alterations / conflict_logs 117,822 / 117 rows — audit trails, gone.
      Archive the old database file if you need them for GST or disputes.
  sync_queue / sync_inbox / sync_cursors  device-local sync state, correctly
      not carried. The new database starts with an empty outbox.

ORDER OF OPERATIONS
-------------------
  1. Fresh CLOUD first. It issues the ids that cross boundaries.
  2. Re-provision each device by PULLING from the new cloud — never migrate a
     device separately, or the same business ends up with two id spaces, which
     is the problem you are leaving behind.

SAFETY
------
* DRY RUN BY DEFAULT. `--apply` is required to write anything.
* Refuses a destination that already holds invoices for this business unless
  `--allow-nonempty`. This is a fresh-start tool; merging into a populated
  database is what the Settings sync button is for.
* Verification runs on the DESTINATION'S OWN export, not on what we think we
  sent, and compares per-table row counts plus money totals. A mismatch is a
  FAILURE, not a warning — a migration that silently drops a table is worse than
  one that refuses.
* Tokens are read from the environment, never passed as arguments, so they stay
  out of shell history and process listings.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _dbcompat import out, use_utf8_stdout  # noqa: E402

try:
    import requests
except ImportError:
    sys.exit("This script needs `requests` (pip install requests).")

TIMEOUT = 300

# Totals that must survive the move. Row counts alone would miss a table that
# arrived with the right number of rows and the wrong money in them.
MONEY_CHECKS = {
    "invoices": "total_amount",
    "invoice_payments": "amount_paid",
    "purchase_invoices": "total_amount",
}


def _tok(var: str) -> str:
    v = (os.environ.get(var) or "").strip()
    if not v:
        sys.exit(f"\n  {var} is not set. Export it rather than passing a token on "
                 f"the command line:\n    set {var}=<token>\n")
    return v


def _export(url: str, token: str) -> dict:
    r = requests.get(f"{url.rstrip('/')}/api/data-transfer/export",
                     headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
    if not r.ok:
        sys.exit(f"\n  export failed: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def _counts(payload: dict) -> dict[str, int]:
    return {t: len(rows) for t, rows in (payload.get("tables") or {}).items() if rows}


def _money(payload: dict) -> dict[str, float]:
    totals = {}
    for table, col in MONEY_CHECKS.items():
        rows = (payload.get("tables") or {}).get(table) or []
        totals[table] = round(sum(float(r.get(col) or 0) for r in rows), 2)
    return totals


def _verify(before: dict, after: dict) -> bool:
    """Compare the SOURCE export against the DESTINATION's own export.

    Deliberately not "did the import report N rows" — that is the importer
    marking its own homework. Re-exporting the destination is the only check
    that sees what actually landed.
    """
    ok = True
    cb, ca = _counts(before), _counts(after)

    out(f"\n{'TABLE':34} {'SOURCE':>8} {'DEST':>8}")
    for table in sorted(set(cb) | set(ca)):
        s, d = cb.get(table, 0), ca.get(table, 0)
        flag = "" if s == d else "   <<< MISMATCH"
        if s != d:
            ok = False
        out(f"  {table:32} {s:>8} {d:>8}{flag}")

    mb, ma = _money(before), _money(after)
    out(f"\n{'MONEY':34} {'SOURCE':>12} {'DEST':>12}")
    for table in MONEY_CHECKS:
        s, d = mb.get(table, 0.0), ma.get(table, 0.0)
        flag = "" if abs(s - d) < 0.01 else "   <<< MISMATCH"
        if abs(s - d) >= 0.01:
            ok = False
        out(f"  {table:32} {s:>12.2f} {d:>12.2f}{flag}")
    return ok


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source-url", required=True,
                    help="backend holding the business today (e.g. http://localhost:8001)")
    ap.add_argument("--dest-url", required=True,
                    help="FRESH backend to migrate into")
    ap.add_argument("--apply", action="store_true",
                    help="actually import (default is export + report only)")
    ap.add_argument("--allow-nonempty", action="store_true",
                    help="permit a destination that already has invoices for this business")
    ap.add_argument("--backfill-journals", action="store_true",
                    help="run scripts/backfill_journals.py after import (journals are NOT "
                         "carried by the export — see the module docstring). Requires "
                         "--dest-db, because that script talks to a database directly, "
                         "not to --dest-url.")
    ap.add_argument("--dest-db", default=None,
                    help="the DESTINATION's database (sqlite path or postgres URL). Only "
                         "used by --backfill-journals. It is a separate argument on "
                         "purpose: --dest-url is an HTTP backend and backfill_journals.py "
                         "cannot reach it, so without this the backfill would silently run "
                         "against whatever THIS machine's .env points at.")
    ap.add_argument("--dump", default=None,
                    help="also write the source export to this file, so the migration "
                         "is inspectable and re-runnable without re-reading the source")
    args = ap.parse_args()

    # Checked before anything is read, so the run cannot get as far as importing
    # and only then discover it has nowhere to post the journals.
    if args.backfill_journals and not args.dest_db:
        sys.exit("\n  --backfill-journals needs --dest-db.\n"
                 "  backfill_journals.py opens a DATABASE directly; it cannot reach\n"
                 "  --dest-url. Without an explicit target it would run against this\n"
                 "  machine's .env DATABASE_URL — the wrong database, silently.\n")

    src_tok, dst_tok = _tok("MIGRATE_SOURCE_TOKEN"), _tok("MIGRATE_DEST_TOKEN")
    mode = "APPLYING" if args.apply else "DRY RUN"
    out("=" * 78)
    out(f"MIGRATE TO CLEAN IDS  [{mode}]")
    out(f"  source: {args.source_url}")
    out(f"  dest  : {args.dest_url}")
    out("=" * 78)

    out("\nReading the source business…")
    before = _export(args.source_url, src_tok)
    cb = _counts(before)
    out(f"  business_id (source): {before.get('business_id')}")
    out(f"  tables with rows    : {len(cb)}   total rows: {sum(cb.values())}")

    if args.dump:
        Path(args.dump).write_text(json.dumps(before, indent=1, default=str), encoding="utf-8")
        out(f"  written to {args.dump}")

    out("\nChecking the destination is fresh…")
    dest_before = _export(args.dest_url, dst_tok)
    existing = _counts(dest_before)
    if existing.get("invoices"):
        out(f"  destination already holds {existing['invoices']} invoice(s) for this business.")
        if not args.allow_nonempty:
            out("\nREFUSING — this is a fresh-start tool. Migrating into a populated "
                "database merges rather than renumbers, which leaves you with the "
                "id space you are trying to escape. Use --allow-nonempty only if "
                "you know why.")
            return 1
    else:
        out("  empty (no invoices) ✓")

    if not args.apply:
        out(f"\nDRY RUN — nothing written. {sum(cb.values())} row(s) would be imported "
            f"with fresh destination ids.")
        out("Re-run with --apply (and --backfill-journals) when the above looks right.")
        return 0

    out("\nImporting with remap_ids=true (destination allocates every id)…")
    r = requests.post(
        f"{args.dest_url.rstrip('/')}/api/data-transfer/import?remap_ids=true",
        headers={"Authorization": f"Bearer {dst_tok}", "Content-Type": "application/json"},
        json={"tables": before.get("tables") or {}}, timeout=TIMEOUT)
    if not r.ok:
        out(f"\n  import FAILED: HTTP {r.status_code} {r.text[:400]}")
        return 1
    res = r.json()
    out(f"  imported: {res.get('total')} row(s)")
    # `b2b_skipped`, not `skipped` — the importer reports dropped two-sided rows
    # under that exact key (M-19). A connection, order or order line that did not
    # apply is a hole in the migration, so it is surfaced, not just logged.
    if res.get("b2b_skipped"):
        out(f"  ⚠ {len(res['b2b_skipped'])} B2B row(s) SKIPPED and are NOT in the "
            f"destination: {res['b2b_skipped']}")

    if args.backfill_journals:
        out("\nBackfilling journals on the destination "
            "(journal_entries/_lines are not carried by the export)…")
        script = Path(__file__).resolve().parent / "backfill_journals.py"
        p = subprocess.run([sys.executable, str(script), "--apply", "--db", args.dest_db],
                           capture_output=True, text=True, timeout=TIMEOUT)
        out((p.stdout or "")[-1500:])
        if p.returncode != 0:
            out(f"  journal backfill FAILED:\n{(p.stderr or '')[-800:]}")
            return 1
    else:
        out("\n  ⚠ journals NOT backfilled. Trial balance, P&L and party ledgers "
            "read from journal_entries, which this export does not carry. Run "
            "scripts/backfill_journals.py --apply on the destination before use.")

    out("\nVerifying against the destination's OWN export…")
    after = _export(args.dest_url, dst_tok)
    if not _verify(before, after):
        out("\nMIGRATION INCOMPLETE — the destination does not match the source. "
            "Do NOT cut over. Nothing has been deleted from the source; "
            "investigate the mismatched tables above.")
        return 1

    out("\nVERIFIED ✓  every table and every money total matches.")
    out("Ids on the destination were allocated fresh — check one: the business's "
        "lowest customer id should be small again.")
    out("\nRemaining, by hand: close/re-open register shifts, and archive the old "
        "database if you need table_alterations or conflict_logs for GST history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
