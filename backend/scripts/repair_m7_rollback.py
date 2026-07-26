"""
scripts/repair_m7_rollback.py — undo the two unsafe M-7 corrections
===================================================================
The first version of ``database/migration.py::_repair_invoice_paid_state``
rewrote ``paid_amount`` to match the payment ledger in BOTH directions. That was
wrong: it assumed the ledger is complete, in a system we had just proved was
silently dropping rows across sync. On the 26 Jul 2026 boot it changed two
invoices it should not have touched:

    C1-0002 (biz 6): Paid/2533.00  ->  Partial/104.00     invented a ₹2,429 debt
    OW-0003 (biz 6): Paid/124.00   ->  Paid/311.00        invented a ₹187 credit

The migration is fixed (it now only ever RAISES toward the ledger, and reports
the other two cases instead of writing them). This script restores those two
rows to the values they held before that boot, taken from the migration's own
log line — which is the reason a repair must always print what it changed.

USAGE
-----
    python scripts/repair_m7_rollback.py            # dry run, shows the plan
    python scripts/repair_m7_rollback.py --apply    # writes

Safe to run more than once: it only writes a row that still holds the bad value,
and refuses outright if a row already holds something else (which would mean
someone has since corrected it by hand and this script must not stomp on them).

AFTER RUNNING, these two invoices still need a human decision — see the note
printed at the end. The script restores the PRE-EXISTING state; it does not
claim that state was correct.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text                                    # noqa: E402
from database.db import engine                                 # noqa: E402


# (business_id, invoice_id, value the bad repair WROTE, value to RESTORE)
AFFECTED = [
    # number,        biz, bad_status, bad_paid,  prev_status, prev_paid
    ("C1-0002",        6, "Partial",    104.0,   "Paid",       2533.0),
    ("OW-0003",        6, "Paid",       311.0,   "Paid",        124.0),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is a dry run)")
    args = ap.parse_args()

    planned, skipped = [], []
    with engine.connect() as conn:
        for number, biz, bad_status, bad_paid, prev_status, prev_paid in AFFECTED:
            row = conn.execute(text(
                "SELECT id, status, paid_amount, total_amount FROM invoices "
                "WHERE invoice_id = :n AND business_id = :b"
            ), {"n": number, "b": biz}).fetchone()

            if row is None:
                skipped.append(f"{number} (biz {biz}): not found in this database")
                continue

            inv_id, status, paid, total = row
            paid = round(float(paid or 0.0), 2)

            if status == prev_status and paid == prev_paid:
                skipped.append(f"{number} (biz {biz}): already restored")
                continue
            if not (status == bad_status and paid == bad_paid):
                skipped.append(
                    f"{number} (biz {biz}): holds {status}/{paid}, which is neither "
                    f"the bad value ({bad_status}/{bad_paid}) nor the restored one "
                    f"({prev_status}/{prev_paid}) — someone has changed it since. "
                    f"LEFT ALONE.")
                continue

            planned.append((inv_id, number, biz, status, paid, prev_status, prev_paid, total))

        print("=" * 72)
        print("M-7 ROLLBACK" + ("  [APPLYING]" if args.apply else "  [DRY RUN]"))
        print("=" * 72)

        for _, number, biz, status, paid, prev_status, prev_paid, total in planned:
            print(f"  {number} (biz {biz}, total {total}): "
                  f"{status}/{paid}  ->  {prev_status}/{prev_paid}")
        for s in skipped:
            print(f"  SKIP  {s}")
        if not planned:
            print("  nothing to do")

        if planned and args.apply:
            for inv_id, number, biz, _, _, prev_status, prev_paid, _ in planned:
                conn.execute(text(
                    "UPDATE invoices SET status = :s, paid_amount = :p WHERE id = :i"
                ), {"s": prev_status, "p": prev_paid, "i": inv_id})
            conn.commit()
            print(f"\n  restored {len(planned)} invoice(s)")
        elif planned:
            print("\n  dry run — re-run with --apply to write")

    print()
    print("-" * 72)
    print("STILL NEEDS A HUMAN DECISION")
    print("-" * 72)
    print("""
This restores what the rows held BEFORE the bad repair. It does not assert that
those values were right — both invoices have a genuine discrepancy underneath:

  C1-0002  total 2533, marked Paid, but only ONE payment row of 104 exists.
           Either ~2,429 of receipts never synced down to this database, or the
           invoice was marked Paid without the money. Check the customer's
           account and the cloud copy before deciding.

  OW-0003  total 124, but TWO payment rows totalling 311 (187 + 124). The 124
           matches the invoice exactly; the 187 almost certainly belongs to a
           different invoice and should be re-pointed at it.

Neither is safe to resolve automatically, which is why the migration now reports
these cases instead of writing them.
""".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
