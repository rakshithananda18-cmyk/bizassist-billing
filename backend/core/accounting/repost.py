"""
core/accounting/repost.py — re-derive the journal on the destination of a sync
==============================================================================
ONE job: when a commercial document arrives over sync, make sure the receiving
database posts its own journal entry for it.

THE BUG THIS CLOSES (review finding M-2)
----------------------------------------
``journal_entries`` and ``journal_lines`` are absent from
``database/sync_map.MODEL_MAP``. A sale rung up on a local install pushed its
Invoice, line items, stock movements and payment receipt to the cloud — and
left the journal behind. The cloud's trial balance, P&L and party ledger
therefore omitted every locally-rung sale, and the local side omitted every
cloud-rung one. Neither database raised anything: each was internally
consistent and the two were jointly wrong. The scheduled books-integrity audit
runs per-database, so it reported "balanced" on both.

WHY RE-DERIVE INSTEAD OF REPLICATING THE ROWS
---------------------------------------------
A journal entry is a deterministic function of its source document — that is
the whole design of ``posting.build_*_lines``. Two further facts make copying
the rows the wrong move:

  1. ``JournalEntry`` carries a **tamper-evident hash chain** in which each
     entry's ``prev_hash`` is the previous entry's hash *for that business in
     that database*. Entries arrive over sync interleaved and out of order, so
     a copied chain is invalid on arrival and would have to be rebuilt — at
     which point nothing was gained by copying it.
  2. ``source_id`` is the source document's integer PK, which differs between
     databases. A copied entry would point at the wrong document, or at none.

Re-posting locally instead gives each database a correct, self-consistent,
independently verifiable chain over the same underlying documents. Both sides
agree on the numbers without ever having to agree on the hashes.

IDEMPOTENCY
-----------
``posting.post_entry`` is idempotent on ``(business_id, source_type,
source_id)`` and ``source_id`` here is the DESTINATION's own row id, so
re-applying the same document — an outbox replay, an LWW update, a re-pull —
returns the existing entry and posts nothing new. That is what makes it safe to
call this on *every* apply rather than only on insert.

NO SILENT FAILURES
------------------
A repost that fails must never abort the sync batch (one bad document would
stall the whole outbox), but it must also never vanish. Failures are logged at
ERROR with the document identified, and recorded in ``SyncLog`` so they are
visible to the books-integrity audit rather than only to whoever reads the log
file. The caller gets back a result object saying what happened.
"""
import logging
from typing import Optional

from core.accounting import posting

logger = logging.getLogger("bizassist.accounting.repost")


# Sync entity name -> how to post it. Anything not listed here has no journal
# consequence (products, customers, barcodes, settings, stock rows …) and is
# skipped without comment.
#
# NOTE: every builder in `posting` reads HEADER fields only (totals, tax totals,
# paid_amount, dates) — never line items — so a document can be reposted the
# moment its header row lands, without waiting for its children to sync.
REPOSTABLE_ENTITIES = frozenset({
    "invoices",
    "invoice_payments",
    "purchase_invoices",
    "expenses",
})


class RepostResult:
    """What happened, in a form the caller can log or count.

    ``status`` is one of:
      ``"posted"``   a new journal entry was written
      ``"existing"`` already posted (idempotent hit) — the common case
      ``"skipped"``  this entity has no journal consequence, or the row is not
                     postable yet (e.g. a draft purchase)
      ``"failed"``   the repost raised; ``error`` carries why
    """

    __slots__ = ("status", "entity", "row_id", "error")

    def __init__(self, status: str, entity: str = "", row_id=None, error: str = ""):
        self.status = status
        self.entity = entity
        self.row_id = row_id
        self.error = error

    @property
    def ok(self) -> bool:
        return self.status != "failed"

    def __repr__(self):                                    # pragma: no cover
        return f"<RepostResult {self.status} {self.entity}#{self.row_id} {self.error}>"


