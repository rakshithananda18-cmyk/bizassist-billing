"""
scripts/quarantine_misattached_payments.py — remove receipts that belong elsewhere
==================================================================================
Closes the two M-7 anomalies printed on every boot, by removing the two receipts
that caused them. Exports them to JSON first, so the action is reversible.

THE EVIDENCE (measured 26 Jul 2026, not assumed)
------------------------------------------------
``create_sale_invoice`` stamps every initial receipt with
``note = "Initial payment for invoice <number>"``. That note is an independent
record of which invoice the money was for, so it can be checked against the
invoice the row actually points at. Two rows disagree::

    #45  ₹187  note "LCL-OW-0006"  ->  attached to OW-0003  (total ₹124)
    #53  ₹104  note "LCL-OW-0002"  ->  attached to C1-0002  (total ₹2533)

Neither has a valid home in business 6:

  · ``LCL-OW-0006`` does not exist in business 6 at all.
  · ``LCL-OW-0002`` exists (id 834) but is a DIFFERENT document that already
    carries its own ₹442 receipt (#51), and it was created on 3 Jul — four days
    AFTER payment #53 was written. So #53 cannot belong to it either.

They arrived over sync with a raw source-database ``invoice_id`` and no parent
uid (root cause M-10: the pull payload never carried uids), so they were written
against whatever local invoice happened to hold that integer.

WHAT REMOVING THEM DOES — arithmetic, verified before writing this script:

    C1-0002  total 2533, recorded 2533, ledger 104 (only #53)
             -> after: 0 payment rows, recorded 2533 == total. Anomaly gone.
    OW-0003  total 124,  recorded 124,  ledger 311 (#45 ₹187 + #49 ₹124)
             -> after: ledger 124 == recorded == total. Anomaly gone.

Both boot-time anomalies clear, and no other row is touched.

WHY REMOVE RATHER THAN RE-POINT
-------------------------------
``invoice_payments.invoice_id`` is NOT NULL, so a row cannot be detached in
place. And there is no invoice in this database to re-point them at — the
documents their notes name are absent or already settled. Guessing a target
would invent a payment against a real customer, which is the mistake this whole
review has been about.

    python scripts/quarantine_misattached_payments.py            # dry run
    python scripts/quarantine_misattached_payments.py --apply

The export is written next to the database as
``quarantined_payments_<timestamp>.json`` and contains every column, so a row can
be reinstated with a plain INSERT if the counterparty database later shows the
receipts do belong here.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text                                    # noqa: E402
from database.db import engine                                 # noqa: E402


# (payment id, business_id, amount, the number its note names)
TARGETS = [
    (45, 6, 187.0, "LCL-OW-0006"),
    (53, 6, 104.0, "LCL-OW-0002"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args()

    print("=" * 74)
    print("QUARANTINE MIS-ATTACHED RECEIPTS" + ("  [APPLYING]" if args.apply else "  [DRY RUN]"))
    print("=" * 74)

    exported, planned, skipped = [], [], []
    with engine.connect() as conn:
        for pid, biz, amount, claimed in TARGETS:
            row = conn.execute(text(
                "SELECT * FROM invoice_payments WHERE id = :i AND business_id = :b"
            ), {"i": pid, "b": biz}).mappings().first()

            if row is None:
                skipped.append(f"payment #{pid}: not present (already removed?)")
                continue

            data = dict(row)
            note = (data.get("note") or "").strip()
            amt = round(float(data.get("amount_paid") or 0.0), 2)

            # Re-verify against the CURRENT database rather than trusting the
            # constants above — the row may have been corrected by hand since.
            if amt != amount or not note.endswith(claimed):
                skipped.append(
                    f"payment #{pid}: expected ₹{amount} noting '{claimed}', found "
                    f"₹{amt} noting '{note}'. Changed since this script was "
                    f"written — LEFT ALONE.")
                continue

            inv = conn.execute(text(
                "SELECT invoice_id, total_amount FROM invoices WHERE id = :i"
            ), {"i": data["invoice_id"]}).mappings().first()
            actual = inv["invoice_id"] if inv else "<missing>"
            if actual == claimed:
                skipped.append(
                    f"payment #{pid}: now correctly attached to '{actual}' — "
                    f"nothing to quarantine.")
                continue

            print(f"  payment #{pid}  ₹{amt}")
            print(f"      note names : {claimed}")
            print(f"      attached to: {actual} (total ₹{inv['total_amount'] if inv else '?'})")
            exported.append(data)
            planned.append(pid)

        for s in skipped:
            print(f"  SKIP  {s}")

        if not planned:
            print("\n  nothing to do")
            return 0

        if not args.apply:
            print(f"\n  {len(planned)} receipt(s) would be exported and removed — "
                  f"re-run with --apply")
            return 0

        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        out = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", f"quarantined_payments_{stamp}.json"))
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(exported, fh, indent=2, default=str)
        print(f"\n  exported {len(exported)} row(s) -> {out}")

        for pid in planned:
            conn.execute(text("DELETE FROM invoice_payments WHERE id = :i"), {"i": pid})
        conn.commit()
        print(f"  removed {len(planned)} receipt(s)")

    print("""
  Restart the backend. The two M-7 anomaly lines should be GONE:

    C1-0002  no payment rows -> excluded from the check, recorded 2533 == total
    OW-0003  ledger 124 == recorded 124 == total

  If the counterparty database later shows these receipts DO belong to this
  business, reinstate them from the JSON export with the correct invoice_id.
""".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
