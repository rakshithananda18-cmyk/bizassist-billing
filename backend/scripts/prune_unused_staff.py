#!/usr/bin/env python
"""
prune_unused_staff.py — remove staff accounts that were never used.

WHY THIS EXISTS
---------------
Staff accounts accumulate and nothing ever says so. On the live database
(2026-07-31) one business held 24 cashier logins where the owner had created 2:

    counter_1 / counter_2      created 30 Jul, prefixes C1/C2 — the real ones
    22 others                  created across 12–26 Jul, names like
                               `c_794eb357`, `cash_5b8c8965`

The 22 were created deliberately, through authenticated `POST /staff` calls at
22 distinct times — the audit log has an INSERT for each. Nothing in the codebase
generates names of that shape, so they came from a client: almost certainly
manual testing. The application did not invent them.

What the application DID get wrong is that there was no way to notice. The Staff
screen showed a name, a role and a counter prefix, so an abandoned account was
indistinguishable from a working till. `users.last_login` now exists to close
that, and this script acts on it.

WHAT COUNTS AS "NEVER USED"
---------------------------
`last_login IS NULL` — the account has never authenticated. That is the only
safe signal. Deliberately NOT used:

  * "looks auto-generated" — a name-shape heuristic would eventually delete
    somebody's real till because they named it `c_2`;
  * "old" — a seasonal counter idle for six months is still a real account;
  * "no invoices" — a supply-adder legitimately raises none.

Accounts that predate the `last_login` column also read as NULL. That is why
`--require-age-days` exists and defaults to 7: a row created before the column
shipped has an old `created_at`, and one created since has had a chance to be
used. Combined, they are a reasonable proxy; alone, neither is.

SAFETY
------
* DRY RUN BY DEFAULT. `--apply` is required.
* Refuses to touch an account that has EVER been used (`last_login` set).
* Refuses to touch an account referenced by any invoice, shift or ledger row it
  can find — a login attached to real trade is history, not clutter.
* Never touches an owner (`parent_business_id IS NULL`).
* Prints every row and every reason before doing anything.
* CLOUD FIRST. A staff login lives in two databases; `DELETE /staff/{id}` pushes
  a tombstone to the cloud so "deleted cashiers can no longer log in". Deleting
  only the local row would leave the credential LIVE on the cloud backend and
  remove the owner's only way to see it — worse than not deleting at all. A row
  is removed locally only after its tombstone is accepted.

USAGE
-----
    python scripts/prune_unused_staff.py --business 7
    python scripts/prune_unused_staff.py --business 7 --apply
    python scripts/prune_unused_staff.py --business 7 --keep counter_1,counter_2 --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text                                    # noqa: E402
from database.db import SessionLocal                           # noqa: E402
from database.models import User                               # noqa: E402
from services.dates import utc_now                             # noqa: E402


def _in_use(db, staff: User) -> str | None:
    """A reason this account is NOT clutter, or None.

    Over-inclusive on purpose: anything found here spares the row. A false
    positive leaves one unused login behind; a false negative deletes a login
    that real trade points at.
    """
    probes = [
        ("invoices",             "user_id"),
        ("invoices",             "created_by"),
        ("register_shifts",      "user_id"),
        ("shift_cash_movements", "user_id"),
        ("invoice_payments",     "user_id"),
        ("stock_ledger",         "user_id"),
    ]
    for table, col in probes:
        try:
            n = db.execute(
                text(f'SELECT COUNT(*) FROM "{table}" WHERE "{col}" = :i'),
                {"i": staff.id},
            ).scalar()
            if n:
                return f"{n} row(s) in {table}.{col}"
        except Exception:
            continue          # table/column absent here — nothing to protect
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--business", type=int, required=True,
                    help="owner's local user id (e.g. 7)")
    ap.add_argument("--keep", default="",
                    help="comma-separated names OR ids to spare, e.g. "
                         "'counter_1,counter_2' or 'id:88,id:89'. Use ids when a "
                         "name is claimed by more than one account.")
    ap.add_argument("--require-age-days", type=int, default=7,
                    help="only prune accounts older than this (default 7)")
    ap.add_argument("--dedupe-keep", default="",
                    help="resolve duplicate login names: 'id:88,id:89' keeps "
                         "those rows and deletes the OTHER rows sharing their "
                         "name. LOCAL-ONLY — no cloud tombstone is sent. See "
                         "the note in the source about why.")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default is a dry run)")
    args = ap.parse_args()

    keep = {k.strip().lower() for k in args.keep.split(",") if k.strip()}
    cutoff = utc_now() - timedelta(days=args.require_age_days)

    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.id == args.business,
                                      User.parent_business_id == None).first()  # noqa: E711
        if not owner:
            print(f"No business owner with id={args.business}.")
            return 1

        staff = (db.query(User)
                   .filter(User.parent_business_id == owner.id)
                   .order_by(User.id).all())
        print(f"Business : {owner.business_name} (id={owner.id}, {owner.public_id})")
        print(f"Staff     : {len(staff)}\n")

        # Login names that more than one row claims. A cashier typing
        # "counter_1" cannot be resolved to a single account, so this is a real
        # defect in its own right — and it means a name is NOT a safe way to say
        # which row to keep. Both sides are spared and reported; the owner picks
        # by id.
        by_name: dict = {}
        for s in staff:
            by_name.setdefault((s.staff_login_name or s.username or "").lower(), []).append(s)
        ambiguous = {n for n, rows in by_name.items() if len(rows) > 1}

        keep_ids = {int(k[3:]) for k in keep if k.startswith("id:") and k[3:].isdigit()}
        keep_names = {k for k in keep if not k.startswith("id:")}
        dedupe_keep_ids = {int(k[3:]) for k in
                           (x.strip() for x in args.dedupe_keep.split(",") if x.strip())
                           if k.startswith("id:") and k[3:].isdigit()}

        prune, spared, dedupe = [], [], []
        for s in staff:
            name = (s.staff_login_name or s.username or "").lower()
            if s.id in keep_ids:
                spared.append((s, "explicitly kept by id")); continue
            if name in keep_names:
                spared.append((s, "explicitly kept by name")); continue
            if name in ambiguous:
                if s.id in dedupe_keep_ids:
                    spared.append((s, f"kept as the canonical {name!r}")); continue
                if dedupe_keep_ids & {r.id for r in by_name[name]}:
                    # A canonical row was named for THIS name, so the rest are
                    # redundant copies. LOCAL-ONLY delete — see `dedupe` below.
                    dedupe.append(s); continue
                # Never auto-resolve a duplicate. Deleting "the wrong counter_1"
                # is unrecoverable and the script cannot know which is which.
                spared.append((s, f"AMBIGUOUS — {len(by_name[name])} accounts share "
                                  f"the name {name!r}; resolve with --dedupe-keep id:<n>"))
                continue
            if getattr(s, "last_login", None) is not None:
                spared.append((s, f"has logged in ({s.last_login})")); continue
            if s.created_at is None:
                # Unknown age is NOT young and NOT old — it is unknown, and the
                # only safe reading of unknown is "do not delete".
                #
                # This was a bug: the guard read `if s.created_at and ... > cutoff`,
                # so a NULL fell straight through to be pruned. Both of this
                # business's REAL counters have `created_at = NULL` (they were
                # written by a path that never set it), so the age guard would
                # have deleted exactly the two accounts it exists to protect.
                spared.append((s, "created_at is NULL — age unknown, not deleting"))
                continue
            if s.created_at > cutoff:
                spared.append((s, f"created less than {args.require_age_days}d ago")); continue
            reason = _in_use(db, s)
            if reason:
                spared.append((s, f"referenced by real data — {reason}")); continue
            prune.append(s)

        if ambiguous:
            unresolved = sorted(
                n for n in ambiguous
                if not (dedupe_keep_ids & {r.id for r in by_name[n]})
            )
            resolved = sorted(ambiguous - set(unresolved))
            if unresolved:
                print("DUPLICATE LOGIN NAMES — resolve these before pruning:")
                for n in unresolved:
                    rows = by_name[n]
                    print(f"  {n!r} is claimed by {len(rows)} accounts:")
                    for r in rows:
                        print(f"     id={r.id:<5} internal={r.username:<20} "
                              f"prefix={r.counter_prefix or '—':<4} created={r.created_at}")
                print("  Pick one per name with --dedupe-keep id:<n>\n")
            if resolved:
                print("DUPLICATE LOGIN NAMES — resolved by --dedupe-keep:")
                for n in resolved:
                    rows = by_name[n]
                    kept = [r for r in rows if r.id in dedupe_keep_ids]
                    drop = [r for r in rows if r.id not in dedupe_keep_ids]
                    k = ", ".join(f"id={r.id} ({r.username})" for r in kept)
                    d = ", ".join(f"id={r.id} ({r.username})" for r in drop)
                    print(f"  {n!r}: keeping {k} · dropping {d}")
                print()

        print("KEEPING:")
        for s, why in spared:
            print(f"  id={s.id:<5} {(s.staff_login_name or s.username):<22} "
                  f"{s.counter_prefix or '—':<5} {why}")

        print("\nWOULD DELETE (never logged in, no data attached):")
        for s in prune:
            print(f"  id={s.id:<5} {(s.staff_login_name or s.username):<22} "
                  f"created={s.created_at}")
        if not prune:
            print("  (none)")

        if dedupe:
            print("\nWOULD DELETE AS DUPLICATES — LOCAL ONLY, no cloud tombstone:")
            for s in dedupe:
                print(f"  id={s.id:<5} internal={s.username:<22} "
                      f"(redundant copy of {(s.staff_login_name or '')!r})")

        if not prune and not dedupe:
            return 0

        if not args.apply:
            print(f"\nDRY RUN. {len(prune)} account(s) would be deleted"
                  + (f" and {len(dedupe)} duplicate(s) removed locally" if dedupe else "")
                  + ". Re-run with --apply.")
            return 0

        # ── CLOUD FIRST, THEN LOCAL ──────────────────────────────────────────
        # A staff login exists in TWO places. `DELETE /staff/{id}` pushes a
        # tombstone to the cloud precisely so "deleted cashiers can no longer log
        # in" — deleting only the local row leaves the credential live on the
        # cloud backend, and removes the owner's only way to see it and remove
        # it. That is strictly worse than leaving the account alone.
        #
        # So the cloud goes first, and a local row is deleted ONLY once its
        # tombstone is accepted. A business with no cloud link has nothing to
        # tombstone and proceeds normally.
        from core.api.staff import _push_staff_to_cloud
        from services.sync_worker import _get_cloud_token

        cloud_linked = bool(_get_cloud_token(owner.id))
        if not cloud_linked:
            print("\nThis business has no cloud token — local-only, nothing to "
                  "tombstone on the cloud.")

        deleted, stranded = 0, []
        for s in prune:
            bare = s.staff_login_name or s.username
            if cloud_linked:
                try:
                    _push_staff_to_cloud(owner.id, [{
                        "staff_login_name": bare,
                        "internal_username": "",
                        "hashed_password": "",
                        "role": "",
                        "counter_prefix": None,
                        "deleted": True,
                    }])
                except Exception as e:
                    stranded.append((bare, str(e)[:120]))
                    continue
            db.delete(s)
            deleted += 1
        db.commit()

        # ── DUPLICATES: LOCAL DELETE, NO TOMBSTONE ───────────────────────────
        # The cloud matches a tombstone by staff_login_name, NOT by id:
        #
        #     existing = db.query(User).filter(
        #         User.parent_business_id == owner_id,
        #         func.lower(User.staff_login_name) == bare).first()
        #     if rec.deleted: db.delete(existing)
        #
        # A duplicate pair is two LOCAL rows sharing ONE name, and the cloud has
        # exactly one row for that name — the legitimate one. Sending a tombstone
        # to remove the local copy would therefore delete the cashier's real
        # cloud account, and they would be unable to log in from any
        # cloud-connected device until a later staff push happened to recreate
        # it. The duplicate is a local artefact; its removal is a local matter.
        #
        # (Where the copies came from: the cloud's `_resolve_username` appends
        # `_c<n>` when an internal username is already taken globally, which is
        # exactly the `counter_1_c7` shape. Those cloud-named rows found their
        # way back into the local database.)
        dedupe_done = 0
        for s in dedupe:
            db.delete(s)
            dedupe_done += 1
        if dedupe_done:
            db.commit()

        print(f"\nDeleted {deleted} unused staff account(s). {len(spared)} kept.")
        if dedupe_done:
            print(f"Removed {dedupe_done} duplicate local row(s) — cloud untouched "
                  f"on purpose, its copy of that login is the real one.")
        if stranded:
            print(f"\n{len(stranded)} NOT deleted — the cloud would not accept the "
                  f"tombstone, so the login is still live there. Left in place so "
                  f"you can still see and remove them:")
            for bare, err in stranded:
                print(f"  {bare:<22} {err}")
            print("Re-run once the cloud is reachable.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
