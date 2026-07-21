"""
core/accounting/integrity.py — on-demand & scheduled books-integrity check.
=============================================================================
Two independent guarantees, checked together (P0 "scheduled verify_chain +
trial-balance drift"):

  1. HASH CHAIN INTACT — `posting.verify_chain`: nobody edited/deleted/reordered
     a posted journal entry (tamper evidence).

  2. JOURNAL FOOTS GLOBALLY — SUM(all journal_lines.debit) == SUM(all credits).
     Every entry foots individually at post time (posting.post_entry raises
     otherwise), so the whole ledger MUST foot; a non-zero drift means a line was
     corrupted or an entry was written bypassing the command layer.

`run_integrity_check` composes both into one report and never raises — it is a
read-only diagnostic safe to call from a request handler or a scheduled job.
`assert_books_intact` is the raising variant for tests/guards.
"""
import logging

from sqlalchemy import func

from core.models import JournalEntry, JournalLine
from core.accounting import posting

logger = logging.getLogger("bizassist.accounting.integrity")


def journal_balance(db, business_id: int) -> dict:
    """Global Dr/Cr totals over a business's posted journal lines and their drift.
    ``ok`` when |drift| < 0.01 (a rounding epsilon)."""
    row = (
        db.query(
            func.coalesce(func.sum(JournalLine.debit), 0.0),
            func.coalesce(func.sum(JournalLine.credit), 0.0),
        )
        .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
        .filter(JournalEntry.business_id == business_id)
        .first()
    )
    total_debit = round(float(row[0] or 0.0), 2)
    total_credit = round(float(row[1] or 0.0), 2)
    drift = round(total_debit - total_credit, 2)
    return {
        "ok": abs(drift) < 0.01,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "drift": drift,
    }


def run_integrity_check(db, business_id: int) -> dict:
    """Read-only combined report. Never raises. Shape:

        {
          "ok": bool,                       # both checks passed
          "business_id": int,
          "hash_chain": {...verify_chain...},
          "journal_balance": {...journal_balance...},
        }
    """
    chain = posting.verify_chain(db, business_id)
    balance = journal_balance(db, business_id)
    ok = bool(chain.get("ok")) and bool(balance.get("ok"))
    if not ok:
        logger.warning(
            "[ACCT] integrity check FAILED biz=%s chain_ok=%s balance_ok=%s drift=%s",
            business_id, chain.get("ok"), balance.get("ok"), balance.get("drift"),
        )
    return {
        "ok": ok,
        "business_id": business_id,
        "hash_chain": chain,
        "journal_balance": balance,
    }


def assert_books_intact(db, business_id: int) -> None:
    """Raising variant for tests / hard guards."""
    report = run_integrity_check(db, business_id)
    if not report["ok"]:
        raise ValueError(f"books integrity check failed for business {business_id}: {report}")
