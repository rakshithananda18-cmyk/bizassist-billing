"""
scripts/audit_money_integrity.py — is the money actually right?
===============================================================
A read-only report over the whole database. Every check here exists because the
corresponding defect was found in REAL data on 26 Jul 2026, not because it
seemed like a good idea.

    python scripts/audit_money_integrity.py
    python scripts/audit_money_integrity.py --business 6
    python scripts/audit_money_integrity.py --db backend/bizassist.db

Writes nothing. Exit code 1 if any check fails, so it can gate a deploy.

THE CHECKS
----------
A. Mis-attached payments (M-9)
   `create_sale_invoice` stamps every initial receipt with
   `note = "Initial payment for invoice <number>"`. That note is an independent
   record of which invoice the money was FOR, so it can be compared against the
   invoice the row actually points at. Two mismatches were found in production —
   money credited to the wrong customer's invoice.

B. Missing journal entries (M-2)
   Every sale, credit note, purchase, expense and receipt must have exactly one
   entry. One business was found with 38 invoices and ZERO entries: its trial
   balance, P&L and party ledger were all empty while the POS looked fine.

C. Paid state vs the payment ledger (M-7)
   Reported in both directions, but the two directions mean different things —
   see the notes printed with the results.

D. Orphan and cross-tenant payments
   A receipt pointing at no invoice, or at another business's invoice.

E. Duplicate invoice numbers (F-3)
   Two documents sharing one number. Blocks the M-3 unique index.

F. Journal entries that do not foot
   Σ debits != Σ credits. Should be impossible — `post_entry` refuses to write
   an unbalanced entry — so a hit here means something wrote the table directly.
"""
import argparse
import os
import re
import sqlite3
import sys

_INITIAL_PAYMENT = re.compile(r"^Initial payment for invoice (.+)$")


