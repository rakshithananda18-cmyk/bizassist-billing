"""
core/accounting/period_lock.py — period close/lock enforcement.
================================================================
"Closing the books" through a date means: no journal entry may be POSTED with
`entry_date <= locked_through`. State is event-sourced in `period_locks`
(append-only lock/unlock events); the *effective* lock for a business is the most
recent event — `locked_through` if it `is_active`, else None (unlocked).

The single enforcement point is `assert_period_open()`, called from
`posting.post_entry` AFTER its idempotency check. Because every money mutation
(sale, payment, credit/debit note, purchase, expense) posts a journal entry
inside its own transaction before the command commits, one guard here protects
every write path atomically: a raise aborts the whole command (no commit).

All functions are business_id-scoped and compose WITHOUT committing — the caller
(API endpoint / command) owns the commit, exactly like the rest of accounting.
"""
import logging
from typing import Optional

from core.models import PeriodLock

logger = logging.getLogger("bizassist.accounting")


class PeriodLockedError(ValueError):
    """Raised when a journal entry would post into a closed (locked) period.

    Subclasses ValueError so the existing money-command routes (which already map
    `except ValueError` → HTTP 422 with the message) surface it cleanly and
    consistently, and so the command's transaction is aborted (never committed).
    """

    def __init__(self, message, locked_through=None, entry_date=None):
        super().__init__(message)
        self.locked_through = locked_through
        self.entry_date = entry_date


def effective_lock(db, business_id) -> Optional[str]:
    """Return the inclusive locked-through date for a business, or None if open.

    The latest event wins (event-sourced): a lock event sets the boundary, an
    unlock event (is_active=False) lifts it.
    """
    row = (
        db.query(PeriodLock)
        .filter(PeriodLock.business_id == business_id)
        .order_by(PeriodLock.id.desc())
        .first()
    )
    if row is None or not row.is_active:
        return None
    return row.locked_through


def assert_period_open(db, business_id, entry_date) -> None:
    """Raise AskError(409) if `entry_date` falls in a locked (closed) period.

    A missing/empty entry_date can't be proven to be in the open period, so it is
    treated conservatively as on-or-before any lock and rejected when a lock
    exists (callers default entry_date to today() before posting, so real writes
    always carry a date).
    """
    locked_through = effective_lock(db, business_id)
    if not locked_through:
        return
    d = entry_date or ""
    if d <= locked_through:
        logger.info("[ACCT] blocked post into locked period biz=%s date=%s locked_through=%s",
                    business_id, entry_date, locked_through)
        raise PeriodLockedError(
            f"The books are locked through {locked_through}. "
            f"Post a reversing entry in the open period instead of changing a closed one.",
            locked_through=locked_through, entry_date=entry_date,
        )


def lock_period(db, *, business_id, through, note=None) -> PeriodLock:
    """Append a LOCK event closing the books through `through` (inclusive). No commit."""
    evt = PeriodLock(business_id=business_id, locked_through=through, is_active=True, note=note)
    db.add(evt)
    logger.info("[ACCT] period locked biz=%s through=%s", business_id, through)
    return evt


def unlock_period(db, *, business_id, note=None) -> PeriodLock:
    """Append an UNLOCK event lifting the current lock. No commit."""
    evt = PeriodLock(business_id=business_id, locked_through=None, is_active=False, note=note)
    db.add(evt)
    logger.info("[ACCT] period unlocked biz=%s", business_id)
    return evt


def lock_history(db, business_id):
    """All lock/unlock events for a business, newest first (for the audit view)."""
    return (
        db.query(PeriodLock)
        .filter(PeriodLock.business_id == business_id)
        .order_by(PeriodLock.id.desc())
        .all()
    )
