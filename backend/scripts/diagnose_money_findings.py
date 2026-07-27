"""
scripts/diagnose_money_findings.py — WHY, not just WHAT. Read-only.
===================================================================
`audit_money_integrity.py` says which documents are wrong.  This says what
happened to them, so a repair is chosen on evidence instead of on a story.

    python scripts/diagnose_money_findings.py
    python scripts/diagnose_money_findings.py --db postgresql://...

Writes nothing, and the connection is put into engine-enforced read-only mode.

THE QUESTION THIS EXISTS TO ANSWER
----------------------------------
The 2026-07-27 cloud audit found 63 documents with no journal entry and 31 with
inflated line items.  Those two counts have two very different explanations and
they need opposite responses:

  * **Historical.**  A defect that has since been fixed in code, whose damaged
    rows were repaired LOCALLY and never on the cloud.  The response is a
    one-time repair.
  * **Ongoing.**  A defect still writing bad rows today.  Repairing first would
    destroy the evidence and the corruption would simply come back.

The distinguishing evidence is TIME, and it is cheap to collect:

  * If every affected row was written in one burst, weeks after the documents it
    belongs to, that is a batch event — the M-16/M-17/M-18 signature exactly.
  * If affected rows are still appearing at today's date, the writer is live and
    nothing should be repaired until it is found.

REPORTED, NEVER ASSUMED
-----------------------
Every number here is measured.  Where a column this needs does not exist on a
given schema the section says NOT MEASURED rather than printing a zero — a
missing measurement and a measurement of zero are different facts (rule 63).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dbcompat import (connect, resolve_target, out,  # noqa: E402
                       use_utf8_stdout)

TOL = 1.00

SPECS = [
    ("invoices", "invoice_line_items", "invoice_id", "invoice_id",
     "COALESCE(p.total_amount,0) + COALESCE(p.cash_discount,0) - COALESCE(p.round_off,0)"),
    ("b2b_orders", "b2b_order_line_items", "order_id", "order_number",
     "COALESCE(p.total_amount,0)"),
]


def _has_column(c, table, column) -> bool:
    if c.dialect == "sqlite":
        return any(r["name"] == column
                   for r in c.execute(f"PRAGMA table_info({table})"))
    return c.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = ? AND column_name = ?", (table, column)
    ).fetchone() is not None


def biz_labels(c) -> dict:
    """{business_id: 'BA-XXXX'} — the identifier that means the same thing in
    both databases.

    INTEGER business ids ARE NOT COMPARABLE ACROSS ENVIRONMENTS. The cloud and
    a local install allocate their own `users.id`, so "business 42" on the cloud
    is not "business 42" locally; the stable key is `users.public_id`, the BizID.
    Reporting the integer alone invites exactly the wrong cross-reference — and
    the same trap is visible in the B2B orders, which read seller 6 -> buyer 87
    locally and seller 7 -> buyer 19 on the cloud for what is the same order.

    (Note that the biz-7 line-item match in the strategic review was established
    on the MONEY — six header targets agreeing to the paisa — not on the ids,
    which is why that identification still holds.)
    """
    if not c.table_exists("users"):
        return {}
    try:
        return {int(r["id"]): (r["public_id"] or "")
                for r in c.execute("SELECT id, public_id FROM users")}
    except Exception:
        return {}


def _rule(title):
    out("\n" + "=" * 74)
    out(title)
    out("=" * 74)


def offenders(c, parent, child, fk, label, target):
    """Parent rows whose children over- or under-shoot the header."""
    return c.execute(f"""
        SELECT p.id, p.{label} AS doc_no, p.business_id AS biz,
               ({target}) AS target,
               SUM(COALESCE(ch.line_total,0)) AS line_sum,
               COUNT(ch.id) AS n
          FROM {parent} p JOIN {child} ch ON ch.{fk} = p.id
         WHERE COALESCE(p.total_amount,0) <> 0
         GROUP BY p.id
        HAVING ABS(SUM(COALESCE(ch.line_total,0)) - ({target})) > {TOL}
         ORDER BY p.id""").fetchall()


def _split_surplus(c, parent, child, fk, offender_rows):
    """-> (surplus_ids, kept_ids, unresolved_count) using the REPAIR's own rule.

    Walk each document's line items in id order, accumulating `line_total`, and
    find the PREFIX that reconciles to the header. Rows after that prefix are
    the intruders. Identical to `repair_line_items_by_invariant._find_in`, and
    deliberately so: a diagnosis that identified a different set of rows than the
    repair would act on would be worse than no diagnosis.

    A document with no reconciling prefix is counted, never guessed at.
    """
    surplus, kept, unresolved = [], [], 0
    for r in offender_rows:
        target = round(float(r["target"] or 0.0), 2)
        lines = c.execute(
            f"SELECT id, line_total FROM {child} WHERE {fk} = ? ORDER BY id",
            (r["id"],)).fetchall()
        running, cut = 0.0, None
        for idx, ln in enumerate(lines):
            running = round(running + float(ln["line_total"] or 0.0), 2)
            if abs(running - target) <= TOL:
                cut = idx + 1
                break
        if cut is None or cut == len(lines):
            unresolved += 1
            continue
        kept += [int(x["id"]) for x in lines[:cut]]
        surplus += [int(x["id"]) for x in lines[cut:]]
    return surplus, kept, unresolved


def diagnose_line_items(c):
    """WHEN were the surplus rows written, relative to the document?"""
    _rule("1. PHANTOM LINE ITEMS - when were they written?")
    for parent, child, fk, label, target in SPECS:
        if not (c.table_exists(parent) and c.table_exists(child)):
            out(f"\n  {parent}: NOT MEASURED - table absent")
            continue
        if parent == "b2b_orders":
            # b2b_orders has no business_id; it has seller/buyer.
            rows = c.execute(f"""
                SELECT p.id, p.{label} AS doc_no, p.seller_business_id AS biz,
                       ({target}) AS target,
                       SUM(COALESCE(ch.line_total,0)) AS line_sum,
                       COUNT(ch.id) AS n
                  FROM {parent} p JOIN {child} ch ON ch.{fk} = p.id
                 WHERE COALESCE(p.total_amount,0) <> 0
                 GROUP BY p.id
                HAVING ABS(SUM(COALESCE(ch.line_total,0)) - ({target})) > {TOL}
                 ORDER BY p.id""").fetchall()
        else:
            rows = offenders(c, parent, child, fk, label, target)
        out(f"\n  {parent}: {len(rows)} document(s) affected")
        if not rows:
            continue

        if not _has_column(c, child, "created_at"):
            out("      created_at NOT MEASURED - column absent on this schema")
            continue

        ids = [str(int(r["id"])) for r in rows]
        idlist = ",".join(ids)

        # ── SURPLUS rows only ────────────────────────────────────────────────
        # The first version of this bucketed EVERY row on an affected document,
        # which conflates the genuine lines with the intruders and makes the
        # document's own creation days look like part of the corruption. The
        # question is "when were the SURPLUS rows written", so the surplus rows
        # have to be identified first — by the same prefix rule the repair uses,
        # so the diagnosis and the repair can never disagree about which rows
        # they mean.
        surplus_ids, kept_ids, unresolved_docs = _split_surplus(
            c, parent, child, fk, rows)

        out(f"      rows: {len(kept_ids) + len(surplus_ids)} total on these "
            f"documents -> {len(kept_ids)} reconcile to the header, "
            f"{len(surplus_ids)} are SURPLUS")
        if unresolved_docs:
            out(f"      {unresolved_docs} document(s) have NO reconciling prefix"
                f" - not attributable, and the repair would refuse them")

        if surplus_ids:
            buckets = c.execute(f"""
                SELECT SUBSTR(CAST(created_at AS CHAR(30)), 1, 10) AS day,
                       COUNT(*) AS n
                  FROM {child}
                 WHERE id IN ({','.join(str(i) for i in surplus_ids)})
                 GROUP BY SUBSTR(CAST(created_at AS CHAR(30)), 1, 10)
                 ORDER BY day""").fetchall()
            out("      SURPLUS rows by the day they were WRITTEN:")
            for b in buckets:
                out(f"        {b['day'] or 'NULL':<12} {b['n']:>6} row(s)")
            out("      (a few dominant days = batch events, already over;"
                " a tail reaching today = still running)")

        if kept_ids:
            kb = c.execute(f"""
                SELECT MIN(SUBSTR(CAST(created_at AS CHAR(30)), 1, 10)) AS lo,
                       MAX(SUBSTR(CAST(created_at AS CHAR(30)), 1, 10)) AS hi
                  FROM {child}
                 WHERE id IN ({','.join(str(i) for i in kept_ids)})""").fetchone()
            out(f"      for contrast, the GENUINE rows span {kb['lo']} .. {kb['hi']}")

        # And the documents' own dates, for contrast.
        if _has_column(c, parent, "created_at"):
            span = c.execute(f"""
                SELECT MIN(SUBSTR(CAST(created_at AS CHAR(30)), 1, 10)) AS lo,
                       MAX(SUBSTR(CAST(created_at AS CHAR(30)), 1, 10)) AS hi
                  FROM {parent} WHERE id IN ({idlist})""").fetchone()
            out(f"      the DOCUMENTS themselves were created "
                f"{span['lo']} .. {span['hi']}")

        # Duplicate-apply test: are the surplus rows distinguishable at all?
        if _has_column(c, child, "uid"):
            u = c.execute(f"""
                SELECT COUNT(*) AS total, COUNT(DISTINCT uid) AS distinct_uids,
                       SUM(CASE WHEN uid IS NULL THEN 1 ELSE 0 END) AS nulls
                  FROM {child} WHERE {fk} IN ({idlist})""").fetchone()
            out(f"      uids: {u['total']} row(s), {u['distinct_uids']} distinct,"
                f" {u['nulls']} NULL")
            out("      (distinct uids disprove a re-applied sync batch;"
                " repeats or NULLs support one)")


def diagnose_missing_journals(c, since="2026-07-27"):
    _rule("2. DOCUMENTS WITH NO JOURNAL ENTRY - when were they created?")
    if not (c.table_exists("journal_entries") and c.table_exists("invoices")):
        out("  NOT MEASURED - journal_entries or invoices absent")
        return
    if not _has_column(c, "invoices", "created_at"):
        out("  created_at NOT MEASURED - column absent")
        return
    rows = c.execute("""
        SELECT SUBSTR(CAST(i.created_at AS CHAR(30)), 1, 10) AS day,
               COUNT(*) AS n
          FROM invoices i
         WHERE COALESCE(i.total_amount,0) <> 0
           AND NOT EXISTS (SELECT 1 FROM journal_entries j
                            WHERE j.business_id = i.business_id
                              AND j.source_id = i.id
                              AND j.source_type = CASE
                                    WHEN COALESCE(i.invoice_type,'') = 'credit_note'
                                    THEN 'credit_note' ELSE 'sale' END)
         GROUP BY SUBSTR(CAST(i.created_at AS CHAR(30)), 1, 10)
         ORDER BY day""").fetchall()
    if not rows:
        out("  none")
        return
    out("  unposted documents by the day they were CREATED:")
    for r in rows:
        out(f"    {r['day'] or 'NULL':<12} {r['n']:>6} document(s)")
    # Judge the tail against WHEN THE FIX SHIPPED, not against "today".
    #
    # This line used to read "a tail reaching today means documents are STILL
    # arriving unposted" — and I read it exactly that way and called a live
    # defect that was not one. The newest unposted document here is 2026-07-26
    # 18:57; `repost.py` and `apply_hooks.py` were created at 2026-07-27 00:09,
    # so the push path posted no journal at all until AFTER every one of these
    # rows was written. A date near the present is only evidence of a live defect
    # if the fix predates it. Section 6 is the test that settles it.
    newest = max((r["day"] or "") for r in rows)
    fix_day = str(since)[:10]
    if newest > fix_day:
        out(f"\n  The newest is {newest}, AFTER the fix shipped ({fix_day}).")
        out("  That is evidence of a LIVE defect - see section 6.")
    else:
        out(f"\n  The newest is {newest}; the journal-posting fix shipped "
            f"{fix_day}.")
        out("  So every one of these predates the fix and is BACKLOG, not proof")
        out("  of a live defect. Section 6 tests whether the fix actually works.")

    # ── The 20 most recent, named ────────────────────────────────────────────
    # A histogram says a tail exists; it does not say WHAT is in the tail. These
    # are the rows that decide whether this is history or a live writer, so they
    # are printed individually with the evidence of where they came from.
    has_uid = _has_column(c, "invoices", "uid")
    uidcol = "i.uid" if has_uid else "NULL"
    recent = c.execute(f"""
        SELECT i.id, i.business_id, i.invoice_id AS doc_no, i.total_amount,
               i.invoice_type, {uidcol} AS uid,
               SUBSTR(CAST(i.created_at AS CHAR(30)), 1, 19) AS created
          FROM invoices i
         WHERE COALESCE(i.total_amount,0) <> 0
           AND NOT EXISTS (SELECT 1 FROM journal_entries j
                            WHERE j.business_id = i.business_id
                              AND j.source_id = i.id
                              AND j.source_type = CASE
                                    WHEN COALESCE(i.invoice_type,'') = 'credit_note'
                                    THEN 'credit_note' ELSE 'sale' END)
         ORDER BY i.created_at DESC""").fetchall()[:20]
    labels = biz_labels(c)
    out("\n  The 20 most recent unposted documents:")
    out(f"    {'created':<21}{'BizID':<13}{'document':<18}{'total':>11}  origin")
    for r in recent:
        origin = ("synced (has uid)" if r["uid"] else
                  "local-only (no uid)" if has_uid else "uid NOT MEASURED")
        biz = labels.get(int(r["business_id"]), f"#{r['business_id']}")
        out(f"    {str(r['created']):<21}{biz:<13}"
            f"{str(r['doc_no']):<18}{float(r['total_amount'] or 0):>11.2f}  {origin}")
    out("\n  A `uid` means the row came through sync; its absence means it was")
    out("  written directly on this database. That distinguishes a sync-apply")
    out("  defect from a billing-command defect, and they need different fixes.")

    # Documents whose number pattern suggests they are not sales at all. Worth
    # separating BEFORE anyone runs a journal backfill over them: posting a sale
    # entry for an opening balance would invent revenue that never happened.
    odd = [r for r in recent if str(r["doc_no"] or "").upper().startswith("OPEN")]
    if odd:
        out(f"\n  NOTE: {len(odd)} of these are numbered OPEN-*. If those are")
        out("  opening-balance documents rather than sales, a journal backfill")
        out("  would post REVENUE that never happened. Confirm what they are")
        out("  before running any backfill.")


def diagnose_overlap(c):
    """Do the two findings share documents? If so, one event explains both."""
    _rule("3. DO THE TWO FINDINGS OVERLAP?")
    if not (c.table_exists("journal_entries") and c.table_exists("invoice_line_items")):
        out("  NOT MEASURED")
        return
    target = ("COALESCE(p.total_amount,0) + COALESCE(p.cash_discount,0) "
              "- COALESCE(p.round_off,0)")
    bad_lines = {int(r["id"])
                 for r in offenders(c, "invoices", "invoice_line_items",
                                    "invoice_id", "invoice_id", target)}
    no_journal = {int(r["id"]) for r in c.execute("""
        SELECT i.id FROM invoices i
         WHERE COALESCE(i.total_amount,0) <> 0
           AND NOT EXISTS (SELECT 1 FROM journal_entries j
                            WHERE j.business_id = i.business_id
                              AND j.source_id = i.id
                              AND j.source_type = CASE
                                    WHEN COALESCE(i.invoice_type,'') = 'credit_note'
                                    THEN 'credit_note' ELSE 'sale' END)""")}
    both = bad_lines & no_journal
    out(f"  inflated line items      : {len(bad_lines)}")
    out(f"  missing journal entry    : {len(no_journal)}")
    out(f"  BOTH on the same document: {len(both)}")
    if not bad_lines and not no_journal:
        out("\n  Nothing to compare - neither finding is present here.")
    elif both and len(both) >= min(len(bad_lines), len(no_journal)) * 0.5:
        out("\n  A large overlap means ONE event produced both symptoms, and the")
        out("  two findings should not be repaired as if they were independent.")
    elif not both:
        out("\n  No overlap: two independent defects, repairable separately.")
    else:
        out(f"\n  Partial overlap ({len(both)}). Some documents were hit by both;"
            f" most were not.")


def diagnose_by_business(c):
    _rule("4. WHICH BUSINESSES, AND HOW MUCH")
    labels = biz_labels(c)
    target = ("COALESCE(p.total_amount,0) + COALESCE(p.cash_discount,0) "
              "- COALESCE(p.round_off,0)")
    rows = offenders(c, "invoices", "invoice_line_items",
                     "invoice_id", "invoice_id", target)
    per = {}
    for r in rows:
        delta = float(r["line_sum"] or 0) - float(r["target"] or 0)
        b = per.setdefault(r["biz"], {"n": 0, "amt": 0.0})
        b["n"] += 1
        b["amt"] += delta
    out(f"  {'biz id':<9}{'BizID':<14}{'documents':>11}{'surplus line value':>22}")
    for biz, v in sorted(per.items(), key=lambda kv: -kv[1]["amt"]):
        out(f"  {str(biz):<9}{labels.get(int(biz), '?'):<14}"
            f"{v['n']:>11}{round(v['amt'], 2):>22}")
    if per:
        out(f"  {'TOTAL':<23}{sum(v['n'] for v in per.values()):>11}"
            f"{round(sum(v['amt'] for v in per.values()), 2):>22}")
    out("\n  Quote the BizID, not the integer: cloud and local allocate their own")
    out("  users.id, so the same business has different numbers in each.")
    out("\n  COGS is line_items x cost_price, so each surplus figure is roughly")
    out("  how much that business's profit is understated by.")


def diagnose_journal_coverage(c):
    """Per business: how many documents ARE posted, versus not.

    This is what separates the two explanations for the missing journals:

      * a business with SOME posted and SOME unposted documents means the
        posting path runs and fails intermittently — look at what those rows
        have in common;
      * a business with NONE posted means the path never runs for it at all,
        which is a different defect and a different fix.

    Cheap, decisive, and it cannot be inferred from the counts already printed.
    """
    _rule("5. JOURNAL COVERAGE PER BUSINESS - selective or total?")
    if not (c.table_exists("journal_entries") and c.table_exists("invoices")):
        out("  NOT MEASURED")
        return
    labels = biz_labels(c)
    rows = c.execute("""
        SELECT i.business_id AS biz,
               COUNT(*) AS total,
               SUM(CASE WHEN EXISTS (
                     SELECT 1 FROM journal_entries j
                      WHERE j.business_id = i.business_id
                        AND j.source_id = i.id
                        AND j.source_type = CASE
                              WHEN COALESCE(i.invoice_type,'') = 'credit_note'
                              THEN 'credit_note' ELSE 'sale' END)
                   THEN 1 ELSE 0 END) AS posted
          FROM invoices i
         WHERE COALESCE(i.total_amount,0) <> 0
         GROUP BY i.business_id
         ORDER BY i.business_id""").fetchall()
    out(f"  {'biz id':<9}{'BizID':<14}{'documents':>10}{'posted':>9}"
        f"{'unposted':>10}  verdict")
    for r in rows:
        total, posted = int(r["total"]), int(r["posted"] or 0)
        missing = total - posted
        if missing == 0:
            verdict = "all posted"
        elif posted == 0:
            verdict = "NONE posted - path never runs here"
        else:
            verdict = "PARTIAL - posting runs but fails sometimes"
        out(f"  {str(r['biz']):<9}{labels.get(int(r['biz']), '?'):<14}"
            f"{total:>10}{posted:>9}{missing:>10}  {verdict}")


def _newest_regardless(c, labels, limit=8):
    """The most recently INSERTED documents, by id — no date arithmetic.

    `id` is monotonic per database, so the highest ids are always the last rows
    written HERE, whatever their `created_at` says. That makes this immune to
    the two things that break a date filter: a NULL timestamp, and a timestamp
    that was copied from the source database by sync rather than stamped on
    arrival.
    """
    rows = c.execute("""
        SELECT i.id, i.business_id, i.invoice_id AS doc_no, i.total_amount,
               SUBSTR(CAST(i.created_at AS CHAR(30)), 1, 19) AS created,
               CASE WHEN EXISTS (
                     SELECT 1 FROM journal_entries j
                      WHERE j.business_id = i.business_id
                        AND j.source_id = i.id
                        AND j.source_type = CASE
                              WHEN COALESCE(i.invoice_type,'') = 'credit_note'
                              THEN 'credit_note' ELSE 'sale' END)
                    THEN 1 ELSE 0 END AS posted
          FROM invoices i
         WHERE COALESCE(i.total_amount,0) <> 0
         ORDER BY i.id DESC""").fetchall()[:limit]
    out(f"\n  The {len(rows)} most recently INSERTED documents (highest id,"
        f" ignoring dates):")
    out(f"    {'id':>7}  {'created':<21}{'BizID':<13}{'document':<18}"
        f"{'total':>10}  journal")
    for r in rows:
        out(f"    {int(r['id']):>7}  {str(r['created']):<21}"
            f"{labels.get(int(r['business_id']), '?'):<13}"
            f"{str(r['doc_no']):<18}{float(r['total_amount'] or 0):>10.2f}  "
            f"{'posted' if int(r['posted']) else 'MISSING'}")


def diagnose_since_fix(c, since: str):
    """Has anything arrived SINCE the journal-posting fix, and did it post?

    WHY THIS SECTION EXISTS — an error of mine, recorded because the reasoning
    matters more than the conclusion.

    Section 2 shows unposted documents with a tail reaching 2026-07-26, and I
    called that a LIVE defect. It is not. `core/accounting/repost.py` and
    `core/sync/apply_hooks.py` were CREATED in commit d34de0a at 2026-07-27
    00:09 IST — before that, the sync push path posted no journal at all. The
    newest unposted document predates the fix by about five hours. Every one of
    the 54 is history.

    "The tail reaches yesterday" and "the defect is live" are not the same
    claim, and I asserted the second from the first without checking when the
    fix shipped. That is the same mistake as reading a clean scan as proof of
    health (rule 33), in the opposite direction.

    What is STILL unproven is whether the fix WORKS here: an absence of unposted
    documents after the deploy is equally explained by nothing having been pushed
    since. Only a document that arrived AFTER the deploy can distinguish those,
    which is what this measures.
    """
    _rule(f"6. ANYTHING ARRIVED SINCE THE FIX DEPLOYED ({since})?")
    if not (c.table_exists("journal_entries") and c.table_exists("invoices")):
        out("  NOT MEASURED")
        return
    labels = biz_labels(c)
    rows = c.execute("""
        SELECT i.id, i.business_id, i.invoice_id AS doc_no, i.total_amount,
               SUBSTR(CAST(i.created_at AS CHAR(30)), 1, 19) AS created,
               CASE WHEN EXISTS (
                     SELECT 1 FROM journal_entries j
                      WHERE j.business_id = i.business_id
                        AND j.source_id = i.id
                        AND j.source_type = CASE
                              WHEN COALESCE(i.invoice_type,'') = 'credit_note'
                              THEN 'credit_note' ELSE 'sale' END)
                    THEN 1 ELSE 0 END AS posted
          FROM invoices i
         WHERE COALESCE(i.total_amount,0) <> 0
           AND CAST(i.created_at AS CHAR(30)) > ?
         ORDER BY i.created_at""", (since,)).fetchall()
    if not rows:
        out("  Nothing matched a created_at LATER than the deploy.")
        # RULE 33, applied to this section. "Nothing found" on its own cannot
        # distinguish "the sale never synced" from "the sale is here but my date
        # comparison missed it" — e.g. a NULL created_at, or a timestamp carried
        # over from the local database rather than stamped on arrival. So show
        # what IS newest, by id, and let the reader see which it is.
        _newest_regardless(c, labels)
        out("\n  If a sale you just rang is NOT in the list above, it has not")
        out("  reached this database yet - check the local backend's push.")
        out("  If it IS there but older than the deploy time, then created_at")
        out("  carries the LOCAL creation time and this comparison is the wrong")
        out("  test; judge by the journal column instead.")
        return
    ok = sum(1 for r in rows if int(r["posted"]))
    out(f"  {len(rows)} document(s) arrived since; {ok} posted, "
        f"{len(rows) - ok} NOT posted")
    out(f"\n    {'created':<21}{'BizID':<13}{'document':<18}{'total':>11}  journal")
    for r in rows[:20]:
        out(f"    {str(r['created']):<21}"
            f"{labels.get(int(r['business_id']), '?'):<13}"
            f"{str(r['doc_no']):<18}{float(r['total_amount'] or 0):>11.2f}  "
            f"{'posted' if int(r['posted']) else 'MISSING'}")
    if ok == len(rows):
        out("\n  Every document since the deploy is posted: the fix WORKS here,")
        out("  and the 54 unposted documents are a closed backlog.")
    else:
        out("\n  Documents are STILL arriving unposted AFTER the fix. The defect")
        out("  is live and no backfill should run until it is found.")


def find_document(c, needle: str):
    """Locate a document by number or uid with NO filters whatsoever.

    Every other query in this file carries `COALESCE(total_amount,0) <> 0`,
    because a zero-value CSV import is not a money document. That filter makes
    a row which arrived with a ZERO OR NULL TOTAL invisible — and "the row is
    not in my results" then gets read as "the row is not in the database".

    Which is exactly the trap this session walked into: a pushed sale reported
    `Successfully pushed 5 changes`, and section 6 did not list it. Those are
    different statements, and only an unfiltered lookup can tell them apart
    (rule 33, in my own tool).
    """
    _rule(f"FIND: any document matching {needle!r} - NO filters applied")
    labels = biz_labels(c)
    like = f"%{needle}%"
    cols = "id, business_id, invoice_id, invoice_type, total_amount, amount, " \
           "paid_amount, status, created_at"
    has_uid = _has_column(c, "invoices", "uid")
    where = "invoice_id LIKE ?" + (" OR uid LIKE ?" if has_uid else "")
    params = (like, like) if has_uid else (like,)
    rows = c.execute(f"SELECT {cols}{', uid' if has_uid else ''} FROM invoices "
                     f"WHERE {where} ORDER BY id", params).fetchall()
    if not rows:
        out(f"  NOT PRESENT. No invoices row matches {needle!r} by number"
            + (" or uid." if has_uid else "."))
        out("  This is an unfiltered search of the whole table, so the document")
        out("  genuinely is not in this database.")
        return
    for r in rows:
        biz = labels.get(int(r["business_id"] or 0), f"#{r['business_id']}")
        out(f"\n  FOUND id={r['id']}  biz={r['business_id']} ({biz})")
        out(f"    invoice_id   : {r['invoice_id']}")
        out(f"    invoice_type : {r['invoice_type']}")
        out(f"    total_amount : {r['total_amount']!r}   amount: {r['amount']!r}")
        out(f"    paid_amount  : {r['paid_amount']!r}   status: {r['status']!r}")
        out(f"    created_at   : {r['created_at']}")
        if has_uid:
            out(f"    uid          : {r['uid']}")
        if not (r["total_amount"] or 0):
            out("    ^^ TOTAL IS ZERO OR NULL - which is why every other section")
            out("       of this report, and the audit, cannot see it.")
        n = c.scalar("SELECT COUNT(*) FROM invoice_line_items WHERE invoice_id = ?",
                     (r["id"],), default=0)
        s = c.scalar("SELECT SUM(COALESCE(line_total,0)) FROM invoice_line_items "
                     "WHERE invoice_id = ?", (r["id"],), default=0)
        out(f"    line items   : {n} row(s) totalling {round(float(s or 0), 2)}")
        j = c.scalar("SELECT COUNT(*) FROM journal_entries WHERE business_id = ? "
                     "AND source_id = ? AND source_type IN ('sale','credit_note')",
                     (r["business_id"], r["id"]), default=0)
        out(f"    journal      : {'posted' if j else 'MISSING'}")


def main() -> int:
    use_utf8_stdout()
    ap = argparse.ArgumentParser(description="Explain the money audit's findings.")
    ap.add_argument("--db", default=None)
    ap.add_argument("--find", default=None,
                    help="look up ONE document by number or uid with no "
                         "filters, and print everything about it. Use this when "
                         "a row you expect is missing from the other sections.")
    ap.add_argument("--since", default="2026-07-27 13:56:33",
                    help="when the journal-posting fix was deployed "
                         "(commit d34de0a, HF boot 2026-07-27 13:56). "
                         "Documents newer than this test the FIX; older "
                         "ones are backlog.")
    args = ap.parse_args()

    c = connect(resolve_target(args.db), readonly=True)
    out("=" * 74)
    out(f"MONEY FINDINGS DIAGNOSIS   {c.label}")
    out(f"engine: {c.dialect}   mode: read-only   WRITES NOTHING")
    out("=" * 74)
    try:
        if args.find:
            find_document(c, args.find)
            c.close()
            out("\n" + "=" * 74)
            out("Nothing was changed.")
            out("=" * 74)
            return 0
        diagnose_line_items(c)
        diagnose_missing_journals(c, args.since)
        diagnose_overlap(c)
        diagnose_by_business(c)
        diagnose_journal_coverage(c)
        diagnose_since_fix(c, args.since)
    finally:
        c.close()
    out("\n" + "=" * 74)
    out("Nothing was changed.")
    out("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
