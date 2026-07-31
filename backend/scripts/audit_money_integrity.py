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

G. Foreign-key violations (N4)
   Orphaned children. SQLite shipped with `PRAGMA foreign_keys` OFF, so 18 real
   orphans accumulated before enforcement was turned on.

H. Overlapping open shifts (M-11)
   One operator, two open drawers. Found in production holding ₹2,485 of cash
   sales that reached no tally, because the second shift carried a `user_id`
   from another database and was therefore invisible to the one-open-shift check.

I. Line items that do not foot to their invoice (M-16/M-17)
   Σ(line_total) != total_amount + cash_discount - round_off. A batch script
   inserted 63 spurious line items on 2026-07-17 and another 15 across
   2026-06-29..07-03; header totals and the journal stayed correct, so nothing
   objected — but Brownie Factory's P&L read a ₹-6,715 loss instead of its real
   ₹+4,648 profit, and business 6's COGS was overstated by ₹2,422.57.

J. B2B order lines that do not foot to the order (M-18)
   The same corruption on the two-party table. Both live b2b_orders were
   affected — ₹1,111.10 of phantom line value across 2 of 2 orders. A buyer and
   a seller reading different totals for one order is the failure the shared
   ledger cannot tolerate.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dbcompat import (connect, ensure, resolve_target,  # noqa: E402
                       is_postgres_target, out, use_utf8_stdout)

_INITIAL_PAYMENT = re.compile(r"^Initial payment for invoice (.+)$")

# 1.00 absorbs paise-level float noise on the line-item identity; 0.01 is the
# paid/ledger tolerance. Both are far wider than any float representation error,
# which is WHY this file contains no SQL rounding at all — see _r().
TOL_LINE = 1.00
TOL_PAID = 0.01


def _r(v):
    """Round for DISPLAY and comparison, in Python, never in SQL.

    NO 2-ARGUMENT SQL `ROUND` ANYWHERE IN THIS FILE — finding N4b-PG (§63).
    Every money column here is `Column(Float)` -> `double precision` on Postgres,
    and Postgres has no `round(double precision, integer)`. SQLite's ROUND takes
    `(real, int)` happily, so this file ran green locally for months and would
    have thrown `UndefinedFunction` on its first contact with the cloud — the
    identical failure that took out every migration guard on the 2026-07-26 boot.

    `ROUND(CAST(x AS numeric), 2)` is valid on both, and is deliberately NOT used:
    it trades one untestable assumption for another. Doing the arithmetic in SQL
    and the rounding here means the queries call no dialect-specific function, so
    there is nothing left to be wrong about. (rules 51, 59)
    """
    return round(float(v or 0.0), 2)


def _table_exists(c, name):
    return c.table_exists(name)




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
            out(f"\n[{mark}] {title}  ({len(rows)})")
            if note and rows:
                for line in note.strip().splitlines():
                    out(f"       {line.strip()}")
            for r in rows[:40]:
                out(f"   - {r}")
            if len(rows) > 40:
                out(f"   … and {len(rows) - 40} more")


