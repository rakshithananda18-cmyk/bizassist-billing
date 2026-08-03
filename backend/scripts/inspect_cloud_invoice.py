"""
scripts/inspect_cloud_invoice.py — what does the CLOUD actually hold for one invoice?
=====================================================================================

READ ONLY. This script never writes to either database and never calls a repair
path. It fetches the cloud's own sync snapshot with the credentials the sync
worker already uses, and prints the raw rows for one invoice next to the local
rows for the same invoice.

WHY IT EXISTS
-------------
On 2026-08-01 LCL-OW-0037 read ₹124 paid on this device and ₹248 paid on the
cloud. Everything needed to reconstruct WHAT happened was in the local database
(the audit log had the cloud's own INSERT, replicated down while
`table_alterations` was still in the sync map). What was NOT available locally
was the state of the cloud row itself — its `uid`, its `updated_at` — and those
are exactly the two fields that decide whether the pull will ever deliver it:

  * no `uid`   → `_apply_pulled_row` declines the row outright.
  * `updated_at` older than the pull cursor → the cloud never offers it again.

Guessing between those two is the difference between a code fix and a data fix,
so this prints them instead.

WHERE TO RUN IT
---------------
On the machine running the local backend — it needs `cloud_sync_tokens.json`
(written at owner login) and network access to the cloud. From `backend/`:

    python scripts/inspect_cloud_invoice.py LCL-OW-0037
    python scripts/inspect_cloud_invoice.py LCL-OW-0037 --business-id 7
    python scripts/inspect_cloud_invoice.py LCL-OW-0037 --json

Exit codes: 0 = compared cleanly, 1 = could not reach or authenticate to the
cloud, 2 = bad arguments. A DIVERGENCE IS NOT AN ERROR — reporting one is the
point, so it still exits 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta

# Run from backend/ or from backend/scripts/ — both work.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# The token file path in sync_worker is relative to the CWD, so match it.
os.chdir(_BACKEND)

import httpx  # noqa: E402

from database.db import SessionLocal  # noqa: E402
from database.models import Invoice, InvoicePayment, User  # noqa: E402
from services.sync_worker import (  # noqa: E402
    CLOUD_URL,
    _get_cloud_token,
    ensure_fresh_cloud_token,
)

# ── The window, and why it is NOT the parity sweep's window ──────────────────
#
# First version of this script copied `_cloud_parity_check`:
#
#     params={"since": "2020-01-01T00:00:00"}
#
# and timed out at 180 s against the live Space. Two things are wrong with that
# line, and the second is the one that matters:
#
#  1. `/api/sync/pull` has no `since` parameter. Its signature is
#     `pull_changes(last_sync_at, limit, ...)`. FastAPI drops unknown query
#     params, so `since` was never read — `last_sync_at` resolved to None and
#     the endpoint fell through to `datetime(1970, 1, 1)`. The "2020" in that
#     string has never had any effect. Anyone narrowing it would have seen no
#     change and concluded the cloud was slow.
#
#  2. So every such call asks for EVERY ROW OF EVERY TABLE with no `limit`.
#     That is the same request shape that was timing out on 30 Jul when the
#     LCL-OW-0037 payment was lost.
#
# This script does not need a full snapshot — it is asking about ONE invoice. It
# sends the correct parameter, a window anchored just before that invoice was
# created, and a row cap. If the cap bites, it says so rather than reporting a
# truncated page as absence (rule 33).
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
_WINDOW_MARGIN_DAYS = 2
_DEFAULT_LIMIT = 5000


def _resolve_business(db, business_id):
    if business_id is not None:
        row = db.query(User).filter(User.id == business_id).first()
        if row is None:
            sys.exit(f"error: no user row with id={business_id}")
        return row
    owners = (
        db.query(User)
        .filter(User.parent_business_id.is_(None), User.public_id.isnot(None))
        .all()
    )
    if len(owners) == 1:
        return owners[0]
    listing = "\n".join(
        f"    --business-id {o.id:<5} {o.public_id:<12} {o.business_name}"
        for o in owners
    )
    sys.exit(
        "error: this database holds more than one business, so which one is "
        "ambiguous. Pick with --business-id:\n" + listing
    )


def _wake(url: str) -> None:
    """Ping /health first.

    The cloud runs on a Hugging Face Space, which sleeps when idle and takes
    tens of seconds to come back. Without this, that cold start is spent inside
    the big request and looks identical to the endpoint being too slow to
    answer — which is precisely the wrong conclusion to draw here.
    """
    try:
        httpx.get(f"{url}/health", timeout=httpx.Timeout(connect=10.0, read=90.0,
                                                         write=10.0, pool=10.0))
    except Exception as e:
        print(f"   (health ping did not answer: {e} — continuing)", file=sys.stderr)


def _fetch_cloud_snapshot(business_id: int, since: str, limit: int) -> dict:
    token = _get_cloud_token(business_id) or ensure_fresh_cloud_token(business_id)
    if not token:
        # Name the file (C-13 item 3). "No cloud token" and "I read the wrong
        # file" are the same sentence to whoever runs this, and only one of them
        # is fixed by signing in.
        from services.sync_worker import token_store_path
        store = token_store_path()
        sys.exit(
            f"error: no cloud token for business {business_id}.\n"
            f"  token store: {store} ({'exists' if store.exists() else 'DOES NOT EXIST'})\n"
            "  It is written at owner login — sign in to the app once, then re-run."
        )
    print(f"   asking {CLOUD_URL} for changes since {since} (limit {limit}/table)…",
          file=sys.stderr)
    _wake(CLOUD_URL)
    try:
        resp = httpx.get(
            f"{CLOUD_URL}/api/sync/pull",
            params={"last_sync_at": since, "limit": limit},
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
        )
    except Exception as e:
        sys.exit(
            f"error: could not reach {CLOUD_URL}: {e}\n"
            f"       The Space may be cold. Re-run once; if it fails again, "
            f"widen with --since or lower --limit."
        )

    if resp.status_code != 200:
        sys.exit(f"error: cloud returned HTTP {resp.status_code}: {resp.text[:300]}")

    body = resp.json()
    # Rule 33 in miniature: a table the cloud could not READ is not a table with
    # no rows, and calling it absent here would be the same mistake this script
    # was written to stop someone making by hand.
    failed = body.get("failed_tables") or []
    if failed:
        names = [f.get("table") if isinstance(f, dict) else str(f) for f in failed]
        print(
            f"!! WARNING: the cloud could not read {len(names)} table(s): {names}\n"
            f"!! Absence below cannot be trusted for those tables.\n",
            file=sys.stderr,
        )
    if body.get("has_more"):
        print(
            "!! WARNING: the cloud truncated this snapshot (has_more=true). A row "
            "not shown may simply be on the next page.\n",
            file=sys.stderr,
        )
    return body.get("changes", {}) or {}


def _fmt_payment(p: dict) -> str:
    return (
        f"      amount={float(p.get('amount_paid') or 0):>10.2f}  "
        f"mode={str(p.get('payment_mode')):<10} "
        f"uid={p.get('uid') or '** NONE **'}\n"
        f"        updated_at={p.get('updated_at')}  created_at={p.get('created_at')}\n"
        f"        idempotency_key={p.get('idempotency_key')}  note={p.get('note')!r}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("invoice_number", help="e.g. LCL-OW-0037")
    ap.add_argument("--business-id", type=int, default=None)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--since", default=None,
        help="ISO timestamp for the cloud window. Default: a couple of days "
             "before the local invoice was created. Widen it if the invoice "
             "does not appear in the snapshot.",
    )
    ap.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                    help="rows per table (the endpoint caps at 5000)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        owner = _resolve_business(db, args.business_id)
        bid = owner.id

        local_inv = (
            db.query(Invoice)
            .filter(Invoice.business_id == bid,
                    Invoice.invoice_id == args.invoice_number)
            .first()
        )
        local_pays = []
        if local_inv is not None:
            local_pays = (
                db.query(InvoicePayment)
                .filter(InvoicePayment.invoice_id == local_inv.id)
                .order_by(InvoicePayment.id)
                .all()
            )

        # Anchor the window on the invoice we are asking about. A full snapshot
        # is not needed to answer a question about one invoice, and asking for
        # one is what makes this request fail against the Space.
        if args.since:
            since = args.since
        elif local_inv is not None and local_inv.created_at:
            since = (local_inv.created_at - timedelta(days=_WINDOW_MARGIN_DAYS)).isoformat()
        else:
            since = (utc_now() - timedelta(days=30)).isoformat()

        changes = _fetch_cloud_snapshot(bid, since, args.limit)
        cloud_inv = next(
            (i for i in changes.get("invoices", [])
             if i.get("invoice_id") == args.invoice_number), None
        )
        cloud_pays = []
        if cloud_inv is not None:
            cloud_pays = [
                p for p in changes.get("invoice_payments", [])
                if p.get("invoice_id") == cloud_inv.get("id")
            ]

        local_sum = round(sum(float(p.amount_paid or 0) for p in local_pays), 2)
        cloud_sum = round(sum(float(p.get("amount_paid") or 0) for p in cloud_pays), 2)
        total = float((cloud_inv or {}).get("total_amount")
                      or (local_inv.total_amount if local_inv else 0) or 0)

        local_uids = {p.uid for p in local_pays if p.uid}
        cloud_uids = {p.get("uid") for p in cloud_pays if p.get("uid")}

        if args.json:
            print(json.dumps({
                "bizid": owner.public_id,
                "invoice_number": args.invoice_number,
                "total_amount": total,
                "local": {
                    "invoice_id": local_inv.id if local_inv else None,
                    "paid_amount": float(local_inv.paid_amount or 0) if local_inv else None,
                    "payment_sum": local_sum,
                    "payments": [
                        {"uid": p.uid, "amount": float(p.amount_paid or 0),
                         "mode": p.payment_mode, "updated_at": str(p.updated_at),
                         "idempotency_key": p.idempotency_key}
                        for p in local_pays
                    ],
                },
                "cloud": {
                    "invoice_id": (cloud_inv or {}).get("id"),
                    "paid_amount": (cloud_inv or {}).get("paid_amount"),
                    "payment_sum": cloud_sum,
                    "payments": cloud_pays,
                },
                "cloud_only_uids": sorted(cloud_uids - local_uids),
                "local_only_uids": sorted(local_uids - cloud_uids),
                "cloud_payments_without_uid": sum(
                    1 for p in cloud_pays if not p.get("uid")),
                "over_paid": bool(total and cloud_sum > total + 0.05),
            }, indent=2, default=str))
            return 0

        print(f"\n  {args.invoice_number}   BizID {owner.public_id}   "
              f"({owner.business_name})")
        print(f"  invoice total: {total:.2f}\n")

        if local_inv is None:
            print("  LOCAL   — invoice absent from this database —")
        else:
            print(f"  LOCAL   invoices.id={local_inv.id}  "
                  f"paid_amount={float(local_inv.paid_amount or 0):.2f}")
        print(f"          {len(local_pays)} payment(s), summing {local_sum:.2f}")
        for p in local_pays:
            print(f"      amount={float(p.amount_paid or 0):>10.2f}  "
                  f"mode={str(p.payment_mode):<10} uid={p.uid or '** NONE **'}\n"
                  f"        updated_at={p.updated_at}  created_at={p.created_at}\n"
                  f"        idempotency_key={p.idempotency_key}  note={p.note!r}")

        print()
        if cloud_inv is None:
            # NOT the same as "absent from the cloud". The pull filters on
            # `updated_at > last_sync_at`, so a window that starts after the
            # invoice's last write hides it. Say which one this is.
            print(f"  CLOUD   — not in the snapshot for the window starting "
                  f"{since} —\n"
                  f"          This is not proof of absence. Re-run with "
                  f"--since 2020-01-01T00:00:00 to widen it.")
        else:
            print(f"  CLOUD   invoices.id={cloud_inv.get('id')}  "
                  f"paid_amount={float(cloud_inv.get('paid_amount') or 0):.2f}")
            print(f"          {len(cloud_pays)} payment(s), summing {cloud_sum:.2f}")
            for p in cloud_pays:
                print(_fmt_payment(p))

        print("\n  ── verdict " + "─" * 55)
        clean = True
        if total and cloud_sum > total + 0.05:
            clean = False
            print(f"  OVER-PAID ON THE CLOUD: {cloud_sum:.2f} against a total of "
                  f"{total:.2f} (excess {cloud_sum - total:.2f}).")
        if cloud_uids - local_uids:
            clean = False
            print(f"  ON THE CLOUD, NOT HERE: {sorted(cloud_uids - local_uids)}")
        if local_uids - cloud_uids:
            clean = False
            print(f"  HERE, NOT ON THE CLOUD: {sorted(local_uids - cloud_uids)}")
        _no_uid = [p for p in cloud_pays if not p.get("uid")]
        if _no_uid:
            clean = False
            print(f"  {len(_no_uid)} cloud payment(s) carry NO uid. The pull "
                  f"declines these rather than risk duplicating money; they are "
                  f"now held in the inbox instead of being dropped.")
        if clean:
            print("  Both sides agree.")
        print()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
