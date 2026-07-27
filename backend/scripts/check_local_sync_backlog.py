"""
scripts/check_local_sync_backlog.py — did the sale save, queue, and push?
=========================================================================
Read-only, LOCAL database. Answers one question in three parts:

    1. Is the sale in `invoices` at all?             (billing wrote it)
    2. Is there a `sync_queue` row for it?           (the outbox captured it)
    3. Does that row have `synced_at`, or an error?  (the worker pushed it)

    python scripts/check_local_sync_backlog.py
    python scripts/check_local_sync_backlog.py --db path\\to\\bizassist.db

WHY THIS EXISTS
---------------
A sale rung on 2026-07-27 never reached the cloud: the cloud's highest invoice
id was still 824 (`LCL-OW-0027`, written 2026-07-26). The three possible
explanations need three different fixes, and only the local database can tell
them apart.

Failing to distinguish them is how "sync is fine" gets said about a system that
has quietly stopped pushing — the M-12/M-13 shape, where a cursor advanced past
failures and the push acked rows the cloud had rejected.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dbcompat import connect, out, use_utf8_stdout  # noqa: E402


def _default_db() -> str:
    """`backend/bizassist.db` — the PARENT of this scripts/ directory.

    The first version of this file resolved to `backend/scripts/bizassist.db`
    and died with `unable to open database file`. Architecture rule 45 says a
    repair script must resolve its own database from `__file__`; it must also
    resolve to the RIGHT directory, and this repo has two files named
    `bizassist.db` — one of them an empty stub at the repo root.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "bizassist.db")


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=_default_db())
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()

    c = connect(args.db, readonly=True)
    out("=" * 74)
    out(f"LOCAL SYNC BACKLOG   {c.label}")
    out(f"engine: {c.dialect}   mode: read-only   WRITES NOTHING")
    out("=" * 74)

    out("\n-- newest invoices written locally --")
    out(f"  {'id':>7}  {'biz':>4}  {'document':<18}{'total':>10}  created")
    for r in c.execute("SELECT id, business_id, invoice_id, total_amount, "
                       "created_at FROM invoices ORDER BY id DESC LIMIT ?",
                       (args.limit,)):
        out(f"  {int(r['id']):>7}  {int(r['business_id'] or 0):>4}  "
            f"{str(r['invoice_id']):<18}{float(r['total_amount'] or 0):>10.2f}  "
            f"{str(r['created_at'])[:19]}")

    if not c.table_exists("sync_queue"):
        out("\n  sync_queue: TABLE ABSENT - nothing can be said about the outbox")
        c.close()
        return 1

    pending = c.scalar("SELECT COUNT(*) FROM sync_queue WHERE synced_at IS NULL",
                       default=0)
    errored = c.scalar("SELECT COUNT(*) FROM sync_queue "
                       "WHERE error IS NOT NULL AND error != ''", default=0)
    total = c.scalar("SELECT COUNT(*) FROM sync_queue", default=0)
    out("\n-- outbox --")
    out(f"  rows total : {total}")
    out(f"  UNSYNCED   : {pending}")
    out(f"  with error : {errored}")

    out("\n-- newest outbox rows --")
    out(f"  {'id':>6}  {'biz':>4}  {'entity':<20}{'op':<8}"
        f"{'created':<21}{'synced':<21}error")
    for r in c.execute("SELECT id, business_id, entity, operation, created_at, "
                       "synced_at, error FROM sync_queue ORDER BY id DESC "
                       "LIMIT ?", (args.limit,)):
        out(f"  {int(r['id']):>6}  {int(r['business_id'] or 0):>4}  "
            f"{str(r['entity']):<20}{str(r['operation']):<8}"
            f"{str(r['created_at'])[:19]:<21}"
            f"{str(r['synced_at'] or '-')[:19]:<21}{str(r['error'] or '')[:40]}")

    # ── The verdict, stated rather than left to the reader ──────────────────
    newest_inv = c.execute("SELECT id, invoice_id, created_at FROM invoices "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    newest_q = c.execute("SELECT created_at FROM sync_queue "
                         "ORDER BY id DESC LIMIT 1").fetchone()
    # ── M-20: the shift the newest sale was rung on ────────────────────────
    if c.table_exists("register_shifts"):
        sh = c.execute(
            "SELECT s.id, s.uid, s.status, s.start_time FROM register_shifts s "
            "JOIN invoices i ON i.shift_id = s.id "
            "WHERE i.id = (SELECT MAX(id) FROM invoices)").fetchone()
        out("\n-- the shift the newest sale belongs to (M-20) --")
        if sh is None:
            out("  the newest invoice has no shift_id")
        else:
            q = c.execute("SELECT id, created_at, synced_at, error FROM sync_queue "
                          "WHERE entity = 'register_shifts' AND entity_id = ? "
                          "ORDER BY id DESC", (sh["id"],)).fetchall()
            out(f"  shift id={sh['id']} status={sh['status']} uid={sh['uid']}")
            if not q:
                out("  NEVER QUEUED for sync. The cloud can never resolve it, so")
                out("  EVERY invoice on this shift will be deferred and lost.")
            else:
                for r in q:
                    out(f"  queued id={r['id']} created={str(r['created_at'])[:19]} "
                        f"synced={str(r['synced_at'] or '-')[:19]} "
                        f"err={str(r['error'] or '')[:40]}")
                out("  It WAS queued. If the cloud still lacks this uid, the shift")
                out("  was itself deferred or rejected on arrival - the deferral is")
                out("  recursive and the parent chain must be resolved first.")

    out("\n" + "-" * 74)
    if newest_inv is None:
        out("  No invoices at all in this database.")
    elif pending > 0:
        # WHY they are pending matters, and the first version of this verdict got
        # it wrong: it said "the sync WORKER is the problem - not running, or
        # unable to reach the cloud" for rows that were pushed perfectly well and
        # deliberately HELD by the M-20 fix. A row kept on purpose and a row
        # stuck because sync is down look identical in a count; they are opposite
        # situations and the error column already distinguishes them.
        held = c.scalar(
            "SELECT COUNT(*) FROM sync_queue WHERE synced_at IS NULL AND ("
            "error LIKE '%deferred by cloud%' OR error LIKE '%did not account%')",
            default=0)
        if held:
            out(f"  {held} row(s) are being HELD ON PURPOSE (M-20).")
            out("  They were pushed; the cloud did not store them, so the outbox")
            out("  keeps them rather than acking a write that never landed.")
            out("  THE DATA IS SAFE and will be re-sent every cycle. It cannot")
            out("  land until the blocking parent reaches the cloud - see the")
            out("  shift section above.")
            out("")
            out("  Before the M-20 fix these rows would have been stamped synced")
            out("  and the sales deleted, exactly as LCL-OW-0028 (Rs641) was.")
        if pending - held > 0:
            out(f"  {pending - held} other row(s) are QUEUED BUT NOT PUSHED -")
            out("  billing and the outbox worked, so the sync WORKER is the")
            out("  problem: not running, or unable to reach the cloud.")
        other_errs = c.execute(
            "SELECT DISTINCT error FROM sync_queue WHERE synced_at IS NULL "
            "AND error IS NOT NULL AND error != '' "
            "AND error NOT LIKE '%deferred by cloud%' "
            "AND error NOT LIKE '%did not account%'").fetchall()
        for e in other_errs[:5]:
            out(f"      other error: {str(e['error'])[:70]}")
    elif newest_q is not None and str(newest_inv["created_at"]) > str(newest_q["created_at"]):
        out(f"  The newest invoice ({newest_inv['invoice_id']}, "
            f"{str(newest_inv['created_at'])[:19]}) is NEWER than the newest")
        out("  outbox row. The sale saved but was NEVER QUEUED - the outbox")
        out("  write is missing, which is a billing-path defect, not a sync one.")
    else:
        out("  The outbox is drained and the newest invoice is represented in it.")
        out("")
        out("  BUT A DRAINED OUTBOX DOES NOT MEAN THE ROW IS IN THE CLOUD.")
        out("  `services/sync_worker.py` stamps `synced_at` on EVERY row in a")
        out("  pushed chunk, including rows the cloud REJECTED - deliberately, so")
        out("  one unappliable row cannot stall the queue behind it (M-13). A")
        out("  rejected row therefore looks exactly like a stored one here:")
        out("  synced_at set, error NULL.")
        out("")
        out("  Worse, the rejection is NOT PERSISTED. It is logged at ERROR and")
        out("  broadcast to the UI, and that is all - `sync_logs` records cloud")
        out("  outages and auth failures, never a rejected row. So the only")
        out("  surviving evidence of a lost sale is a log line that rotates away.")
        out("")
        out("  To find out what actually happened, search the LOCAL backend log")
        out("  around the synced_at time above for:")
        out("      [SYNC_WORKER] the cloud REJECTED")
        out("      [SYNC_WORKER] ... landed in the cloud but their derived state")
        out("  and confirm against the cloud with scripts/diagnose_money_findings.py")
    out("-" * 74)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