def is_initial_payment(pay) -> bool:
    """True when this receipt was taken AT SALE TIME and is already in the books.

    THE DOUBLE-COUNT THIS PREVENTS
    ------------------------------
    ``create_sale_invoice`` writes an ``InvoicePayment`` row whenever the bill is
    paid (fully or partly) at the counter — but it does NOT post a separate
    journal entry for it, because ``build_sale_lines`` has already debited Cash
    for ``paid_amount`` inside the SALE entry. The row is a receipt record, not a
    second accounting event.

    The first version of this module reposted every ``invoice_payments`` row it
    saw. On the destination of a sync that means:

        invoice arrives  → sale entry posted     → Dr Cash 236
        its receipt arrives → payment entry posted → Dr Cash 236   ← again

    Cash counted twice, on every ``mark_paid`` sale, silently. The trial balance
    still foots — both entries are internally balanced — so nothing would have
    flagged it. It was caught only because the end-to-end reconciliation test
    asserted the opposite and failed.

    The marker is the note ``create_sale_invoice`` stamps; a LATER receipt
    (``record_payment``) carries a different note or none, and does get its own
    entry.
    """
    return (getattr(pay, "note", None) or "").strip().startswith(
        "Initial payment for invoice")


def _is_advance_application(pay) -> bool:
    """True when this receipt SPENDS a customer's banked advance rather than
    bringing in new cash.

    It matters because the two cases hit different accounts: a real receipt is
    Dr Cash / Cr AR, while applying an advance is Dr Customer Advances / Cr AR —
    the cash was already booked when the advance was taken, so posting it as
    cash again would double-count it.

    ``core.billing.commands`` stamps a deliberate marker on these rows
    (``idempotency_key = "advance-credit::<invoice id>"``); the note is a
    fallback for rows written before that key existed. Deliberately NOT keyed on
    ``payment_mode == "Credit"``, which is ambiguous — it reads as "store credit"
    here but users also select it for card payments.
    """
    key = (getattr(pay, "idempotency_key", None) or "")
    if key.startswith("advance-credit::"):
        return True
    return (getattr(pay, "note", None) or "").strip().lower() == "applied advance credit"


# Every poster below takes ``enforce_period_lock`` explicitly rather than the
# module patching ``posting.post_entry`` for the duration of a call. The sync
# worker runs on a BACKGROUND THREAD while the API serves requests on others, so
# a patched module global would leak the bypass into whatever user-facing sale
# happened to post in the same instant — silently letting a counter write into
# closed books. The flag travels down the call stack instead; nothing shared is
# ever mutated.

def _post_invoice(db, inv, *, enforce_period_lock):
    """A sale or a credit note — they share the ``invoices`` table."""
    if (getattr(inv, "invoice_type", None) or "") == "credit_note":
        return posting.post_credit_note(db, inv, enforce_period_lock=enforce_period_lock)
    return posting.post_sale(db, inv, enforce_period_lock=enforce_period_lock)


def _post_purchase(db, pur, *, enforce_period_lock):
    if (getattr(pur, "invoice_type", None) or "") == "debit_note":
        return posting.post_debit_note(db, pur, enforce_period_lock=enforce_period_lock)
    return posting.post_purchase(db, pur, enforce_period_lock=enforce_period_lock)


def _post_payment(db, pay, *, enforce_period_lock):
    debit_account = (posting.ACC_ADVANCE if _is_advance_application(pay)
                     else posting.ACC_CASH)
    return posting.post_payment(db, pay, debit_account=debit_account,
                                enforce_period_lock=enforce_period_lock)


def _post_expense(db, exp, *, enforce_period_lock):
    return posting.post_expense(db, exp, enforce_period_lock=enforce_period_lock)


_POSTERS = {
    "invoices": _post_invoice,
    "invoice_payments": _post_payment,
    "purchase_invoices": _post_purchase,
    "expenses": _post_expense,
}