def _connect(path):
    if not os.path.exists(path):
        sys.exit(f"database not found: {path}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(c, name):
    return c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _where_biz(biz, col="business_id"):
    return (f" AND {col} = {int(biz)}", "") if biz else ("", "")


class Report:
    def __init__(self):
        self.sections = []
        self.failures = 0

    def add(self, title, rows, note=""):
        self.sections.append((title, rows, note))
        if rows:
            self.failures += len(rows)

    def render(self):
        for title, rows, note in self.sections:
            mark = "FAIL" if rows else " ok "
            print(f"\n[{mark}] {title}  ({len(rows)})")
            if note and rows:
                for line in note.strip().splitlines():
                    print(f"       {line.strip()}")
            for r in rows[:40]:
                print(f"   - {r}")
            if len(rows) > 40:
                print(f"   … and {len(rows) - 40} more")


def audit(c, biz=None):
    rep = Report()
    bfilter = f" AND business_id = {int(biz)}" if biz else ""

    # ── A. Mis-attached payments ────────────────────────────────────────────
    rows = []
    for p in c.execute(
        f"SELECT * FROM invoice_payments WHERE note LIKE 'Initial payment for invoice %'{bfilter}"
    ):
        m = _INITIAL_PAYMENT.match((p["note"] or "").strip())
        if not m:
            continue
        claimed = m.group(1).strip()
        inv = c.execute("SELECT invoice_id, total_amount FROM invoices WHERE id = ?",
                        (p["invoice_id"],)).fetchone()
        actual = inv["invoice_id"] if inv else None
        if actual != claimed:
            here = c.execute(
                "SELECT id FROM invoices WHERE business_id=? AND invoice_id=?",
                (p["business_id"], claimed)).fetchone()
            rows.append(
                f"biz {p['business_id']} payment #{p['id']} ₹{p['amount_paid']}: "
                f"note says '{claimed}', attached to '{actual}' "
                f"(target {'exists locally as id ' + str(here['id']) if here else 'NOT in this DB'})")
    rep.add("A. Mis-attached payments — money on the wrong invoice (M-9)", rows, """
        Each of these is a receipt credited to a customer other than the one who
        paid it. Re-point invoice_id at the invoice the note names, or delete the
        row if it belongs to a database this one should not hold.
    """)

    # ── B. Missing journal entries ──────────────────────────────────────────
    rows, legacy = [], []
    if _table_exists(c, "journal_entries"):
        for inv in c.execute(
            f"SELECT id, business_id, invoice_id, invoice_type, total_amount, amount "
            f"FROM invoices WHERE 1=1{bfilter}"
        ):
            want = "credit_note" if (inv["invoice_type"] or "") == "credit_note" else "sale"
            hit = c.execute(
                "SELECT 1 FROM journal_entries WHERE business_id=? AND source_type=? AND source_id=?",
                (inv["business_id"], want, inv["id"])).fetchone()
            if hit:
                continue
            # A CSV-imported row populates the LEGACY `amount` column but leaves
            # `total_amount` and the whole tax breakdown at zero. The posting
            # builders read `total_amount`, so such a row would produce an entry
            # of all zeros — junk in the ledger, not books. Nothing to post, and
            # nothing was ever missing. Counting them buries the real gaps under
            # hundreds of false positives, and a report nobody trusts is a report
            # nobody reads. Checked on `total_amount` specifically, NOT on
            # `amount`, because that is the field the builders actually consume.
            if not round(float(inv["total_amount"] or 0.0), 2):
                legacy.append(f"biz {inv['business_id']} {inv['invoice_id']}")
                continue
            rows.append(f"biz {inv['business_id']} {inv['invoice_id']} "
                        f"(₹{inv['total_amount']}) has no {want} entry")
        for p in c.execute(
            f"SELECT id, business_id, amount_paid, note FROM invoice_payments WHERE 1=1{bfilter}"
        ):
            # An INITIAL receipt (taken at sale time) is already booked inside its
            # invoice's sale entry — `build_sale_lines` debits Cash for
            # `paid_amount`. It must NOT have its own entry; flagging it here
            # would push someone into creating one and double-counting the cash.
            if (p["note"] or "").strip().startswith("Initial payment for invoice"):
                continue
            hit = c.execute(
                "SELECT 1 FROM journal_entries WHERE business_id=? AND source_type='payment' AND source_id=?",
                (p["business_id"], p["id"])).fetchone()
            if not hit:
                rows.append(f"biz {p['business_id']} payment #{p['id']} (₹{p['amount_paid']}) has no entry")
    rep.add("B. Documents with no journal entry (M-2)", rows, """
        The books are short by exactly these amounts. Trial balance, P&L and the
        party ledger all read from journal_entries, so they are wrong while this
        is non-empty. Fix with: python scripts/backfill_journals.py --apply
    """)
    if legacy:
        print(f"\n[info] {len(legacy)} zero-value CSV-imported invoice(s) have no "
              f"journal entry, which is correct — they carry no totals to post. "
              f"Excluded from section B.")

    # ── C. Paid state vs ledger ─────────────────────────────────────────────
    under, over, mismatch = [], [], []
    for r in c.execute(f"""
        SELECT i.id, i.business_id, i.invoice_id, i.status,
               ROUND(COALESCE(i.total_amount, i.amount, 0), 2) AS total,
               ROUND(COALESCE(i.paid_amount, 0), 2)            AS recorded,
               ROUND(COALESCE(SUM(p.amount_paid), 0), 2)       AS ledger
          FROM invoices i
          JOIN invoice_payments p ON p.invoice_id = i.id AND p.business_id = i.business_id
         WHERE 1=1{bfilter.replace('business_id', 'i.business_id')}
         GROUP BY i.id"""):
        if r["ledger"] > r["total"] + 0.01:
            over.append(f"biz {r['business_id']} {r['invoice_id']}: total ₹{r['total']}, "
                        f"payment rows sum to ₹{r['ledger']}")
        elif r["ledger"] < r["recorded"] - 0.01:
            under.append(f"biz {r['business_id']} {r['invoice_id']}: recorded ₹{r['recorded']}, "
                         f"payment rows only ₹{r['ledger']}")
        elif abs(r["ledger"] - r["recorded"]) > 0.01:
            mismatch.append(f"biz {r['business_id']} {r['invoice_id']}: recorded ₹{r['recorded']}, "
                            f"ledger ₹{r['ledger']} — the M-7 repair will raise this")
    rep.add("C1. Payment rows EXCEED the invoice total", over, """
        Usually a receipt attached to the wrong invoice — cross-check against
        section A before concluding a customer overpaid.
    """)
    rep.add("C2. Invoice records MORE paid than its rows show", under, """
        Either receipts have not synced down, or the recorded figure is wrong.
        NEVER auto-corrected: lowering it invents a debt and starts chasing a
        customer who may have paid.
    """)
    rep.add("C3. Invoice records LESS paid than its rows show (the M-7 bug)", mismatch)

    # ── D. Orphan / cross-tenant payments ───────────────────────────────────
    rows = [f"payment #{r['id']} (biz {r['business_id']}, ₹{r['amount_paid']}) "
            f"points at invoice id {r['invoice_id']} which does not exist"
            for r in c.execute(
                f"SELECT * FROM invoice_payments p WHERE invoice_id IS NOT NULL{bfilter} "
                f"AND NOT EXISTS (SELECT 1 FROM invoices i WHERE i.id = p.invoice_id)")]
    rep.add("D1. Orphan payments", rows)

    rows = [f"payment #{r['pid']} (biz {r['pb']}) → invoice {r['num']} of biz {r['ib']}"
            for r in c.execute("""
                SELECT p.id pid, p.business_id pb, i.business_id ib, i.invoice_id num
                  FROM invoice_payments p JOIN invoices i ON i.id = p.invoice_id
                 WHERE p.business_id <> i.business_id""")]
    rep.add("D2. Cross-tenant payments", rows, """
        A receipt pointing into another business's books. This is a tenant
        isolation failure, not just bad data.
    """)

    # ── E. Duplicate invoice numbers ────────────────────────────────────────
    rows = [f"biz {r['business_id']} '{r['invoice_id']}' x{r['n']}"
            for r in c.execute(
                f"SELECT business_id, invoice_id, COUNT(*) n FROM invoices "
                f"WHERE invoice_id IS NOT NULL{bfilter} "
                f"GROUP BY business_id, invoice_id HAVING COUNT(*) > 1")]
    rep.add("E. Duplicate invoice numbers (F-3)", rows, """
        Blocks the M-3 unique index. Resolve with:
        python scripts/resolve_duplicate_invoice_numbers.py --apply
    """)

    # ── F. Unbalanced journal entries ───────────────────────────────────────
    rows = []
    if _table_exists(c, "journal_entries"):
        rows = [f"entry #{r['id']} biz {r['business_id']} {r['source_type']}#{r['source_id']}: "
                f"Dr {r['dr']} vs Cr {r['cr']}"
                for r in c.execute(f"""
                    SELECT e.id, e.business_id, e.source_type, e.source_id,
                           ROUND(SUM(COALESCE(l.debit,0)),2)  dr,
                           ROUND(SUM(COALESCE(l.credit,0)),2) cr
                      FROM journal_entries e JOIN journal_lines l ON l.entry_id = e.id
                     WHERE 1=1{bfilter.replace('business_id','e.business_id')}
                     GROUP BY e.id HAVING ABS(dr - cr) > 0.01""")]
    rep.add("F. Journal entries that do not foot", rows)

    # ── G. Foreign-key violations (N4) ──────────────────────────────────────
    # Added because this check found 18 real orphaned rows in bizassist.db on
    # 26 Jul 2026 — and found them only because someone happened to run the
    # pragma by hand. SQLite shipped with `PRAGMA foreign_keys = OFF`, so every
    # FK in the models was declared and never enforced on a local install: rows
    # were left pointing at deleted products, invoices, a customer and a user.
    #
    # N4 turned enforcement on, which stops NEW orphans — it does not remove
    # existing ones, because SQLite checks on write, not on read. So they sit
    # there quietly, and the first symptom is an UPDATE that used to work
    # failing in front of an owner. Measuring it on every audit is the point.
    #
    # Not scoped by --business: `foreign_key_check` is a whole-database pragma
    # and has no notion of a tenant. Reported in full deliberately.
    rows = []
    try:
        if c.execute("PRAGMA foreign_keys").fetchone() is not None:
            from collections import Counter
            violations = c.execute("PRAGMA foreign_key_check").fetchall()
            grouped = Counter((v[0], v[2]) for v in violations)
            rows = [f"{child}: {n} row(s) pointing at a missing {parent}"
                    for (child, parent), n in grouped.most_common()]
    except Exception as e:                       # non-SQLite backend, etc.
        rows = [] if "no such pragma" in str(e).lower() else [f"check failed: {e}"]
    rep.add("G. Foreign-key violations (N4)", rows, """
        Orphaned child rows: a line item, stock movement or barcode whose parent
        no longer exists. Accumulated while SQLite was not enforcing foreign
        keys. Quarantine rather than delete — an invoice line item is evidence of
        a sale even when its parent has gone missing.
    """)

    # ── H. Overlapping open shifts (M-11) ───────────────────────────────────
    # `core/shifts/service.py` opens with "ONE OPEN shift per user at a time" and
    # `open_shift` enforces it via `get_open_shift`. Both are keyed on
    # `(business_id, user_id)` — and `user_id` is a column SYNC CAN POPULATE
    # WRONGLY, which is exactly why `register_shifts` is in
    # `sync_map._USER_FK_REPOINT_ENTITIES`.
    #
    # Found in real data (business 7): shift 4 opened FOUR MINUTES into shift 3
    # and was accepted, because with a foreign `user_id` the one-open-shift check
    # was asking about a different operator. Nobody could see it, nobody could
    # close it, and three cash sales totalling Rs 2,485 were rung against it —
    # money that never reached a drawer tally anyone could reconcile.
    #
    # Same shape as M-2 and M-7: each subsystem correct, the defect living
    # between them, and nothing looking broken.
    rows = []
    if _table_exists(c, "register_shifts"):
        for r in c.execute(f"""
                SELECT business_id, user_id, COUNT(*) n,
                       ROUND(SUM(COALESCE(opening_cash,0)),2) floats
                  FROM register_shifts
                 WHERE status = 'OPEN'{bfilter}
                 GROUP BY business_id, user_id HAVING COUNT(*) > 1"""):
            ids = [str(x["id"]) for x in c.execute(
                "SELECT id FROM register_shifts WHERE status='OPEN' "
                "AND business_id = ? AND user_id = ? ORDER BY start_time",
                (r["business_id"], r["user_id"]))]
            rows.append(
                f"biz {r['business_id']} operator {r['user_id']}: {r['n']} OPEN "
                f"shifts (ids {', '.join(ids)}), floats total {r['floats']}")
    rep.add("H. Overlapping open shifts (M-11)", rows, """
        An operator can hold only one open drawer. Extra open shifts may carry
        real receipts that never entered a tally. Close them from the register
        screen — the expected figure is computed from the payment ledger. They are
        NOT closed automatically: a closing cash amount is a COUNT, not a
        calculation, and inventing one fabricates evidence.
    """)

    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "bizassist.db"))
    ap.add_argument("--business", type=int, default=None)
    args = ap.parse_args()

    path = os.path.abspath(args.db)
    c = _connect(path)
    print("=" * 74)
    print(f"MONEY INTEGRITY AUDIT   {path}"
          + (f"   business {args.business}" if args.business else "   all businesses"))
    print("=" * 74)
    rep = audit(c, args.business)
    rep.render()
    print("\n" + "=" * 74)
    print(f"{rep.failures} issue(s) found" if rep.failures else "clean")
    print("=" * 74)
    return 1 if rep.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
