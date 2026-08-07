#!/usr/bin/env python
"""
rewind_pull_cursor.py — un-stick sync-inbox rows the cloud will never re-offer.

WHY
---
A pulled row that cannot apply is parked in `sync_inbox` and retried on a
backoff. Two mechanisms then conspire to make some rows permanently stuck:

  1. The pull cursor advances even when rows fail (services/sync_worker.py).
     The cloud therefore never offers those rows again, and every retry replays
     the payload STORED IN THE INBOX. A sender-side payload fix — the whole
     point of deploying one — cannot reach a row that is already held.

  2. `due_rows` only returns rows with `attempts < MAX_AUTO_ATTEMPTS` (7).
     Once a row has burned its seven attempts it is never retried again by any
     drain, whatever the cursor says. It waits for a human. That is deliberate
     (core/sync/inbox.py) — but it means the cursor rewind ALONE is a no-op for
     exactly the rows that most need it.

So the repair is BOTH halves, and neither works without the other:

  * rewind the cursor  → the cloud re-offers, and `_park` refreshes the stored
                         payload with the current sender format
                         (core/sync/inbox.py:174)
  * reset `attempts`   → the refreshed row becomes eligible for a drain again

MEASURED CASE (2026-08-07, local SQLite, business 126)
------------------------------------------------------
20 rows held since 2026-08-03 14:50, all at attempts=7. The two `b2b_orders`
rows carry the party links as BARE integers:

    seller_business_id = 7      buyer_business_id = 114

which are the CLOUD's ids — meaningless in a database where that business is
126. That is the spine violation fixed in 740b11e, which now emits
`<col>_bizid` + `<col>_bizname` instead. The fix is deployed, and it still could
not rescue these rows, because a held row never re-reads the sender.
Downstream: 12 `b2b_order_line_items` deferred behind the missing parent, and
B2B-ORD-20260805-0001 rendering with no items.

⚠ THIS CHANGE DOES NOT PROPAGATE
--------------------------------
Like every script here it writes over a raw DB-API connection, so no mapper
event fires and nothing is queued. `sync_inbox` / `sync_cursors` are per-device
sync STATE, not books — they are meant to differ between machines. Run it on
the device whose inbox is stuck.

SAFETY
------
* DRY RUN BY DEFAULT. `--apply` is required to write anything.
* `--apply` against Postgres additionally requires
  `--i-have-a-restorable-backup`.
* Touches exactly three columns — `sync_inbox.attempts`,
  `sync_inbox.next_attempt_at`, and `sync_cursors.cursor_value` — and only for
  the named business. Never deletes an inbox row, never edits a payload, never
  touches a books table.
* Re-pulling is safe to repeat: apply is insert-missing-only, so a row that
  already landed is skipped rather than duplicated.
* Refuses to run if the business has no stuck rows, so it cannot be used to
  blindly rewind a healthy cursor and drag the whole tenant back through a pull.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _dbcompat import (  # noqa: E402
    connect, is_postgres_target, out, resolve_target, use_utf8_stdout,
)

MAX_AUTO_ATTEMPTS = 7          # mirrors core/sync/inbox.MAX_AUTO_ATTEMPTS

# How far before the oldest stuck row to place the cursor. The cloud offers
# rows STRICTLY AFTER the cursor, so landing exactly on the row's timestamp
# would skip the very row we are trying to recover.
_MARGIN_SECONDS = 60


def _iso_minus(ts: str, seconds: int) -> str:
    """`ts` minus `seconds`, as an ISO-8601 UTC string."""
    from datetime import datetime, timedelta, timezone
    raw = str(ts).replace("Z", "+00:00").replace(" ", "T")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        dt = datetime.fromisoformat(raw.split(".")[0])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - timedelta(seconds=seconds)).isoformat()


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--business", type=int, required=True,
                    help="business_id whose inbox is stuck (LOCAL id, in this database)")
    ap.add_argument("--db", default=None,
                    help="SQLite file path OR a postgresql:// URL. Defaults to "
                         "$BIZASSIST_AUDIT_DATABASE_URL, then backend/bizassist.db.")
    ap.add_argument("--before", default=None,
                    help="cursor value to write (ISO-8601). Default: 60s before the "
                         "oldest stuck row, which is what re-offers it.")
    ap.add_argument("--apply", action="store_true",
                    help="actually write the change (default is a dry run)")
    ap.add_argument("--i-have-a-restorable-backup", action="store_true",
                    dest="backup_ack",
                    help="required with --apply against a Postgres database")
    args = ap.parse_args()

    target = resolve_target(args.db)

    if args.apply and is_postgres_target(target) and not args.backup_ack:
        sys.exit(
            "\n  REFUSING to --apply against a PostgreSQL database without "
            "--i-have-a-restorable-backup.\n"
            "  Rewinding a cursor replays a window of the change feed.\n\n"
            "  Do this first:\n"
            "    1. Take a restorable snapshot / pg_dump.\n"
            "    2. Run the DRY RUN (no --apply) and read every line.\n"
            "  Then re-run with --i-have-a-restorable-backup.\n")

    con = connect(target, readonly=not args.apply)
    bid = args.business
    mode = "APPLYING" if args.apply else "DRY RUN"
    out("=" * 78)
    out(f"REWIND PULL CURSOR  [{mode}]")
    out(f"  target: {con.label}   engine: {con.dialect}"
        + ("" if args.apply else "   mode: read-only"))
    out(f"  business_id: {bid}")
    out("=" * 78)

    try:
        stuck = con.execute(
            "SELECT id, entity, uid, reason, error, attempts, created_at "
            "FROM sync_inbox "
            "WHERE business_id = ? AND applied_at IS NULL AND attempts >= ? "
            "ORDER BY created_at ASC, id ASC", (bid, MAX_AUTO_ATTEMPTS)).fetchall()

        pending = con.scalar(
            "SELECT COUNT(*) FROM sync_inbox "
            "WHERE business_id = ? AND applied_at IS NULL", (bid,), default=0)

        out(f"\nUn-applied inbox rows      : {pending}")
        out(f"Past the auto ceiling ({MAX_AUTO_ATTEMPTS})  : {len(stuck)}   "
            "<- never retried again without this")

        if not stuck:
            out("\nNothing to do — no row for this business is past the retry "
                "ceiling.\n(A rewind would only replay a healthy feed. Refusing.)")
            return 0

        by_entity: dict[str, int] = {}
        for r in stuck:
            by_entity[r["entity"]] = by_entity.get(r["entity"], 0) + 1
        out("\nStuck by entity:")
        for e, n in sorted(by_entity.items(), key=lambda kv: -kv[1]):
            out(f"   {e:28} {n}")

        oldest = stuck[0]["created_at"]
        out(f"\nOldest stuck row: id={stuck[0]['id']} entity={stuck[0]['entity']} "
            f"created_at={oldest}")
        out(f"   reason={stuck[0]['reason']}  error={stuck[0]['error']}")

        cursors = con.execute(
            "SELECT id, entity, cursor_value FROM sync_cursors WHERE business_id = ?",
            (bid,)).fetchall()
        if not cursors:
            out("\n  No sync_cursors row for this business — nothing to rewind. "
                "The rows would need the cloud to re-offer them by some other "
                "means; stopping rather than guessing.")
            return 1

        new_cursor = args.before or _iso_minus(oldest, _MARGIN_SECONDS)
        out("\nCursors:")
        for c in cursors:
            out(f"   entity={c['entity']!r}  {c['cursor_value']}  ->  {new_cursor}")

        out("\nWILL DO:")
        out(f"   1. sync_cursors.cursor_value := {new_cursor}   ({len(cursors)} row(s))")
        out(f"   2. sync_inbox.attempts := 0, next_attempt_at := NULL   "
            f"({len(stuck)} row(s))")
        out("   Payloads are NOT edited here — the re-offer refreshes them "
            "(core/sync/inbox.py:174).")

        if not args.apply:
            out("\nDRY RUN — nothing written. Re-run with --apply.")
            return 0

        con.execute(
            "UPDATE sync_cursors SET cursor_value = ? WHERE business_id = ?",
            (new_cursor, bid))
        con.execute(
            "UPDATE sync_inbox SET attempts = 0, next_attempt_at = NULL "
            "WHERE business_id = ? AND applied_at IS NULL AND attempts >= ?",
            (bid, MAX_AUTO_ATTEMPTS))
        con.commit()

        out(f"\nAPPLIED. {len(stuck)} row(s) are eligible again and the cursor is "
            f"back to {new_cursor}.")
        out("The next pull re-offers them with the CURRENT sender payload format; "
            "watch the inbox drain to confirm.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