def repost_synced_row(db, entity: str, obj, *, log_prefix: str = "sync") -> RepostResult:
    """Ensure the journal entry for a just-applied synced row exists HERE.

    Composes without committing — it joins the caller's transaction, exactly
    like the command paths do, so the document and its journal land together or
    not at all.

    Never raises. A repost failure is a bookkeeping problem with one document;
    letting it propagate would abort the whole sync batch and stall the outbox
    behind it, which is a much larger failure. The error is returned (and logged
    at ERROR) so the caller can record it instead of dropping it.

    ``enforce_period_lock=False`` is deliberate and is set for every call from
    here — see ``posting.post_entry``. The document was already posted in the
    database that authored it; the destination merely locked its books on a
    different day, and refusing the entry would leave that destination holding a
    document with no journal, i.e. books that do not balance.
    """
    if entity not in REPOSTABLE_ENTITIES or obj is None:
        return RepostResult("skipped", entity)

    row_id = getattr(obj, "id", None)
    if row_id is None or getattr(obj, "business_id", None) is None:
        # Nothing to key idempotency on yet — the caller must flush() first.
        return RepostResult("skipped", entity, row_id)

    # An initial receipt is ALREADY inside its invoice's sale entry (Dr Cash for
    # paid_amount). Posting one here too debits Cash a second time — see
    # is_initial_payment. This check must come before anything else touches it.
    if entity == "invoice_payments" and is_initial_payment(obj):
        return RepostResult("skipped", entity, row_id)

    poster = _POSTERS.get(entity)
    if poster is None:                                     # pragma: no cover
        return RepostResult("skipped", entity, row_id)

    # Was it already posted? Answered before we post so we can report
    # "existing" vs "posted" honestly rather than inferring it afterwards.
    from core.models import JournalEntry
    source_type = _source_type_of(entity, obj)
    already = (
        db.query(JournalEntry.id)
        .filter(JournalEntry.business_id == obj.business_id,
                JournalEntry.source_type == source_type,
                JournalEntry.source_id == row_id)
        .first()
        is not None
    )
    if already:
        return RepostResult("existing", entity, row_id)

    try:
        # SAVEPOINT around the post. Catching the exception is not enough on its
        # own: a failed flush leaves the SQLAlchemy session in a state where
        # every later statement raises until something rolls back. Without this,
        # one unpostable document would poison the rest of the sync batch —
        # turning a single missing journal entry into a stalled outbox.
        with db.begin_nested():
            poster(db, obj, enforce_period_lock=False)
            db.flush()
        logger.info("[REPOST] %s: posted journal for %s#%s biz=%s",
                    log_prefix, entity, row_id, obj.business_id)
        return RepostResult("posted", entity, row_id)
    except Exception as e:
        # Loud, identified, and handed back — never swallowed. The books being
        # short one entry is a real defect and has to be visible.
        logger.error("[REPOST] %s: FAILED to post journal for %s#%s biz=%s: %s",
                     log_prefix, entity, row_id, getattr(obj, "business_id", None), e,
                     exc_info=True)
        return RepostResult("failed", entity, row_id, str(e))


def _source_type_of(entity: str, obj) -> str:
    """The ``JournalEntry.source_type`` the poster for this row will use.

    Kept next to ``_POSTERS`` on purpose: if a poster's source_type changes and
    this doesn't, the idempotency probe silently stops matching and every sync
    would post a duplicate entry.
    """
    if entity == "invoices":
        return "credit_note" if (getattr(obj, "invoice_type", None) or "") == "credit_note" else "sale"
    if entity == "purchase_invoices":
        return "debit_note" if (getattr(obj, "invoice_type", None) or "") == "debit_note" else "purchase"
    if entity == "invoice_payments":
        return "payment"
    return "expense"


def repost_unposted_documents(db, business_id: int) -> dict:
    """Self-healing utility to scan all sales, purchases, payments, and expenses
    for the specified business and post any unposted journal entries."""
    from database.models import Invoice, PurchaseInvoice, InvoicePayment, Expense
    counts = {"posted": 0, "existing": 0, "failed": 0}

    targets = [
        ("invoices", db.query(Invoice).filter(Invoice.business_id == business_id).all()),
        ("purchase_invoices", db.query(PurchaseInvoice).filter(PurchaseInvoice.business_id == business_id).all()),
        ("invoice_payments", db.query(InvoicePayment).filter(InvoicePayment.business_id == business_id).all()),
        ("expenses", db.query(Expense).filter(Expense.business_id == business_id).all()),
    ]

    for entity, rows in targets:
        for row in rows:
            res = repost_synced_row(db, entity, row, log_prefix="repost_unposted")
            if res.status in counts:
                counts[res.status] += 1

    return counts