def audit(c, biz=None):
    # Normalise: `audit` is called directly from tests and consoles with a bare
    # sqlite3 connection, which was valid before the compat layer existed.
    c = ensure(c)
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
        out(f"\n[info] {len(legacy)} zero-value CSV-imported invoice(s) have no "
              f"journal entry, which is correct — they carry no totals to post. "
              f"Excluded from section B.")

    # ── C. Paid state vs ledger ─────────────────────────────────────────────
    under, over, mismatch = [], [], []
    for row in c.execute(f"""
        SELECT i.id, i.business_id, i.invoice_id, i.status,
               COALESCE(i.total_amount, i.amount, 0) AS total,
               COALESCE(i.paid_amount, 0)            AS recorded,
               COALESCE(SUM(p.amount_paid), 0)       AS ledger
          FROM invoices i
          JOIN invoice_payments p ON p.invoice_id = i.id AND p.business_id = i.business_id
         WHERE 1=1{bfilter.replace('business_id', 'i.business_id')}
         GROUP BY i.id, i.business_id, i.invoice_id, i.status,
                  i.total_amount, i.amount, i.paid_amount"""):
        total, recorded, ledger = (_r(row["total"]), _r(row["recorded"]),
                                   _r(row["ledger"]))
        if ledger > total + TOL_PAID:
            over.append(f"biz {row['business_id']} {row['invoice_id']}: total ₹{total}, "
                        f"payment rows sum to ₹{ledger}")
        elif ledger < recorded - TOL_PAID:
            under.append(f"biz {row['business_id']} {row['invoice_id']}: recorded ₹{recorded}, "
                         f"payment rows only ₹{ledger}")
        elif abs(ledger - recorded) > TOL_PAID:
            mismatch.append(f"biz {row['business_id']} {row['invoice_id']}: recorded ₹{recorded}, "
                            f"ledger ₹{ledger} — the M-7 repair will raise this")
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
        # TWO portability fixes here, both silent killers on Postgres:
        #   * the 2-arg ROUND (see _r);
        #   * `HAVING ABS(dr - cr)` referenced the SELECT aliases. SQLite resolves
        #     output aliases in HAVING; Postgres does NOT (they are legal only in
        #     GROUP BY and ORDER BY) and raises `column "dr" does not exist`.
        #     The expression is spelled out instead of aliased.
        rows = [f"entry #{r['id']} biz {r['business_id']} {r['source_type']}#{r['source_id']}: "
                f"Dr {_r(r['dr'])} vs Cr {_r(r['cr'])}"
                for r in c.execute(f"""
                    SELECT e.id, e.business_id, e.source_type, e.source_id,
                           SUM(COALESCE(l.debit,0))  AS dr,
                           SUM(COALESCE(l.credit,0)) AS cr
                      FROM journal_entries e JOIN journal_lines l ON l.entry_id = e.id
                     WHERE 1=1{bfilter.replace('business_id','e.business_id')}
                     GROUP BY e.id, e.business_id, e.source_type, e.source_id
                    HAVING ABS(SUM(COALESCE(l.debit,0))
                               - SUM(COALESCE(l.credit,0))) > {TOL_PAID}""")]
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
    #
    # DIALECT: `foreign_key_check` is a SQLite pragma. On Postgres every FK is
    # validated by the engine on write, so violating rows cannot accumulate the
    # way they did here — EXCEPT behind a `NOT VALID` constraint, which is the
    # one case worth counting and is what _dbcompat reports there. A check that
    # cannot run must say so rather than return an empty list that renders as
    # "ok" (rule 33) — that is why the failure branch below emits a row.
    rows = []
    if c.dialect == "sqlite":
        try:
            from collections import Counter
            violations = c.execute("PRAGMA foreign_key_check").fetchall()
            grouped = Counter((v[0], v[2]) for v in violations)
            rows = [f"{child}: {n} row(s) pointing at a missing {parent}"
                    for (child, parent), n in grouped.most_common()]
        except Exception as e:
            rows = [f"NOT CHECKED — foreign_key_check failed: {e}"]
    else:
        try:
            bad = c.execute(
                "SELECT conrelid::regclass::text AS child, conname "
                "FROM pg_constraint WHERE contype='f' AND NOT convalidated"
            ).fetchall()
            rows = [f"{r['child']}: constraint {r['conname']} is NOT VALID, so "
                    f"it may be holding violating rows" for r in bad]
        except Exception as e:
            rows = [f"NOT CHECKED — NOT VALID constraint scan failed: {e}"]
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
                SELECT business_id, user_id, COUNT(*) AS n,
                       SUM(COALESCE(opening_cash,0)) AS floats
                  FROM register_shifts
                 WHERE status = 'OPEN'{bfilter}
                 GROUP BY business_id, user_id HAVING COUNT(*) > 1"""):
            ids = [str(x["id"]) for x in c.execute(
                "SELECT id FROM register_shifts WHERE status='OPEN' "
                "AND business_id = ? AND user_id = ? ORDER BY start_time",
                (r["business_id"], r["user_id"]))]
            rows.append(
                f"biz {r['business_id']} operator {r['user_id']}: {r['n']} OPEN "
                f"shifts (ids {', '.join(ids)}), floats total {_r(r['floats'])}")
    rep.add("H. Overlapping open shifts (M-11)", rows, """
        An operator can hold only one open drawer. Extra open shifts may carry
        real receipts that never entered a tally. Close them from the register
        screen — the expected figure is computed from the payment ledger. They are
        NOT closed automatically: a closing cash amount is a COUNT, not a
        calculation, and inventing one fabricates evidence.
    """)

    # ── I. Line items that do not foot to their invoice (M-16) ─────────────
    # Added because M-16 was found BY HAND: a batch script on 2026-07-17 inserted
    # 63 spurious `invoice_line_items` rows into businesses 6 and 7, which made
    # Brownie Factory's P&L read a -6,715 loss instead of its real +4,648 profit.
    # Nothing detected it — every subsystem was individually consistent, the
    # journal footed, the invoice totals were untouched; only the LINE ITEMS were
    # inflated, and no check compared them to the document they belong to.
    #
    # Needing to look for something by hand is the signal it belongs in the
    # automated audit (architecture rule 35). This is that check.
    #
    # THE FORMULA MATTERS, and my first version of this check got it wrong —
    # it compared Sigma(line_total) against `total_amount` alone and produced FIVE
    # false positives on business 7. A post-tax cash discount and the round-off
    # live on the HEADER, not on the lines, so the identity is:
    #
    #     Sigma(line_total) == total_amount + cash_discount - round_off
    #
    # Verified against real rows (LCL-OW-0027: 337.65 == 323 + 15 - 0.35).
    # Getting this wrong matters more than it looks: a check that cries wolf is a
    # check people learn to skip, which is precisely how section B's legacy-import
    # noise nearly buried the real M-2 gaps.
    #
    # 1.00 of tolerance then absorbs paise-level rounding only.
    #
    # Zero-value CSV-imported invoices are skipped for the same reason section B
    # skips them: they carry no totals and no lines to compare.
    rows = []
    if _table_exists(c, "invoice_line_items"):
        rows = [
            f"biz {r['business_id']} {r['num']}: header {_r(r['total'])} "
            f"(+disc {_r(r['disc'])} -roff {_r(r['roff'])}) vs lines {_r(r['line_sum'])} "
            f"({r['n']} line(s), delta {_r(r['delta'])})"
            for r in c.execute(f"""
                SELECT i.business_id, i.invoice_id AS num,
                       COALESCE(i.total_amount,0)     AS total,
                       SUM(COALESCE(li.line_total,0)) AS line_sum,
                       COALESCE(i.cash_discount,0)    AS disc,
                       COALESCE(i.round_off,0)        AS roff,
                       SUM(COALESCE(li.line_total,0))
                             - (COALESCE(i.total_amount,0)
                                + COALESCE(i.cash_discount,0)
                                - COALESCE(i.round_off,0))  AS delta,
                       COUNT(li.id) AS n
                  FROM invoices i
                  JOIN invoice_line_items li ON li.invoice_id = i.id
                 WHERE COALESCE(i.total_amount,0) <> 0{bfilter.replace('business_id','i.business_id')}
                 GROUP BY i.id, i.business_id, i.invoice_id, i.total_amount,
                          i.cash_discount, i.round_off
                HAVING ABS(SUM(COALESCE(li.line_total,0))
                           - (COALESCE(i.total_amount,0)
                              + COALESCE(i.cash_discount,0)
                              - COALESCE(i.round_off,0))) > {TOL_LINE}
                 ORDER BY ABS(SUM(COALESCE(li.line_total,0))
                              - (COALESCE(i.total_amount,0)
                                 + COALESCE(i.cash_discount,0)
                                 - COALESCE(i.round_off,0))) DESC""")]
    rep.add("I. Line items that do not foot to their invoice (M-16)", rows, """
        The invoice header and the rows it is made of disagree. This is how the
        M-16 duplicate-line-item corruption looked: totals and journal both
        correct, line items inflated, the P&L wrong by the difference. A positive
        delta means MORE line value than the customer was billed (duplicates); a
        negative delta means lines are missing.
        Investigate before repairing — the header may be right and the lines
        wrong, or the reverse, and only the printed/filed copy settles it.
    """)

    # ── J. B2B order lines that do not foot to their order (M-18) ───────────
    # The M-16/M-17 corruption, found on the TWO-PARTY table. Measured on real
    # data: BOTH live b2b_orders had inflated line items — Rs1,111.10 of phantom
    # line value across 2 of 2 orders.
    #
    # This matters more than the single-tenant case, because a B2B order is a
    # record two businesses quote to each other. A buyer reading a total the
    # seller does not recognise is the failure mode the whole shared-ledger
    # thesis depends on not happening.
    #
    # b2b_orders carries no cash_discount/round_off column, so the target is the
    # plain total_amount.
    rows = []
    if _table_exists(c, "b2b_order_line_items"):
        rows = [
            f"order {r['order_number']} (seller {r['seller_business_id']} -> "
            f"buyer {r['buyer_business_id']}): header {_r(r['total'])} vs lines "
            f"{_r(r['line_sum'])} ({r['n']} line(s), delta {_r(r['delta'])})"
            for r in c.execute(f"""
                SELECT o.order_number, o.seller_business_id, o.buyer_business_id,
                       COALESCE(o.total_amount,0)     AS total,
                       SUM(COALESCE(li.line_total,0)) AS line_sum,
                       SUM(COALESCE(li.line_total,0))
                             - COALESCE(o.total_amount,0) AS delta,
                       COUNT(li.id) AS n
                  FROM b2b_orders o
                  JOIN b2b_order_line_items li ON li.order_id = o.id
                 WHERE COALESCE(o.total_amount,0) <> 0
                 GROUP BY o.id, o.order_number, o.seller_business_id,
                          o.buyer_business_id, o.total_amount
                HAVING ABS(SUM(COALESCE(li.line_total,0))
                           - COALESCE(o.total_amount,0)) > {TOL_LINE}
                 ORDER BY ABS(SUM(COALESCE(li.line_total,0))
                              - COALESCE(o.total_amount,0)) DESC""")]
    rep.add("J. B2B order lines that do not foot to the order (M-18)", rows, """
        A B2B order is a record TWO businesses quote to each other, so a header
        and lines that disagree means the buyer and the seller can read different
        numbers for the same order. Same shape as M-16/M-17 on the shared table.
        Repair with: python scripts/repair_line_items_by_invariant.py --apply
        (it handles b2b_orders as well as invoices).
    """)

    return rep


def main():
    use_utf8_stdout()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None,
                    help="SQLite file path OR a postgresql:// URL. Defaults to "
                         "$BIZASSIST_AUDIT_DATABASE_URL, then backend/bizassist.db.")
    ap.add_argument("--business", type=int, default=None)
    args = ap.parse_args()

    target = resolve_target(args.db)
    # READ-ONLY, enforced by the engine — see _dbcompat.connect. This audit is
    # now pointed at production databases, so "it only runs SELECTs" being true
    # today is not the same as it being unable to write.
    c = connect(target, readonly=True)
    out("=" * 74)
    out(f"MONEY INTEGRITY AUDIT   {c.label}"
          + (f"   business {args.business}" if args.business else "   all businesses"))
    out(f"engine: {c.dialect}   mode: read-only")
    out("=" * 74)
    rep = audit(c, args.business)
    rep.render()

    integ = c.integrity_report()
    out(f"\n[info] integrity: {integ['integrity']}   "
          f"fk: {integ['fk_violations']} — {integ['note']}")

    out("\n" + "=" * 74)
    out(f"{rep.failures} issue(s) found" if rep.failures else "clean")
    out("=" * 74)
    c.close()
    return 1 if rep.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
