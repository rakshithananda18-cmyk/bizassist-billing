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
phantom business. Measured on the live database 2026-07-31: all 32 staff rows
carried a BizID, against 9 real owners — which is why the nightly job logged

    [SCHED] Running books integrity audit for 40 business(es)...

The backfill no longer does this. This script cleans up what it already did.

SAFETY
------
* DRY RUN BY DEFAULT. `--apply` is required to write anything.
* Touches exactly ONE column, `public_id`, on rows where
  `parent_business_id IS NOT NULL`. Never deletes a row, never touches an owner,
  never touches a password, role or counter prefix.
* Refuses to clear a BizID that is REFERENCED anywhere it can check — a stray id
  that something already points at is a migration problem, not a cleanup one,
  and silently breaking that pointer is worse than leaving the row alone.
* Prints every row it would change, before changing it.

USAGE
-----
    python scripts/clear_staff_bizids.py            # dry run — shows the plan
    python scripts/clear_staff_bizids.py --apply    # perform it
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text                                    # noqa: E402
from database.db import SessionLocal                           # noqa: E402
from database.models import User                               # noqa: E402


def _referenced_bizids(db) -> set:
    """BizIDs that something else already points at.

    Best-effort and deliberately over-inclusive: anything found here is left
    alone. A false positive costs one uncleaned row; a false negative breaks a
    live reference.
    """
    found = set()
    probes = [
        # (table, column) pairs that store a BizID string.
        ("b2b_connections", "seller_public_id"),
        ("b2b_connections", "buyer_public_id"),
        ("b2b_orders",      "seller_public_id"),
        ("b2b_orders",      "buyer_public_id"),
    ]
    for table, col in probes:
        try:
            rows = db.execute(
                text(f'SELECT DISTINCT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL')
            ).fetchall()
            found.update(r[0] for r in rows if r[0])
        except Exception:
            # Table or column absent on this deployment — nothing to protect.
            continue
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="actually write the change (default is a dry run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        staff = (
            db.query(User)
            .filter(User.public_id != None,               # noqa: E711
                    User.parent_business_id != None)      # noqa: E711
            .order_by(User.parent_business_id, User.id)
            .all()
        )
        owners = (
            db.query(User)
            .filter(User.parent_business_id == None)      # noqa: E711
            .count()
        )

        print(f"Real business owners : {owners}")
        print(f"Staff holding a BizID: {len(staff)}")
        print(f"Per-business sweeps currently iterate: {owners + len(staff)}\n")

        if not staff:
            print("Nothing to do — no staff account holds a BizID.")
            return 0

        referenced = _referenced_bizids(db)
        clearable, protected = [], []
        for s in staff:
            (protected if s.public_id in referenced else clearable).append(s)

        print("WOULD CLEAR:")
        for s in clearable:
            print(f"  id={s.id:<6} {s.username:<28} parent={s.parent_business_id:<6} "
                  f"public_id={s.public_id}")

        if protected:
            print("\nLEFT ALONE — referenced elsewhere, clearing would break a live pointer:")
            for s in protected:
                print(f"  id={s.id:<6} {s.username:<28} public_id={s.public_id}")

        if not args.apply:
            print(f"\nDRY RUN. {len(clearable)} row(s) would change. "
                  f"Re-run with --apply to perform it.")
            return 0

        for s in clearable:
            s.public_id = None
        db.commit()
        print(f"\nDone. Cleared {len(clearable)} staff BizID(s).")
        print(f"Per-business sweeps will now iterate {owners} owner(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
