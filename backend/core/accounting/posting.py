"""
core/accounting/posting.py — POSTED double-entry journal.
=========================================================
Writes a balanced `JournalEntry` (+ `JournalLine`s) per source document AT
TRANSACTION TIME. Composes WITHIN the caller's transaction and NEVER commits —
the command owns the commit, exactly like `SL.record_movement`. Idempotent per
source document, and every entry is validated to foot (Σ Dr == Σ Cr) before it
is written, so the posted journal is a true, tamper-evident audit trail.

Account names MUST match the derived engine in `core/api/reports.py` so the
posted journal reconciles with the reconstructed one.
"""
import hashlib
import json
import logging
from datetime import datetime

from core.models import JournalEntry, JournalLine

logger = logging.getLogger("bizassist.accounting")

GENESIS_HASH = "GENESIS"


def _chain_hash(*, business_id, entry_date, source_type, source_id,
                ref_no, narration, clean, prev_hash) -> str:
    """Deterministic SHA-256 over an entry's content + the previous hash.

    Money amounts are formatted to fixed 2dp so float noise can't shift the hash.
    Lines are hashed in insertion order (verify reads them back in id order).
    """
    payload = json.dumps({
        "business_id": business_id,
        "entry_date": entry_date,
        "source_type": source_type,
        "source_id": source_id,
        "ref_no": ref_no or "",
        "narration": narration or "",
        "lines": [[a, f"{dr:.2f}", f"{cr:.2f}"] for (a, dr, cr) in clean],
        "prev_hash": prev_hash,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# Canonical chart-of-accounts names (keep in sync with reports._build_journal_entries).
ACC_CASH = "Cash & Bank"
ACC_AR = "Accounts Receivable"
ACC_AP = "Accounts Payable"
ACC_SALES = "Sales"
ACC_PURCHASES = "Purchases"
ACC_GST_OUT = "GST Payable"
ACC_GST_IN = "GST Input Credit"
ACC_DISCOUNT = "Discount Allowed"   # post-tax cash discount given to customers (R4)


def _r2(x) -> float:
    return round(float(x or 0.0), 2)


def _gst_total(doc) -> float:
    return _r2((doc.cgst_total or 0.0) + (doc.sgst_total or 0.0)
               + (doc.igst_total or 0.0) + (doc.cess_total or 0.0))


def post_entry(db, *, business_id, entry_date, source_type, source_id,
               ref_no, narration, lines):
    """Idempotently post ONE balanced journal entry. Composes WITHOUT committing.

    `lines`: iterable of (account, debit, credit). Zero-only lines are dropped.
    Idempotent on (business_id, source_type, source_id). Raises ValueError if the
    entry does not foot (a guard that a buggy caller can never write bad books).
    """
    existing = db.query(JournalEntry).filter(
        JournalEntry.business_id == business_id,
        JournalEntry.source_type == source_type,
        JournalEntry.source_id == source_id,
    ).first()
    if existing is not None:
        return existing

    # A journal entry always carries a date — fall back to the posting date
    # (today) when the source document didn't record one.
    entry_date = entry_date or datetime.today().strftime("%Y-%m-%d")

    # Period lock: refuse to post into a closed period. Checked AFTER the
    # idempotency return above, so re-running a command that already posted a
    # pre-lock entry is never falsely blocked. This is the single choke point
    # protecting every money write path (sale/payment/note/purchase/expense) —
    # each composes its journal entry here before the caller commits, so a raise
    # aborts the whole command.
    from core.accounting import period_lock  # lazy import: avoid cycle
    period_lock.assert_period_open(db, business_id, entry_date)

    clean = [(a, _r2(dr), _r2(cr)) for (a, dr, cr) in lines if _r2(dr) or _r2(cr)]
    td = _r2(sum(dr for _, dr, _ in clean))
    tc = _r2(sum(cr for _, _, cr in clean))
    if abs(td - tc) >= 0.01:
        raise ValueError(
            f"journal entry does not foot: Dr {td} != Cr {tc} ({source_type} {source_id})")

    # Tamper-evident hash chain (R3): link this entry to the previous one for the
    # business. prev_hash = the last entry's entry_hash ("GENESIS" for the first).
    prev = (
        db.query(JournalEntry)
        .filter(JournalEntry.business_id == business_id)
        .order_by(JournalEntry.id.desc())
        .first()
    )
    prev_hash = prev.entry_hash if (prev and prev.entry_hash) else GENESIS_HASH
    entry_hash = _chain_hash(
        business_id=business_id, entry_date=entry_date, source_type=source_type,
        source_id=source_id, ref_no=ref_no, narration=narration,
        clean=clean, prev_hash=prev_hash,
    )

    entry = JournalEntry(
        business_id=business_id, entry_date=entry_date,
        source_type=source_type, source_id=source_id,
        ref_no=ref_no, narration=narration,
        prev_hash=prev_hash, entry_hash=entry_hash,
    )
    db.add(entry)
    db.flush()
    for (a, dr, cr) in clean:
        db.add(JournalLine(entry_id=entry.id, account=a, debit=dr, credit=cr))

    logger.info("[ACCT] posted %s#%s biz=%s dr=%.2f cr=%.2f lines=%d hash=%s",
                source_type, source_id, business_id, td, tc, len(clean), entry_hash[:12])
    return entry


def verify_chain(db, business_id) -> dict:
    """Walk a business's posted journal in order and recompute the hash chain.

    Returns {ok, checked, head} when intact, or {ok: False, broken_at, ...} at the
    FIRST entry whose stored prev_hash/entry_hash doesn't match the recomputation
    — i.e. the first place the books were edited, deleted, or reordered. Legacy
    entries pre-dating R3 (no entry_hash) are skipped, so the chain verifies from
    the first hashed entry forward.
    """
    from sqlalchemy.orm import selectinload
    entries = (
        db.query(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .filter(JournalEntry.business_id == business_id)
        .order_by(JournalEntry.id.asc())
        .all()
    )
    prev_hash = GENESIS_HASH
    checked = 0
    for e in entries:
        if not e.entry_hash:
            continue  # legacy, un-chained entry
        clean = [(l.account, _r2(l.debit), _r2(l.credit))
                 for l in sorted(e.lines, key=lambda x: x.id)]
        expected = _chain_hash(
            business_id=e.business_id, entry_date=e.entry_date,
            source_type=e.source_type, source_id=e.source_id,
            ref_no=e.ref_no, narration=e.narration,
            clean=clean, prev_hash=prev_hash,
        )
        if e.prev_hash != prev_hash or e.entry_hash != expected:
            logger.warning("[ACCT] hash chain BROKEN biz=%s at entry id=%s ref=%s",
                           business_id, e.id, e.ref_no)
            return {
                "ok": False, "checked": checked,
                "broken_at": {"id": e.id, "ref_no": e.ref_no,
                              "source_type": e.source_type, "source_id": e.source_id,
                              "entry_date": e.entry_date},
                "expected_hash": expected, "stored_hash": e.entry_hash,
            }
        prev_hash = e.entry_hash
        checked += 1
    return {"ok": True, "checked": checked, "head": prev_hash if checked else None}


# ── Line Builders (shared with reports._build_journal_entries to DRY account mapping) ──

def build_sale_lines(inv):
    total = _r2(inv.total_amount)                       # payable (already net of any cash discount)
    cash = _r2(getattr(inv, "cash_discount", 0.0))      # post-tax cash discount given (R4)
    gross = _r2(total + cash)                            # pre-cash-discount total (== `total` when cash==0)
    gst = _gst_total(inv)
    net = _r2(gross - gst)                               # Sales credit = full revenue (unchanged when cash==0)
    paid = _r2(min(inv.paid_amount or 0.0, total))
    ar = _r2(total - paid)
    # Cash discount booked as an expense (Discount Allowed) so the entry still foots
    # while Sales + GST stay on the FULL value. Zero line is dropped by post_entry,
    # making cash==0 byte-identical to the original two-sided sale entry.
    return [(ACC_CASH, paid, 0.0), (ACC_AR, ar, 0.0), (ACC_DISCOUNT, cash, 0.0),
            (ACC_SALES, 0.0, net), (ACC_GST_OUT, 0.0, gst)]


def build_credit_note_lines(inv):
    total = _r2(inv.total_amount)
    gst = _gst_total(inv)
    net = _r2(total - gst)
    return [(ACC_SALES, net, 0.0), (ACC_GST_OUT, gst, 0.0), (ACC_AR, 0.0, total)]


def build_purchase_lines(pur):
    total = _r2(pur.total_amount)
    gst = _gst_total(pur)
    net = _r2(total - gst)
    settle = ACC_CASH if pur.status == "Paid" else ACC_AP
    return [(ACC_PURCHASES, net, 0.0), (ACC_GST_IN, gst, 0.0), (settle, 0.0, total)]


def build_debit_note_lines(pur):
    total = _r2(pur.total_amount)
    gst = _gst_total(pur)
    net = _r2(total - gst)
    settle = ACC_CASH if pur.status == "Paid" else ACC_AP
    return [(settle, total, 0.0), (ACC_PURCHASES, 0.0, net), (ACC_GST_IN, 0.0, gst)]


def build_expense_lines(exp):
    amt = _r2(exp.amount)
    acct = f"{exp.category} Expense" if exp.category else "Operating Expenses"
    return [(acct, amt, 0.0), (ACC_CASH, 0.0, amt)]


# ── Document-specific posting (reuses builders, composes without committing) ──────────

def post_sale(db, inv):
    return post_entry(
        db, business_id=inv.business_id, entry_date=inv.invoice_date,
        source_type="sale", source_id=inv.id, ref_no=inv.invoice_id,
        narration=f"Sale — {inv.customer or 'customer'}",
        lines=build_sale_lines(inv),
    )


def post_credit_note(db, inv):
    return post_entry(
        db, business_id=inv.business_id, entry_date=inv.invoice_date,
        source_type="credit_note", source_id=inv.id, ref_no=inv.invoice_id,
        narration=f"Sales return — {inv.customer or 'customer'}",
        lines=build_credit_note_lines(inv),
    )


def post_purchase(db, pur):
    return post_entry(
        db, business_id=pur.business_id, entry_date=pur.invoice_date,
        source_type="purchase", source_id=pur.id, ref_no=pur.invoice_number,
        narration=f"Purchase — {pur.supplier_name or 'supplier'}",
        lines=build_purchase_lines(pur),
    )


def post_debit_note(db, pur):
    return post_entry(
        db, business_id=pur.business_id, entry_date=pur.invoice_date,
        source_type="debit_note", source_id=pur.id, ref_no=pur.invoice_number,
        narration=f"Purchase return — {pur.supplier_name or 'supplier'}",
        lines=build_debit_note_lines(pur),
    )


def post_expense(db, exp):
    return post_entry(
        db, business_id=exp.business_id, entry_date=exp.expense_date,
        source_type="expense", source_id=exp.id, ref_no=f"EXP-{exp.id}",
        narration=exp.category or "Expense",
        lines=build_expense_lines(exp),
    )


def post_payment(db, pay):
    """A later receipt against an invoice: Dr Cash, Cr Accounts Receivable."""
    amt = _r2(pay.amount_paid)
    return post_entry(
        db, business_id=pay.business_id, entry_date=pay.payment_date,
        source_type="payment", source_id=pay.id, ref_no=f"REC-{pay.id}",
        narration="Payment received",
        lines=[(ACC_CASH, amt, 0.0), (ACC_AR, 0.0, amt)],
    )
