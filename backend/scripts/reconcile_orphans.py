#!/usr/bin/env python3
"""
reconcile_orphans.py
====================
Safety-net sweep for orphaned / stranded rows — the class of debris behind the
July 2026 "phantom counters" bug, where deleting/re-keying a business left child
rows pointing at an owner that no longer exists (or never really existed).

It finds, and OPTIONALLY purges:

  1. Orphaned STAFF   — users.parent_business_id points at an owner row that is
                        gone (or is itself a staff row, which should never happen).
  2. Orphaned DATA    — any business-scoped table whose business_id has no live
                        owner (User with parent_business_id IS NULL).

DEFAULT IS READ-ONLY: it prints a report and changes nothing. Pass --purge to
delete, and --yes to skip the confirmation prompt. Always back up first.

Usage:
    python scripts/reconcile_orphans.py                 # report only
    python scripts/reconcile_orphans.py --purge         # delete (asks to confirm)
    python scripts/reconcile_orphans.py --purge --yes   # delete, no prompt
"""
import os
import sys
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND)

from sqlalchemy import text
from database.db import SessionLocal, DATABASE_URL, Base
from database.models import User
import database.models  # noqa: F401  — ensure all models register on Base


def _business_scoped_tables():
    out = []
    for name, table in Base.metadata.tables.items():
        if name == "users":
            continue
        if "business_id" in table.columns:
            out.append((name, table))
    return sorted(out, key=lambda t: t[0])


def find_orphans(db):
    live_owner_ids = {r[0] for r in db.query(User.id).filter(User.parent_business_id.is_(None)).all()}
    all_user_ids = {r[0] for r in db.query(User.id).all()}

    orphan_staff = (
        db.query(User)
          .filter(User.parent_business_id.isnot(None))
          .filter(~User.parent_business_id.in_(live_owner_ids))
          .all()
    )

    orphan_data = {}
    for name, _table in _business_scoped_tables():
        rows = db.execute(
            text(f"SELECT business_id, COUNT(*) c FROM {name} "
                 f"WHERE business_id IS NOT NULL GROUP BY business_id")
        ).fetchall()
        stray = {bid: c for (bid, c) in rows if bid not in live_owner_ids}
        if stray:
            orphan_data[name] = stray

    return orphan_staff, orphan_data, all_user_ids, live_owner_ids


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--purge", action="store_true", help="Actually delete the orphans (default: report only).")
    ap.add_argument("--yes", action="store_true", help="Skip the confirmation prompt when purging.")
    args = ap.parse_args()

    print(f"Target database: {DATABASE_URL}\n")
    db = SessionLocal()
    try:
        orphan_staff, orphan_data, all_ids, owner_ids = find_orphans(db)

        print(f"Owners (live businesses): {len(owner_ids)}   Total user rows: {len(all_ids)}")
        print("-" * 60)
        print(f"Orphaned STAFF rows: {len(orphan_staff)}")
        for s in orphan_staff:
            print(f"  id={s.id}  username={s.username!r}  parent_business_id={s.parent_business_id}  "
                  f"counter_prefix={s.counter_prefix!r}")

        total_data = sum(sum(v.values()) for v in orphan_data.values())
        print(f"\nOrphaned DATA rows: {total_data} across {len(orphan_data)} table(s)")
        for name, stray in orphan_data.items():
            print(f"  {name}: {stray}")
        print("-" * 60)

        if not orphan_staff and not orphan_data:
            print("No orphans found. Nothing to do.")
            return 0

        if not args.purge:
            print("\nREAD-ONLY report. Re-run with --purge to delete these rows.")
            return 0

        if not args.yes:
            resp = input("\nDelete ALL of the above? Type 'yes' to proceed: ").strip().lower()
            if resp != "yes":
                print("Aborted. Nothing changed.")
                return 1

        deleted_staff = 0
        for s in orphan_staff:
            db.delete(s)
            deleted_staff += 1
        deleted_data = 0
        for name, stray in orphan_data.items():
            bids = list(stray.keys())
            res = db.execute(
                text(f"DELETE FROM {name} WHERE business_id IN ("
                     + ",".join(":b%d" % i for i in range(len(bids))) + ")"),
                {f"b{i}": b for i, b in enumerate(bids)},
            )
            deleted_data += res.rowcount or 0
        db.commit()
        print(f"\nPurged {deleted_staff} staff row(s) and {deleted_data} data row(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
