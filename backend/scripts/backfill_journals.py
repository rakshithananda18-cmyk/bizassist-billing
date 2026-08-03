"""
scripts/backfill_journals.py — post the journal for documents that never got one
================================================================================
`core/accounting/repost.py` makes sure every document that arrives over sync gets
a journal entry on the receiving side. It does nothing for documents that are
ALREADY sitting in the database with no entry — and the 26 Jul 2026 audit found
plenty::

    biz 6 (SaaS Production):  38 invoices,  0 journal entries
    biz 7 (Brownie Factory):  28 invoices, 24 entries, 0 for its 30 receipts

Those businesses' trial balance, P&L and party ledger read from
`journal_entries`, so they were silently empty or short while the POS looked
perfectly normal. That is M-2's real blast radius: not "some rows missing" but
an entire business with no books.

    python scripts/backfill_journals.py                 # dry run
    python scripts/backfill_journals.py --apply
    python scripts/backfill_journals.py --business 6 --apply

WHAT IT POSTS
-------------
Sales, credit notes, purchases, debit notes, expenses and receipts — reusing the
exact same `core/accounting/posting` builders the counter uses, so a backfilled
entry is byte-identical to one posted at sale time. Idempotent on
(business_id, source_type, source_id), so re-running posts nothing twice.

WHAT IT SKIPS, AND WHY
----------------------
· **Zero-value CSV imports.** A legacy imported invoice carries no totals and no
  tax breakdown. There is nothing to post; inventing an entry would fabricate
  revenue that never existed.
· **Anything that fails to balance.** `post_entry` refuses unbalanced entries and
  this script lets that refusal stand, reporting the document instead. A
  document whose numbers do not foot is a data problem to look at, not one to
  paper over.

PERIOD LOCKS ARE BYPASSED, deliberately — same reasoning as the sync repost. The
documents are historical fact that predate the lock; refusing them would leave
the business holding documents with no books, which is strictly worse than a
late entry in a closed period.

ORDERING: documents are posted oldest-first so the hash chain is built in
document order rather than in whatever order the rows were inserted.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ── --db, resolved BEFORE `database.db` is imported ──────────────────────────
#
# WHY IT IS DONE HERE AND NOT IN main()
# `database/db.py` reads DATABASE_URL **at import time**: it builds the engine,
# and for SQLite it also attaches the `PRAGMA foreign_keys=ON` /
# `busy_timeout` connect listeners. Re-pointing anything after the import would
# leave the engine bound to the original target — the script would print the
# database you asked for and write to the one it already opened. So the value
# has to be in the environment before line `from database.db import ...` runs.
#
# WHY THIS SCRIPT NEEDED IT AT ALL
# It posts through `core/accounting/posting`, so unlike the raw-SQL repair
# scripts it needs a real ORM Session and cannot use `_dbcompat.connect`.
# Without --db it could only ever reach whatever the APPLICATION was pointed at,
# which is exactly why the 47 journal-less documents on the CLOUD could not be
# touched (SYNC_LIVENESS_AUDIT §7b.7 lists this class of gap).
#
# This is NOT the "inherit whatever DATABASE_URL happens to be" anti-pattern the
# runbook warns about: the value comes from an explicit flag the operator typed,
# and the banner below prints the target it actually opened.
def _early_db_target() -> "str | None":
    for i, a in enumerate(sys.argv):
        if a == "--db" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith("--db="):
            return a.split("=", 1)[1]
    return None


_DB_TARGET = _early_db_target()
if _DB_TARGET:
    os.environ["DATABASE_URL"] = _DB_TARGET


def _safe_target(url: str) -> str:
    """The target, with any password removed. Never print a raw URL."""
    try:
        from _dbcompat import _redact          # scripts/ is sys.path[0] when run
        return _redact(url)
    except Exception:
        return url.split("@")[-1] if "@" in url else url


from database.db import SessionLocal                           # noqa: E402
from database.models import Invoice, PurchaseInvoice           # noqa: E402
from core.models import InvoicePayment, JournalEntry, Expense  # noqa: E402
from core.accounting import repost                             # noqa: E402


def _has_entry(db, business_id, source_type, source_id) -> bool:
    return db.query(JournalEntry.id).filter(
        JournalEntry.business_id == business_id,
        JournalEntry.source_type == source_type,
        JournalEntry.source_id == source_id,
    ).first() is not None


def _postable_amount(obj) -> float:
    """The figure the posting builders will actually read.

    Deliberately does NOT fall back to the legacy `amount` column for invoices.
    A CSV-imported row sets `amount` but leaves `total_amount` and every tax
    total at zero, and `build_sale_lines` reads `total_amount` — so treating
    `amount` as postable would write an entry of all zeros. An empty entry in a
    tamper-evident ledger is worse than a missing one: it looks like books.
    """
    for attr in ("total_amount", "amount_paid"):
        v = getattr(obj, attr, None)
        if v:
            return round(float(v), 2)
    return 0.0


def collect(db, business_id=None):
    """Every document lacking its entry, oldest-first, as (entity, obj)."""
    work = []

    q = db.query(Invoice)
    if business_id:
        q = q.filter(Invoice.business_id == business_id)
    for inv in q.order_by(Invoice.invoice_date.asc(), Invoice.id.asc()).all():
        want = "credit_note" if (inv.invoice_type or "") == "credit_note" else "sale"
        if _has_entry(db, inv.business_id, want, inv.id):
            continue
        if not _postable_amount(inv):
            continue                      # legacy CSV import — nothing to post
        work.append(("invoices", inv))

    q = db.query(PurchaseInvoice)
    if business_id:
        q = q.filter(PurchaseInvoice.business_id == business_id)
    for pur in q.order_by(PurchaseInvoice.id.asc()).all():
        want = "debit_note" if (getattr(pur, "invoice_type", None) or "") == "debit_note" else "purchase"
        if _has_entry(db, pur.business_id, want, pur.id) or not _postable_amount(pur):
            continue
        work.append(("purchase_invoices", pur))

    q = db.query(Expense)
    if business_id:
        q = q.filter(Expense.business_id == business_id)
    for exp in q.order_by(Expense.id.asc()).all():
        if _has_entry(db, exp.business_id, "expense", exp.id) or not _postable_amount(exp):
            continue
        work.append(("expenses", exp))

    # Receipts LAST: a payment entry credits Accounts Receivable, which only
    # makes sense once its invoice's own entry has debited it.
    #
    # INITIAL receipts are skipped — they are already inside their invoice's sale
    # entry (`build_sale_lines` debits Cash for `paid_amount`). Backfilling them
    # would debit Cash a SECOND time for every mark_paid sale, and the trial
    # balance would still foot, so nothing would flag it. See
    # `repost.is_initial_payment`. `repost_synced_row` refuses them anyway; they
    # are filtered here too so the dry-run count is honest.
    q = db.query(InvoicePayment)
    if business_id:
        q = q.filter(InvoicePayment.business_id == business_id)
    for pay in q.order_by(InvoicePayment.id.asc()).all():
        if _has_entry(db, pay.business_id, "payment", pay.id) or not _postable_amount(pay):
            continue
        if repost.is_initial_payment(pay):
            continue
        work.append(("invoice_payments", pay))

    return work


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--business", type=int, default=None)
    ap.add_argument("--db", default=None,
                    help="target database (path or postgres URL). Applied before "
                         "the engine is built — see the note at the top of this "
                         "file. Defaults to DATABASE_URL / the app's database.")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        work = collect(db, args.business)
        print("=" * 74)
        print("JOURNAL BACKFILL" + ("  [APPLYING]" if args.apply else "  [DRY RUN]"))
        # Always state which database was opened. Every serious mistake in this
        # project's repair history has been a correct answer about the wrong
        # database (SYNC_LIVENESS_AUDIT §5.1), so the target is not optional
        # output.
        print(f"target: {_safe_target(os.environ.get('DATABASE_URL', '(default)'))}"
              f"   engine: {db.bind.dialect.name}")
        print("=" * 74)

        by_biz = {}
        for entity, obj in work:
            by_biz.setdefault(obj.business_id, []).append((entity, obj))
        for biz, items in sorted(by_biz.items()):
            counts = {}
            for entity, _ in items:
                counts[entity] = counts.get(entity, 0) + 1
            print(f"  business {biz}: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
        if not work:
            print("  nothing to backfill — every document already has its entry")
            return 0
        print(f"\n  {len(work)} document(s) total")

        if not args.apply:
            print("\n  dry run — re-run with --apply to post")
            return 0

        posted = failed = 0
        for entity, obj in work:
            res = repost.repost_synced_row(db, entity, obj, log_prefix="backfill")
            if res.status == "posted":
                posted += 1
            elif res.status == "failed":
                failed += 1
                print(f"  FAILED  {entity}#{obj.id} (biz {obj.business_id}): {res.error}")
        db.commit()

        print(f"\n  posted {posted} entry(ies)"
              + (f", {failed} failed — listed above" if failed else ""))
        if failed:
            print("  A failure here means the document's own numbers do not foot. "
                  "Left unposted deliberately; investigate rather than force it.")

        from core.accounting import posting
        print("\n  chain verification:")
        for biz in sorted(by_biz):
            rep = posting.verify_chain(db, biz)
            print(f"    business {biz}: "
                  + ("ok" if rep["ok"] else f"BROKEN at {rep.get('broken_at')}")
                  + f"  ({rep['checked']} entries)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
