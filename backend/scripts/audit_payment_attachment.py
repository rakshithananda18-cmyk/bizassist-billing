"""
scripts/audit_payment_attachment.py — the same receipt, on two databases
=======================================================================

Compares `invoice_payments` between the LOCAL and the CLOUD database BY UID and
reports every receipt whose parent invoice is not the same document on both
sides. READ-ONLY on both connections; it has no `--apply` and cannot acquire
one.

WHY THIS BREAKS THE ONE-DATABASE-AT-A-TIME CONVENTION, ON PURPOSE
-----------------------------------------------------------------
Every other money script here connects to exactly one target, deliberately, so
that each repair is one decision with one audit trail. That convention is right
for REPAIRS and it is why `void_duplicate_payment.py` refuses to reach across.

But it left a whole defect class unobservable. Found on 2026-08-01:

    uid e10f6d92-e55a-4b49-9fcb-b4679bdc56dd   Rs 45.00 cash, 2026-07-06
      local : invoice 457, business 8  (BA-W9J21Y)  total 45.00   -> settles it
      cloud : invoice 786, business 7  (BA-JABXGD)  total 424.00  -> overpays

One receipt, two different tenants' invoices. `audit_money_integrity.py` scored
BOTH databases clean on section A (mis-attached payments) and section D2
(cross-tenant payments), and was right to: the cloud copy carries
`business_id = 7`, matching the invoice it hangs off, so it is perfectly
self-consistent over there. The row is only wrong in comparison. A defect that
lives in the DIFFERENCE between two databases cannot be seen by any number of
audits of either one — which is the §8 mistake pattern turned into a tool.

WHAT IT REPORTS
---------------
  WRONG-TENANT   parent invoices belong to different BizIDs. Money on another
                 business's books. This is M-9 with the tenant boundary crossed.
  WRONG-INVOICE  same BizID, different invoice number. Classic M-9.
  AMOUNT-DRIFT   same parent, different `amount_paid`.
  ORPHANED       the payment's `invoice_id` resolves to no invoice row.

Matching is on `uid` throughout, and tenants are matched on BizID
(`users.public_id`). Integer `business_id` is never compared across databases —
it is meaningful only inside the database that issued it (core/identity.py), and
this measurement is the proof: business 11 is BA-T9SVHG locally and BA-E3PBH9 on
the cloud, and business 1 is a different Admin Central on each side.

USAGE
-----
    python scripts/audit_payment_attachment.py --cloud "$CLOUD_URL"
    python scripts/audit_payment_attachment.py --cloud "$CLOUD_URL" --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))

from _dbcompat import connect, out, resolve_target, use_utf8_stdout  # noqa: E402

_TOLERANCE = 0.05

_SQL = (
    "SELECT p.uid AS uid, p.amount_paid AS amount_paid, "
    "       p.business_id AS pay_biz, p.payment_mode AS payment_mode, "
    "       p.payment_date AS payment_date, "
    "       i.id AS inv_row, i.invoice_id AS inv_no, "
    "       i.business_id AS inv_biz, i.total_amount AS inv_total, "
    "       u.public_id AS inv_bizid, u.business_name AS inv_bizname "
    "FROM invoice_payments p "
    "LEFT JOIN invoices i ON i.id = p.invoice_id "
    "LEFT JOIN users u ON u.id = i.business_id "
    "WHERE p.uid IS NOT NULL"
)


def _f(v) -> float:
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _load(con) -> dict:
    rows = {}
    for r in con.execute(_SQL):
        rows[r["uid"]] = {k: r[k] for k in r.keys()}
    return rows


def _describe(side, r) -> str:
    if r["inv_row"] is None:
        return (f"    {side:<6}: ORPHAN — payment.business_id={r['pay_biz']}, "
                f"parent invoice row missing")
    return (f"    {side:<6}: invoice {r['inv_no']} (row {r['inv_row']}), "
            f"business {r['inv_biz']} {r['inv_bizid'] or '(no BizID)'} "
            f"{r['inv_bizname'] or ''}, total {_f(r['inv_total']):,.2f}")


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Compare invoice_payments across two databases by uid. "
                    "Read-only on both.")
    ap.add_argument("--local", default=None,
                    help="SQLite path or URL for side A. Defaults to "
                         "backend/bizassist.db.")
    ap.add_argument("--cloud", default=None,
                    help="SQLite path or URL for side B. Defaults to "
                         "$BIZASSIST_AUDIT_DATABASE_URL.")
    ap.add_argument("--one-sided", action="store_true",
                    help="also list receipts present on only ONE database. "
                         "That is a LIVENESS question, not an attachment one, "
                         "so it is off by default — but 'sync never carried it' "
                         "and 'sync carried it wrongly' are both real money and "
                         "the operator should be able to see either.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    local_target = args.local or os.path.join(
        os.path.dirname(_HERE), "bizassist.db")
    cloud_target = resolve_target(args.cloud)
    if os.path.abspath(str(local_target)) == os.path.abspath(str(cloud_target)):
        sys.exit("\n  Both sides resolve to the same database. There is "
                 "nothing to compare.\n  Pass --cloud explicitly.\n")

    a = connect(local_target, readonly=True)
    b = connect(cloud_target, readonly=True)
    if not args.json:
        out("=" * 78)
        out("PAYMENT ATTACHMENT ACROSS DATABASES   [READ-ONLY BOTH SIDES]")
        out(f"  local: {a.label}  ({a.dialect})")
        out(f"  cloud: {b.label}  ({b.dialect})")
        out("=" * 78)

    try:
        A, B = _load(a), _load(b)
        shared = sorted(set(A) & set(B))

        buckets = {"wrong_tenant": [], "wrong_invoice": [],
                   "amount_drift": [], "orphaned": []}
        for uid in shared:
            ra, rb = A[uid], B[uid]
            if ra["inv_row"] is None or rb["inv_row"] is None:
                buckets["orphaned"].append((uid, ra, rb))
                continue
            # Tenant identity is compared on BizID ONLY. Comparing the integer
            # here would report every correctly-synced row as a mismatch and
            # miss the real ones.
            if (ra["inv_bizid"] or "\x00a") != (rb["inv_bizid"] or "\x00b"):
                buckets["wrong_tenant"].append((uid, ra, rb))
            elif str(ra["inv_no"]) != str(rb["inv_no"]):
                buckets["wrong_invoice"].append((uid, ra, rb))
            elif abs(_f(ra["amount_paid"]) - _f(rb["amount_paid"])) > _TOLERANCE:
                buckets["amount_drift"].append((uid, ra, rb))

        if args.json:
            out(json.dumps({
                "local_payments": len(A), "cloud_payments": len(B),
                "shared_uids": len(shared),
                "findings": {k: [{"uid": u, "local": la, "cloud": cl}
                                 for u, la, cl in v]
                             for k, v in buckets.items()},
            }, indent=2, default=str))
            return 1 if any(buckets.values()) else 0

        out(f"\n  local payments with a uid : {len(A)}")
        out(f"  cloud payments with a uid : {len(B)}")
        out(f"  present on both sides     : {len(shared)}")
        out(f"  local-only                : {len(set(A) - set(B))}")
        out(f"  cloud-only                : {len(set(B) - set(A))}")

        titles = {
            "wrong_tenant": "WRONG TENANT — the same receipt is on two "
                            "different businesses' invoices",
            "wrong_invoice": "WRONG INVOICE — same business, different "
                             "invoice (M-9)",
            "amount_drift": "AMOUNT DRIFT — same parent, different amount",
            "orphaned": "ORPHANED — the parent invoice is missing on one side",
        }
        total = 0
        for key, title in titles.items():
            hits = buckets[key]
            total += len(hits)
            out(f"\n[{'FAIL' if hits else ' ok '}] {title}  ({len(hits)})")
            for uid, ra, rb in hits:
                out(f"  uid {uid}   {_f(ra['amount_paid']):,.2f} "
                    f"{ra['payment_mode'] or '-'} {ra['payment_date'] or '-'}")
                out(_describe("local", ra))
                out(_describe("cloud", rb))

        if args.one_sided:
            for label, only in (("LOCAL-ONLY", sorted(set(A) - set(B))),
                                ("CLOUD-ONLY", sorted(set(B) - set(A)))):
                src = A if label == "LOCAL-ONLY" else B
                out(f"\n[info] {label} — present here, absent on the other "
                    f"side  ({len(only)})")
                for uid in only:
                    r = src[uid]
                    out(f"  uid {uid}   {_f(r['amount_paid']):,.2f} "
                        f"{r['payment_mode'] or '-'} {r['payment_date'] or '-'}")
                    out(_describe(label.split("-")[0].lower(), r))
            out("\n  One-sided is NOT corruption by itself. It is the normal "
                "look of a row\n  that sync has not carried yet — and the "
                "normal look of one it never will.\n  Which of those it is "
                "cannot be read off this list.")

        out("\n" + "=" * 78)
        out(f"  {total} receipt(s) attached differently on the two databases")
        out("=" * 78)
        if not args.one_sided:
            out("\n  A uid present on only ONE side is NOT counted above. That "
                "is a liveness\n  question (did sync carry it?), not an "
                "attachment one, and conflating the\n  two is how a stalled "
                "pull gets read as corruption. Pass --one-sided to list them.")
        return 1 if total else 0
    finally:
        a.close()
        b.close()


if __name__ == "__main__":
    raise SystemExit(main())
