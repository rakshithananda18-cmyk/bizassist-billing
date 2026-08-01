#!/usr/bin/env python
"""
clear_staff_bizids.py — take back the BizIDs that were handed to staff accounts.

WHY
---
A BizID (`users.public_id`) is the TENANT identifier. It is what
`_resolve_business_id_by_username` resolves against, what the LAN discovery
registry keys on, and what every per-business sweep counts.

`_backfill_biz_ids` used to select on `public_id IS NULL` alone, with no
`parent_business_id IS NULL`, so every cashier was handed one and became a
phantom business. Measured on the CLOUD database 2026-07-31: all 32 staff rows
carried a BizID, against 9 real owners — which is why the nightly job logged

    [SCHED] Running books integrity audit for 40 business(es)...

The backfill no longer does this. This script cleans up what it already did.

WHY IT NOW TAKES --db
---------------------
The previous version imported `database.db.SessionLocal`, so it could only ever
open whatever the APPLICATION was pointed at. That made it structurally unable
to reach the one database the defect was measured on. The 32 offending rows are
on **Postgres**; the local SQLite has 0 (verified 2026-08-01, 9 owners /
0 staff holding a BizID), so every run of the old script correctly reported
"nothing to do" about a database that was not the one with the problem.

That is the §8 mistake pattern: asserting something about one side of a
two-database system from evidence gathered on the other. The fix is to let the
operator name the side.

⚠ THIS CHANGE DOES NOT PROPAGATE
--------------------------------
Like every script in this directory, it writes over a raw DB-API connection, so
SQLAlchemy's mapper events never fire and nothing is queued into `sync_queue`.
`users` is not in `MODEL_MAP` either, so even a normal ORM write would not sync.
**Run it on each database you want changed.**

SAFETY
------
* DRY RUN BY DEFAULT. `--apply` is required to write anything.
* `--apply` against Postgres additionally requires
  `--i-have-a-restorable-backup`; there is no `.bak` beside a cloud database.
* Touches exactly ONE column, `public_id`, on rows where
  `parent_business_id IS NOT NULL`. Never deletes a row, never touches an owner,
  never touches a password, role or counter prefix.
* Refuses to clear a BizID that is ALSO recorded in `deleted_businesses` — the
  same string being live and retired at once is a migration problem, not a
  cleanup one, and papering over it is worse than leaving the row alone.
* Reports, without refusing, any BizID that appears in the append-only audit
  trails (`table_alterations`, `telemetry_events`). See the long note by
  `_REFUSE_PROBES` for why the probe list this script shipped with checked four
  columns that have never existed on either database.
* Each reference probe is rolled back on failure. On Postgres a failed statement
  aborts the whole transaction (rule 58), so the previous bare `except: continue`
  would have left every SUBSEQUENT probe failing too — reporting "nothing is
  referenced" from a dead transaction, and then clearing rows that were.
* Verified before commit: re-counts the remaining staff BizIDs and rolls back if
  the number is not the protected count.
* Prints every row it would change, before changing it.

USAGE
-----
    python scripts/clear_staff_bizids.py                       # dry run, local
    python scripts/clear_staff_bizids.py --db "$CLOUD_URL"     # dry run, cloud
    python scripts/clear_staff_bizids.py --db "$CLOUD_URL" --apply \
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

# ─────────────────────────────────────────────────────────────────────────────
# WHERE A BizID ACTUALLY APPEARS
# ─────────────────────────────────────────────────────────────────────────────
# THE PROBE LIST THAT USED TO BE HERE WAS FICTION. It read
#
#     b2b_connections.seller_public_id / .buyer_public_id
#     b2b_orders.seller_public_id      / .buyer_public_id
#
# and **none of those four columns has ever existed**, on either database. The
# real columns are `seller_business_id` / `buyer_business_id`, and they hold
# INTEGERS, not BizIDs. Verified 2026-08-01 on both sides: the local SQLite
# schema has no such column, and the first Postgres run reported
# `column "seller_public_id" does not exist` four times.
#
# So the refusal this script advertises — "refuses to clear a BizID that is
# REFERENCED anywhere it can check" — was never once operative. The old code
# swallowed all four failures with a bare `except: continue`, returned an empty
# set, and printed a clean plan. An empty result from a probe that cannot run
# reads exactly like an empty result from a probe that ran (rule 33), and that
# is what it did, silently, for the whole life of the file.
#
# Enumerated properly, a BizID string is stored in exactly four places:
#
#   users.public_id              the live tenant identifier (what we clear)
#   deleted_businesses.public_id a RETIRED BizID
#   table_alterations.public_id  append-only audit trail
#   telemetry_events.bizid       append-only audit trail
#
# Those last three are not pointers in the FK sense — each row holds its own
# copy of the string, so clearing `users.public_id` dangles nothing. They divide
# by what the operator should do about them, which is why there are two lists.

# A collision here is a MIGRATION problem: the same string is simultaneously
# live on a staff row and recorded as retired. Refuse and let a human look.
_REFUSE_PROBES = [
    ("deleted_businesses", "public_id"),
]

# Append-only audit trails. Clearing does not break them, but it does sever the
# join back to a live user, so the operator is told how much attribution they
# are giving up rather than being stopped.
_ATTRIBUTION_PROBES = [
    ("table_alterations", "public_id"),
    ("telemetry_events", "bizid"),
]


def _probe(con, table, col, bizids, unreadable, probed):
    """-> {bizid: row count} for the given candidates, or {} if unaskable.

    Scoped by an IN list rather than scanning the table: `telemetry_events` is
    the largest table on the cloud and there is no reason to read a BizID out of
    it that we were never going to clear anyway.

    `probed` accumulates "N BizIDs on file, M matched" per table, and it is not
    decoration. THE WHOLE DEFECT THIS FUNCTION REPLACED WAS A CLEAN RESULT THAT
    NOBODY COULD FALSIFY. A probe that matches nothing because the table is
    empty and a probe that matches nothing because there is genuinely nothing to
    find print the identical line unless the denominator is shown — so it is
    shown, and the operator can tell a real all-clear from a vacuous one.
    """
    if not con.table_exists(table):
        unreadable.append(f"{table}.{col} (no such table here)")
        return {}
    placeholders = ",".join("?" for _ in bizids)
    try:
        rows = con.execute(
            f'SELECT "{col}", COUNT(*) FROM "{table}" '
            f'WHERE "{col}" IN ({placeholders}) GROUP BY "{col}"',
            tuple(bizids)).fetchall()
        found = {r[0]: r[1] for r in rows if r[0]}
        on_file = con.scalar(
            f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" IS NOT NULL',
            default=0)
        probed.append(f"{table}.{col}: {on_file} BizID row(s) on file, "
                      f"{len(found)} of the {len(bizids)} candidate(s) matched")
        return found
    except Exception as e:
        # Rule 58. Without this rollback the aborted transaction poisons every
        # later probe on Postgres — which is how the four fictional probes above
        # managed to fail as a set rather than one at a time.
        con.rollback()
        unreadable.append(f"{table}.{col} ({str(e).strip().splitlines()[0]})")
        return {}


def _referenced_bizids(con, bizids) -> tuple[set, dict, list, list]:
    """-> (refuse_set, {bizid: {table: count}}, probes that ran, probes that failed)

    The last two are separate because of rule 33: a probe that FAILED is not a
    probe that found nothing, and the operator has to be able to tell the
    difference before authorising a write. That distinction is the entire reason
    the fiction above was visible at all.
    """
    unreadable: list = []
    probed: list = []
    refuse: set = set()
    attribution: dict = {}
    if not bizids:
        return refuse, attribution, probed, unreadable
    for table, col in _REFUSE_PROBES:
        refuse.update(_probe(con, table, col, bizids, unreadable, probed))
    for table, col in _ATTRIBUTION_PROBES:
        for bizid, n in _probe(con, table, col, bizids,
                               unreadable, probed).items():
            attribution.setdefault(bizid, {})[table] = n
    return refuse, attribution, probed, unreadable


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
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

    # Checked on the TARGET STRING, before the connection is opened.
    if args.apply and is_postgres_target(target) and not args.backup_ack:
        sys.exit(
            "\n  REFUSING to --apply against a PostgreSQL database without "
            "--i-have-a-restorable-backup.\n"
            "  This clears the tenant identifier on live user rows with no "
            ".bak beside them.\n\n"
            "  Do this first:\n"
            "    1. Take a restorable snapshot / pg_dump.\n"
            "    2. Run the DRY RUN (no --apply) and read every line.\n"
            "  Then re-run with --i-have-a-restorable-backup.\n")

    con = connect(target, readonly=not args.apply)
    mode = "APPLYING" if args.apply else "DRY RUN"
    out("=" * 78)
    out(f"CLEAR STAFF BIZIDS  [{mode}]")
    out(f"  target: {con.label}   engine: {con.dialect}"
        + ("" if args.apply else "   mode: read-only"))
    out("=" * 78)

    try:
        staff = con.execute(
            "SELECT id, username, public_id, parent_business_id FROM users "
            "WHERE public_id IS NOT NULL AND parent_business_id IS NOT NULL "
            "ORDER BY parent_business_id, id").fetchall()
        owners = con.scalar(
            "SELECT COUNT(*) FROM users WHERE parent_business_id IS NULL",
            default=0)

        out(f"\nReal business owners : {owners}")
        out(f"Staff holding a BizID: {len(staff)}")
        out(f"Per-business sweeps currently iterate: {owners + len(staff)}\n")

        if not staff:
            out("Nothing to do — no staff account holds a BizID here.")
            return 0

        candidates = [s["public_id"] for s in staff]
        refuse, attribution, probed, unreadable = _referenced_bizids(
            con, candidates)
        if probed:
            out("PROBED:")
            for p in probed:
                out(f"  {p}")
            out("")
        if unreadable:
            out("COULD NOT PROBE (treated as unknown, NOT as empty — rule 33):")
            for u in unreadable:
                out(f"  {u}")
            out("  Re-read the plan below knowing this check did not run.\n")

        clearable, protected = [], []
        for s in staff:
            (protected if s["public_id"] in refuse else clearable).append(s)

        out("WOULD CLEAR:")
        for s in clearable:
            marks = attribution.get(s["public_id"]) or {}
            trail = ("   [audit trail: "
                     + ", ".join(f"{t}={n}" for t, n in sorted(marks.items()))
                     + "]") if marks else ""
            out(f"  id={s['id']:<6} {str(s['username']):<28} "
                f"parent={s['parent_business_id']:<6} "
                f"public_id={s['public_id']}{trail}")

        if attribution:
            out("\n  NOTE: rows marked [audit trail] have history recorded "
                "against that BizID.\n"
                "  Those rows keep their own copy of the string, so nothing "
                "dangles — but once\n"
                "  the user row is cleared the trail can no longer be joined "
                "back to a live user.")

        if protected:
            out("\nLEFT ALONE — this BizID is ALSO recorded as retired in "
                "deleted_businesses.\n"
                "That is a live/retired identity collision: a migration "
                "problem, not a cleanup one.")
            for s in protected:
                out(f"  id={s['id']:<6} {str(s['username']):<28} "
                    f"public_id={s['public_id']}")

        if not args.apply:
            out(f"\nDRY RUN. {len(clearable)} row(s) would change. "
                f"Re-run with --apply to perform it.")
            return 0

        if not clearable:
            out("\nNothing clearable. No write attempted.")
            return 0

        for s in clearable:
            con.execute("UPDATE users SET public_id = NULL WHERE id = ?",
                        (s["id"],))

        # Verify BEFORE commit. If the count is not what the plan said, the
        # transaction goes back rather than leaving a half-applied cleanup.
        remaining = con.scalar(
            "SELECT COUNT(*) FROM users "
            "WHERE public_id IS NOT NULL AND parent_business_id IS NOT NULL",
            default=-1)
        if remaining != len(protected):
            con.rollback()
            out(f"\n  VERIFICATION FAILED: expected {len(protected)} staff "
                f"BizID(s) to remain, found {remaining}.")
            out("  Rolled back. Nothing was changed.")
            return 2

        con.commit()
        out(f"\nDone. Cleared {len(clearable)} staff BizID(s).")
        out(f"Per-business sweeps will now iterate {owners} owner(s) "
            f"+ {len(protected)} protected staff row(s).")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
