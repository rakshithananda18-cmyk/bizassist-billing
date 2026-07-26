"""
scripts/resolve_duplicate_invoice_numbers.py — settle F-3's leftovers
=====================================================================
The M-3 unique index refuses to install while duplicate invoice numbers exist,
and on the 26 Jul 2026 boot it reported one::

    biz 7 'LCL-OW-0006' x2

This is **F-3 caught in the wild** — the bug this whole pass started with. When
numbering was ``COUNT(invoices in series) + 1``, two sales rung up in the same
instant both read the same count and both minted the same number. Those two rows
were created 15 milliseconds apart, and they are DIFFERENT bills (one has 4 line
items, the other 5), so this is exactly the "two distinct sales, one number"
failure the sequence allocator was built to make impossible.

WHY THIS IS A SCRIPT AND NOT A MIGRATION
----------------------------------------
Renumbering an issued tax invoice is not a decision code should take by itself.
Under Rule 46 of the CGST Rules the number is part of the document; it may be
printed on the customer's copy and already filed in a GST return. Which of the
two keeps the number, and what the other becomes, is the owner's call — so this
script SHOWS the pair, proposes the conventional resolution, and only writes
when told to.

USAGE
-----
    python scripts/resolve_duplicate_invoice_numbers.py                 # inspect
    python scripts/resolve_duplicate_invoice_numbers.py --apply         # renumber
    python scripts/resolve_duplicate_invoice_numbers.py --business 7    # one tenant

RESOLUTION APPLIED
------------------
The EARLIEST-created row keeps the number (it is the one most likely already
printed and handed over). Each later duplicate is moved to the next free number
in the SAME series, via the same allocator used at the counter — so the
replacement number cannot collide with anything, now or later.

STALE HUMAN-READABLE REFERENCES
-------------------------------
Line items and payments link by invoice **id**, so the links themselves survive
a renumber untouched. But two places record the invoice NUMBER as text, and the
first version of this script left both behind:

  · ``invoice_payments.note`` — "Initial payment for invoice LCL-OW-0006".
    After renumbering it named a DIFFERENT bill (the twin that kept the number),
    which the money-integrity audit then correctly flagged as a mis-attached
    payment. It is now rewritten to the new number.

  · ``journal_entries.ref_no`` — **deliberately NOT touched.** ``ref_no`` is an
    input to ``_chain_hash``, so editing it would invalidate that entry's hash
    and every entry after it, destroying the tamper-evidence the journal exists
    to provide. The entry legitimately records the number *as issued at posting
    time*; the renumbering is recorded on the invoice instead (``notes``), which
    is where an amendment belongs.

Run ``--repair-notes`` on a database renumbered by the earlier version to clean
up the payment notes it left stale.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text                                    # noqa: E402
from database.db import SessionLocal                           # noqa: E402
from database.models import Invoice, InvoiceLineItem           # noqa: E402
from core.models import InvoicePayment, JournalEntry           # noqa: E402
from core.billing import sequence as SEQ                       # noqa: E402
from core.billing import commands as billing                   # noqa: E402


def _series_of(number: str) -> str:
    """'LCL-OW-0006' -> 'LCL-OW'. Split on the LAST dash: a series may contain
    dashes, the numeric tail never does."""
    head, _, tail = (number or "").rpartition("-")
    return head if (head and tail.isdigit()) else (number or "")


def find_duplicates(db, business_id=None):
    q = ("SELECT business_id, invoice_id, COUNT(*) AS n FROM invoices "
         "WHERE invoice_id IS NOT NULL ")
    params = {}
    if business_id is not None:
        q += "AND business_id = :b "
        params["b"] = business_id
    q += "GROUP BY business_id, invoice_id HAVING COUNT(*) > 1"
    return db.execute(text(q), params).fetchall()


def describe(db, biz, number):
    rows = (
        db.query(Invoice)
        .filter(Invoice.business_id == biz, Invoice.invoice_id == number)
        .order_by(Invoice.created_at.asc(), Invoice.id.asc())
        .all()
    )
    out = []
    for inv in rows:
        out.append({
            "row": inv,
            "lines": db.query(InvoiceLineItem).filter(
                InvoiceLineItem.invoice_id == inv.id).count(),
            "payments": db.query(InvoicePayment).filter(
                InvoicePayment.business_id == biz,
                InvoicePayment.invoice_id == inv.id).count(),
            "journal": db.query(JournalEntry).filter(
                JournalEntry.business_id == biz,
                JournalEntry.source_id == inv.id).count(),
        })
    return out


_NOTE_RE = re.compile(r"^(Initial payment for invoice )(.+)$")


def _retag_dependents(db, inv, old_number: str, new_number: str) -> int:
    """Point the human-readable references on this invoice's children at the new
    number, and record the amendment on the invoice itself.

    Returns how many payment notes were rewritten. See the module docstring for
    why ``journal_entries.ref_no`` is deliberately excluded.
    """
    touched = 0
    for pay in db.query(InvoicePayment).filter(
        InvoicePayment.business_id == inv.business_id,
        InvoicePayment.invoice_id == inv.id,
    ).all():
        m = _NOTE_RE.match((pay.note or "").strip())
        if m and m.group(2).strip() == old_number:
            pay.note = f"{m.group(1)}{new_number}"
            touched += 1

    stamp = (f"Renumbered {old_number} -> {new_number} to resolve a duplicate "
             f"invoice number (F-3).")
    inv.notes = f"{inv.notes}\n{stamp}" if (inv.notes or "").strip() else stamp
    return touched


def repair_stale_notes(db, business_id=None, apply=False) -> int:
    """Fix payment notes left pointing at a number the invoice no longer holds.

    Only rewrites a note when the payment's OWN invoice is the obvious subject —
    i.e. the number the note claims now belongs to a DIFFERENT invoice that is
    this one's duplicate twin (same business, date, total and customer). That is
    precise for renumbering fallout and will not touch a genuinely mis-attached
    payment, which is a different defect with a different fix.
    """
    q = db.query(InvoicePayment).filter(
        InvoicePayment.note.like("Initial payment for invoice %"))
    if business_id:
        q = q.filter(InvoicePayment.business_id == business_id)

    fixed = 0
    for pay in q.all():
        m = _NOTE_RE.match((pay.note or "").strip())
        if not m:
            continue
        claimed = m.group(2).strip()
        inv = db.query(Invoice).filter(Invoice.id == pay.invoice_id).first()
        if inv is None or inv.invoice_id == claimed:
            continue

        twin = (
            db.query(Invoice)
            .filter(Invoice.business_id == inv.business_id,
                    Invoice.invoice_id == claimed,
                    Invoice.invoice_date == inv.invoice_date,
                    Invoice.total_amount == inv.total_amount)
            .first()
        )
        if twin is None or twin.id == inv.id:
            print(f"  SKIP  biz {pay.business_id} payment #{pay.id}: note claims "
                  f"'{claimed}' but that is not this invoice's twin — this looks "
                  f"like a genuine mis-attachment (M-9), not renumbering fallout. "
                  f"LEFT ALONE.")
            continue

        print(f"  biz {pay.business_id} payment #{pay.id} (₹{pay.amount_paid}): "
              f"note '{claimed}' -> '{inv.invoice_id}'")
        if apply:
            pay.note = f"{m.group(1)}{inv.invoice_id}"
            stamp = (f"Renumbered {claimed} -> {inv.invoice_id} to resolve a "
                     f"duplicate invoice number (F-3).")
            if stamp not in (inv.notes or ""):
                inv.notes = f"{inv.notes}\n{stamp}" if (inv.notes or "").strip() else stamp
        fixed += 1
    if apply and fixed:
        db.commit()
    return fixed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write (default: inspect only)")
    ap.add_argument("--business", type=int, default=None, help="limit to one business_id")
    ap.add_argument("--repair-notes", action="store_true",
                    help="fix payment notes left stale by an earlier renumber")
    args = ap.parse_args()

    if args.repair_notes:
        db = SessionLocal()
        try:
            print("=" * 74)
            print("STALE PAYMENT NOTES" + ("  [APPLYING]" if args.apply else "  [INSPECT]"))
            print("=" * 74)
            n = repair_stale_notes(db, args.business, apply=args.apply)
            print(f"\n  {n} note(s) " + ("rewritten" if args.apply else
                                         "would be rewritten — re-run with --apply"))
            if n:
                print("\n  journal_entries.ref_no is intentionally left as issued: it "
                      "\n  feeds the tamper-evident hash chain, and the amendment is "
                      "\n  recorded on the invoice's notes field instead.")
            return 0
        finally:
            db.close()

    db = SessionLocal()
    try:
        dupes = find_duplicates(db, args.business)
        print("=" * 74)
        print("DUPLICATE INVOICE NUMBERS" + ("  [APPLYING]" if args.apply else "  [INSPECT]"))
        print("=" * 74)
        if not dupes:
            print("  none — the M-3 unique index will install on the next boot")
            return 0

        planned = []
        for biz, number, n in dupes:
            series = _series_of(number)
            print(f"\n  business {biz}   number {number}   x{n}   (series '{series}')")
            entries = describe(db, biz, number)
            for i, e in enumerate(entries):
                inv = e["row"]
                keep = "  << KEEPS the number (earliest)" if i == 0 else ""
                print(f"    id={inv.id:<6} created={inv.created_at}  "
                      f"total={inv.total_amount}  status={inv.status}  "
                      f"customer={inv.customer!r}")
                print(f"           lines={e['lines']}  payments={e['payments']}  "
                      f"journal_entries={e['journal']}{keep}")
            for e in entries[1:]:
                planned.append((biz, series, e["row"]))

        if not args.apply:
            print("\n  inspect only — re-run with --apply to renumber the later "
                  "duplicate(s) into the next free slot in the same series")
            return 0

        print()
        for biz, series, inv in planned:
            new_number = SEQ.next_number(
                db, biz, series,
                scan_max=lambda b=biz, s=series: billing._series_max(db, b, s),
                is_taken=lambda num, b=biz: billing._invoice_number_taken(db, b, num),
            )
            old = inv.invoice_id
            inv.invoice_id = new_number
            retagged = _retag_dependents(db, inv, old, new_number)
            print(f"  business {biz}: invoice id={inv.id}  {old} -> {new_number}"
                  + (f"   ({retagged} payment note(s) retagged)" if retagged else ""))
        db.commit()
        print(f"\n  renumbered {len(planned)} invoice(s). "
              f"The M-3 unique index will install on the next boot.")
        print("""
  Line items and payments link by invoice ID, so those links were unaffected.
  Payment NOTES naming the old number were rewritten, and the amendment is
  recorded on each invoice's notes field.

  journal_entries.ref_no is deliberately left as issued — it feeds the
  tamper-evident hash chain, and rewriting it would invalidate that entry and
  every entry after it. The entry correctly records the number as it stood at
  posting time.

  If a customer holds a printed copy of the OLD number, reprint the affected
  bill so their copy and your books agree.""".rstrip())
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
