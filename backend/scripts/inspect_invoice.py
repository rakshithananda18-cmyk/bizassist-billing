"""
scripts/inspect_invoice.py — one invoice, from whichever database you point at
==============================================================================

Prints an invoice header, its full payment ledger, its line items, and both
money invariants — over `_dbcompat`, so it runs against SQLite or Postgres.
READ-ONLY. It has no `--apply` and cannot acquire one.

WHY THIS EXISTS ALONGSIDE inspect_cloud_invoice.py
--------------------------------------------------
They are not the same tool and the difference has already cost a run.

`inspect_cloud_invoice.py` imports `SessionLocal`. It resolves the business and
the local invoice from the **local SQLite**, then fetches the cloud through
`/api/sync/pull` using that business's stored sync token. So:

  * its `--business-id` is a LOCAL id, even though the output is about the cloud;
  * it ignores `BIZASSIST_AUDIT_DATABASE_URL` entirely;
  * it needs `cloud_sync_tokens.json` to hold a token for that business, which
    is written at OWNER LOGIN — so it simply cannot report on a tenant whose
    owner has never signed in on this machine. That is where it stopped on
    2026-08-01: `error: no cloud token for this business`.

That design is right for what it does — it diffs local against cloud through
the same endpoint the sync worker uses, which is the only way to see what the
PULL would see. But it is the wrong instrument for "what does the cloud row
actually say", and it cannot answer that question at all for a business the
operator does not own.

This script takes the other road: one connection, to exactly the database named
by `--db` / `$BIZASSIST_AUDIT_DATABASE_URL`, and no token, no HTTP, no local
fallback. Every id and every BizID it prints came out of THAT database.

THE ID TRAP THIS IS SHAPED BY
-----------------------------
`business_id` is meaningful only inside the database that issued it
(core/identity.py). Varshini is local 7 and cloud 42; the cloud's business 7 is
somebody else. So when `--business-id` is omitted and the invoice number is
ambiguous, the disambiguation list is printed FROM THE TARGET DATABASE with the
BizID beside each row — because the BizID is the only column in that list that
means the same thing on both sides, and picking by integer alone is how you end
up reading the wrong tenant with total confidence.

USAGE
-----
    python scripts/inspect_invoice.py LCL-OW-0003 --business-id 7 \\
        --db "$CLOUD_URL"
    python scripts/inspect_invoice.py LCL-OW-0037            # local SQLite
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


def _f(v) -> float:
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _money(v) -> str:
    return f"{_f(v):>12,.2f}"


def _candidates(con, number):
    return con.execute(
        "SELECT i.id, i.business_id, i.total_amount, i.paid_amount, i.status, "
        "       u.public_id, u.business_name "
        "FROM invoices i LEFT JOIN users u ON u.id = i.business_id "
        "WHERE i.invoice_id = ? ORDER BY i.business_id, i.id", (number,)
    ).fetchall()


def _report(con, row, as_json):
    inv_id = row["id"]
    total = _f(row["total_amount"])
    disc = _f(row["cash_discount"])
    roff = _f(row["round_off"])

    # `business_id` is selected on the PAYMENT, not inherited from the invoice.
    # A receipt whose own business_id disagrees with its invoice's is M-9 with
    # the tenant boundary crossed, and printing only the invoice's side hides
    # exactly that. Cost one run to learn on 2026-08-01.
    ledger = con.execute(
        "SELECT id, uid, business_id, amount_paid, payment_mode, payment_date, "
        "       note, idempotency_key, created_at, updated_at "
        "FROM invoice_payments WHERE invoice_id = ? ORDER BY id", (inv_id,)
    ).fetchall()
    lines = con.execute(
        "SELECT id, product_name, quantity, line_total, created_at "
        "FROM invoice_line_items WHERE invoice_id = ? ORDER BY id", (inv_id,)
    ).fetchall()

    paid_rows = sum(_f(p["amount_paid"]) for p in ledger)
    line_sum = sum(_f(li["line_total"]) for li in lines)
    line_target = total + disc - roff

    if as_json:
        out(json.dumps({
            "engine": con.dialect,
            "invoice": {k: row[k] for k in row.keys()},
            "ledger": [{k: p[k] for k in p.keys()} for p in ledger],
            "line_items": [{k: li[k] for k in li.keys()} for li in lines],
            "derived": {
                "payment_rows_sum": round(paid_rows, 2),
                "line_items_sum": round(line_sum, 2),
                "line_items_target": round(line_target, 2),
            },
        }, indent=2, default=str))
        return

    out(f"\n  invoice {row['invoice_id']}   business_id={row['business_id']}"
        f"   row id={inv_id}")
    out(f"    total_amount   {_money(total)}")
    out(f"    paid_amount    {_money(row['paid_amount'])}   status="
        f"{row['status']}")
    out(f"    cash_discount  {_money(disc)}   round_off {_money(roff)}")

    out(f"\n  PAYMENT LEDGER  ({len(ledger)} row(s), summing {paid_rows:,.2f})")
    if not ledger:
        out("    (none)")
    for p in ledger:
        cross = ("   <-- BUSINESS MISMATCH vs the invoice"
                 if p["business_id"] != row["business_id"] else "")
        out(f"    {_money(p['amount_paid'])}  {str(p['payment_mode'] or '-'):<10} "
            f"{str(p['payment_date'] or '-'):<12} uid={p['uid']}{cross}")
        out(f"                  biz={p['business_id']}  "
            f"idem={p['idempotency_key']}  created={p['created_at']}")

    out(f"\n  LINE ITEMS  ({len(lines)} row(s), summing {line_sum:,.2f})")
    for li in lines:
        out(f"    li={str(li['id']):<6} {str(li['product_name'] or '-'):<28} "
            f"qty={str(li['quantity'] or '-'):<8}{_money(li['line_total'])}  "
            f"created {li['created_at']}")

    # ── the two invariants, stated the way db_invariants states them ────────
    out("\n  INVARIANTS  (tolerance 0.05)")
    d1 = line_sum - line_target
    ok1 = abs(d1) <= _TOLERANCE
    out(f"    SUM(line_total) == total + cash_discount - round_off"
        f"   {'OK' if ok1 else 'FAIL'}")
    out(f"      {line_sum:,.2f} vs {line_target:,.2f}   delta {d1:+,.2f}")

    ok2 = paid_rows <= total + _TOLERANCE
    out(f"    SUM(amount_paid) <= total_amount"
        f"                       {'OK' if ok2 else 'FAIL'}")
    out(f"      {paid_rows:,.2f} vs {total:,.2f}   "
        f"over by {max(0.0, paid_rows - total):,.2f}")

    hdr = _f(row["paid_amount"])
    ok3 = abs(hdr - paid_rows) <= _TOLERANCE
    out(f"    invoices.paid_amount == SUM(amount_paid)"
        f"                {'OK' if ok3 else 'FAIL'}")
    out(f"      header {hdr:,.2f} vs ledger {paid_rows:,.2f}   "
        f"delta {hdr - paid_rows:+,.2f}")


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Print one invoice, its ledger and its invariants, from "
                    "the database named by --db. Read-only.")
    ap.add_argument("invoice_number", nargs="?", default=None,
                    help="e.g. LCL-OW-0003")
    ap.add_argument("--businesses", action="store_true",
                    help="list every business in the TARGET database with its "
                         "BizID, and exit. Answers 'does this tenant exist "
                         "over here at all?', which an invoice lookup cannot.")
    ap.add_argument("--business-id", type=int, default=None,
                    help="business_id AS NUMBERED IN THE TARGET DATABASE. "
                         "Omit to list the candidates.")
    ap.add_argument("--db", default=None,
                    help="SQLite file path OR a postgresql:// URL. Defaults to "
                         "$BIZASSIST_AUDIT_DATABASE_URL, then backend/bizassist.db.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if not args.businesses and not args.invoice_number:
        ap.error("give an invoice number, or --businesses")

    con = connect(resolve_target(args.db), readonly=True)
    if not args.json:
        out("=" * 78)
        out("INSPECT INVOICE  " + (args.invoice_number or "(business list)"))
        out(f"  target: {con.label}   engine: {con.dialect}   mode: read-only")
        out("=" * 78)

    try:
        if args.businesses:
            rows = con.execute(
                "SELECT id, public_id, business_name, username FROM users "
                "WHERE parent_business_id IS NULL ORDER BY id").fetchall()
            out(f"\n  {len(rows)} business owner(s) in THIS database:\n")
            for r in rows:
                out(f"    business_id {str(r['id']):<5} "
                    f"{str(r['public_id'] or '(no BizID)'):<12} "
                    f"{str(r['business_name'] or '-'):<28} "
                    f"{str(r['username'] or '-')}")
            out("\n  Match tenants across databases on the BizID. The integer "
                "is local to\n  whichever database issued it and means nothing "
                "on the other one.")
            return 0

        rows = _candidates(con, args.invoice_number)
        if not rows:
            out(f"\n  No invoice numbered {args.invoice_number} exists in this "
                f"database.")
            out("  That is an answer about THIS target only — the other "
                "database is not consulted.")
            return 1

        if args.business_id is not None:
            rows = [r for r in rows if r["business_id"] == args.business_id]
            if not rows:
                out(f"\n  No invoice {args.invoice_number} for business_id="
                    f"{args.business_id} here.")
                return 1
        elif len(rows) > 1:
            out(f"\n  {len(rows)} businesses in this database hold an invoice "
                f"numbered {args.invoice_number}.")
            out("  Invoice numbers are per-business, so pick one. The BizID is "
                "the column\n  that means the same thing on both databases — "
                "match on that, not the integer.\n")
            for r in rows:
                out(f"    --business-id {str(r['business_id']):<5} "
                    f"{str(r['public_id'] or '(none)'):<12} "
                    f"{str(r['business_name'] or '-'):<24} "
                    f"total={_f(r['total_amount']):,.2f}  "
                    f"paid={_f(r['paid_amount']):,.2f}  {r['status']}")
            return 2

        for r in rows:
            full = con.execute(
                "SELECT id, invoice_id, business_id, total_amount, paid_amount, "
                "       status, cash_discount, round_off, uid, created_at, "
                "       updated_at "
                "FROM invoices WHERE id = ?", (r["id"],)).fetchone()
            _report(con, full, args.json)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
