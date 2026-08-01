"""
scripts/void_duplicate_payment.py — remove one receipt, by uid, from one database
=================================================================================

Voids a single `invoice_payments` row identified by its **uid**, exports it to
JSON first, and re-derives the invoice's `paid_amount` / `status` from what is
left. Dry run by default.

WHY uid, AND WHY ONE DATABASE AT A TIME
---------------------------------------
`invoice_payments.id` is per-database — the same receipt is 71 locally and a
different integer on the cloud. The uid is the only identifier that names the
same row on both sides, so it is the only safe thing to key a delete on.

And this script deliberately does NOT reach across to the other database. It
connects to exactly the target you name, so the two runs are two decisions with
two dry runs and two audit trails.

⚠ THE DELETE DOES NOT PROPAGATE. READ THIS BEFORE RUNNING IT ONCE.
------------------------------------------------------------------
Deleting here does **not** delete on the other side. The repair scripts operate
over a raw DB-API connection, so SQLAlchemy's `Mapper.after_delete` never fires
and no `DELETE` is queued into `sync_queue`. There is no tombstone table for
`invoice_payments`. The other database keeps its copy, indefinitely.

That is not theoretical. It is why, on 2026-08-01, the cloud still held 31
invoices' worth of duplicate line items that had already been repaired locally —
the repair ran on one side and sync had no way to carry it.

**So: run this on BOTH targets, or the row you just voided will still be there.**

WHAT IT WAS WRITTEN FOR — LCL-OW-0037
-------------------------------------
    invoice total                                    124.00
    cloud   Bank   124.00  uid 0656a848…  30 Jul 11:43   ← the real settlement
    cloud   Cheque 124.00  uid 6326fb2a…  31 Jul 18:58   ← the duplicate
    local   Cheque 124.00  uid 6326fb2a…  31 Jul 18:58   ← the duplicate

The Bank receipt was recorded on the cloud while the pull was down (see
docs/SYNC_LIVENESS_AUDIT_2026-07-31.md §7b), never reached the desktop, and the
invoice was settled a second time there. The owner confirmed the 30 Jul bank
transfer is what actually happened.

    # 1. cloud first — leaves the cloud correct and self-consistent
    python scripts/void_duplicate_payment.py 6326fb2a-e55d-494e-9e4d-f9948aacd791 \
        --db "$CLOUD_DATABASE_URL"

    # 2. then local
    python scripts/void_duplicate_payment.py 6326fb2a-e55d-494e-9e4d-f9948aacd791

    # 3. then let the Bank receipt come DOWN through the normal apply path:
    #    POST /api/sync/parity  (Ops → Run parity check)
    #    It is withheld while the cheque is still here (124+124 > 124) and
    #    becomes importable the moment it is not.

Step 3 is deliberately not done by this script. Writing a payment row from a
repair script would be a second, untested apply path for money — which is how
M-9 (receipts on the wrong invoice) happened. `inbox.drain` uses
`_apply_pulled_row`, the same path the pull uses.

SAFETY
------
* Dry run unless `--apply`.
* `--apply` against Postgres additionally requires
  `--i-have-a-restorable-backup`; there is no `.bak` beside a cloud database.
* The row is written to JSON before it is deleted.
* Refuses if the uid matches zero rows, or more than one.
* Refuses if the post-delete state would still be over-paid — that means there
  is a second duplicate and the operator should look again rather than run this
  repeatedly until the number happens to come out right.
* The delete and the invoice update are ONE transaction, verified before commit
  and rolled back if the verification fails.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from _dbcompat import (connect, is_postgres_target, out,  # noqa: E402
                       resolve_target, use_utf8_stdout)

# The app's own rule, imported rather than restated. A repair that computes
# `status` with its own copy of the logic will disagree with the application the
# first time either changes, and the disagreement shows up as an invoice that
# reads Partial in one place and Paid in another.
from core.sync.apply_hooks import derive_paid_state  # noqa: E402

_TOLERANCE = 0.05


def _fetch_payment(con, uid):
    rows = con.execute(
        "SELECT id, business_id, invoice_id, amount_paid, payment_mode, "
        "       payment_date, note, idempotency_key, uid, created_at, updated_at "
        "FROM invoice_payments WHERE uid = ?", (uid,)
    ).fetchall()
    return rows


def _fetch_invoice(con, invoice_id):
    return con.execute(
        "SELECT id, business_id, invoice_id, total_amount, paid_amount, status "
        "FROM invoices WHERE id = ?", (invoice_id,)
    ).fetchone()


def _ledger(con, invoice_id):
    return con.execute(
        "SELECT id, uid, amount_paid, payment_mode, payment_date, note "
        "FROM invoice_payments WHERE invoice_id = ? ORDER BY id", (invoice_id,)
    ).fetchall()


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Void ONE invoice_payments row by uid and re-derive the "
                    "invoice's paid state.")
    ap.add_argument("uid", help="the payment's uid (same value on both databases)")
    ap.add_argument("--db", default=None,
                    help="SQLite file path OR a postgresql:// URL. Defaults to "
                         "$BIZASSIST_AUDIT_DATABASE_URL, then backend/bizassist.db.")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete. Without it, nothing is modified.")
    ap.add_argument("--export", default=None,
                    help="where to write the JSON backup of the voided row")
    ap.add_argument("--i-have-a-restorable-backup", action="store_true",
                    dest="backup_ack",
                    help="required with --apply against a Postgres database")
    ap.add_argument("--reason",
                    default="duplicate settlement of an already-paid invoice",
                    help="what is actually wrong with this row. Written into "
                         "the JSON export, which is the only record that "
                         "survives the delete — so say the true thing, not the "
                         "default.")
    args = ap.parse_args()

    target = resolve_target(args.db)

    # Production rail, checked on the TARGET STRING before the connection is
    # opened — so the refusal cannot be bypassed by an import error being fixed
    # and the same command re-run.
    if args.apply and is_postgres_target(target) and not args.backup_ack:
        sys.exit(
            "\n  REFUSING to --apply against a PostgreSQL database without "
            "--i-have-a-restorable-backup.\n"
            "  This deletes a payment row from a live database with no .bak "
            "beside it.\n\n"
            "  Do this first:\n"
            "    1. Take a restorable snapshot / pg_dump.\n"
            "    2. Run the DRY RUN (no --apply) and read every line.\n"
            "  Then re-run with --i-have-a-restorable-backup.\n")

    con = connect(target, readonly=not args.apply)
    mode = "APPLYING" if args.apply else "DRY RUN"
    out("=" * 78)
    out(f"VOID DUPLICATE PAYMENT  [{mode}]")
    out(f"  target: {con.label}   engine: {con.dialect}"
        + ("" if args.apply else "   mode: read-only"))
    out("=" * 78)

    try:
        rows = _fetch_payment(con, args.uid)

        if not rows:
            out(f"\n  No payment with uid {args.uid} exists here.")
            out("  Nothing to do. If you have already run this against this "
                "database, that is the expected second-run result.")
            return 0
        if len(rows) > 1:
            out(f"\n  REFUSING: {len(rows)} rows share uid {args.uid}.")
            out("  uid is supposed to be unique; this needs a human before any "
                "delete.")
            return 2

        pay = rows[0]
        inv = _fetch_invoice(con, pay["invoice_id"])
        if inv is None:
            out(f"\n  REFUSING: payment {pay['id']} points at invoice "
                f"{pay['invoice_id']}, which does not exist here.")
            return 2

        total = round(float(inv["total_amount"] or 0), 2)
        before = _ledger(con, inv["id"])
        sum_before = round(sum(float(r["amount_paid"] or 0) for r in before), 2)
        sum_after = round(sum_before - float(pay["amount_paid"] or 0), 2)
        status_after = derive_paid_state(sum_after, total)

        out(f"\n  invoice {inv['invoice_id']}  (biz {inv['business_id']}, "
            f"row id {inv['id']})")
        out(f"    total {total:.2f}   currently recorded: "
            f"{float(inv['paid_amount'] or 0):.2f} / {inv['status']}")
        out(f"\n  ledger BEFORE  ({len(before)} row(s), summing {sum_before:.2f})")
        for r in before:
            mark = "  <-- VOID" if r["uid"] == args.uid else ""
            out(f"      {float(r['amount_paid'] or 0):>10.2f}  "
                f"{str(r['payment_mode'] or ''):<10} {r['payment_date']}  "
                f"uid={r['uid']}{mark}")

        out(f"\n  ledger AFTER   ({len(before) - 1} row(s), summing "
            f"{sum_after:.2f})")
        out(f"  invoice becomes: {sum_after:.2f} / {status_after}")

        if sum_after > total + _TOLERANCE:
            out(f"\n  REFUSING: even after voiding this row the ledger sums to "
                f"{sum_after:.2f} against a total of {total:.2f}.")
            out("  There is more than one duplicate here. Look at the ledger "
                "above and decide which rows are real before deleting any of "
                "them — running this until the number comes out right is how "
                "a real receipt gets destroyed.")
            return 2

        if sum_after < -_TOLERANCE:
            out("\n  REFUSING: the ledger would go negative.")
            return 2

        # Default to the CURRENT DIRECTORY, not next to the script. A backup
        # written into `backend/scripts/` lands inside the repo and is one
        # `git add -A` away from a customer's payment history being committed.
        export_path = args.export or os.path.abspath(
            f"voided_payment_{args.uid[:8]}_"
            f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json")

        if not args.apply:
            out("\n  DRY RUN — nothing was changed.")
            out(f"  Re-run with --apply to void it. The row would be exported "
                f"to:\n    {export_path}")
            out("\n  REMEMBER: this affects ONE database. Run it against the "
                "other target too, or the row stays there — raw deletes are "
                "never queued for sync.")
            return 0

        # ── write ────────────────────────────────────────────────────────────
        payload = {
            "voided_at":  datetime.now(timezone.utc).isoformat(),
            "target":     con.label,
            # NOT hardcoded any more. The export is the only surviving record of
            # a row that no longer exists, so a wrong reason in it is a wrong
            # answer preserved forever. On 2026-08-01 this script was about to
            # be pointed at LCL-OW-0003, where the row is NOT a duplicate — it
            # is one receipt attached to another tenant's invoice
            # (audit_payment_attachment.py, WRONG TENANT). Same delete, entirely
            # different fact.
            "reason":     args.reason,
            "invoice":    {k: inv[k] for k in inv.keys()},
            "payment":    {k: pay[k] for k in pay.keys()},
            "ledger_before": [{k: r[k] for k in r.keys()} for r in before],
            "restore_sql": (
                "INSERT INTO invoice_payments (business_id, invoice_id, "
                "amount_paid, payment_mode, payment_date, note, "
                "idempotency_key, uid, created_at, updated_at) VALUES (...)"
            ),
        }
        with open(export_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        out(f"\n  exported the row to {export_path}")

        now = datetime.now(timezone.utc)
        con.execute("DELETE FROM invoice_payments WHERE uid = ?", (args.uid,))
        con.execute(
            "UPDATE invoices SET paid_amount = ?, status = ?, updated_at = ? "
            "WHERE id = ?", (sum_after, status_after, now, inv["id"]))

        # Verify INSIDE the transaction. A repair that checks its work after
        # committing has already done the damage by the time it disagrees.
        check_rows = _ledger(con, inv["id"])
        check_sum = round(sum(float(r["amount_paid"] or 0) for r in check_rows), 2)
        check_inv = _fetch_invoice(con, inv["id"])
        ok = (
            abs(check_sum - sum_after) < 0.005
            and abs(float(check_inv["paid_amount"] or 0) - sum_after) < 0.005
            and check_inv["status"] == status_after
            and not any(r["uid"] == args.uid for r in check_rows)
        )
        if not ok:
            con.rollback()
            out("\n  ROLLED BACK — post-delete verification failed.")
            out(f"    ledger sums to {check_sum:.2f}, expected {sum_after:.2f}")
            out(f"    invoice reads {check_inv['paid_amount']} / "
                f"{check_inv['status']}, expected {sum_after:.2f} / "
                f"{status_after}")
            return 2

        con.commit()
        out(f"\n  VOIDED payment uid={args.uid} ({float(pay['amount_paid'] or 0):.2f} "
            f"{pay['payment_mode']}).")
        out(f"  invoice {inv['invoice_id']} is now {sum_after:.2f} / {status_after}.")
        out("\n  NEXT:")
        out("    · run this against the OTHER database too — the delete is not "
            "queued for sync and the row is still there.")
        out("    · then trigger a parity run (Ops → Run parity check) so any "
            "cloud-only receipt that now FITS is handed to the inbox and "
            "applied through the normal path.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
