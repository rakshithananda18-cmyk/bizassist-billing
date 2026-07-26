"""
core/billing/sequence.py — monotonic document numbering  (review finding F-3)
=============================================================================
ONE job: hand out the next number in a ``(business_id, series)`` series such
that a number is NEVER handed out twice.

THE BUG THIS REPLACES
---------------------
``_next_invoice_number`` used to be ``COUNT(invoices LIKE 'INV-%') + 1``. Two
independent failures fell out of that:

  1. **Reuse after deletion.** COUNT is a function of the rows that exist right
     now. Delete INV-0007 and the next sale is issued INV-0007 again — two
     different bills sharing one number. Rule 46 of the CGST Rules requires the
     serial number of a tax invoice to be unique for the financial year, so
     this is a compliance breach, not just an inconvenience.
  2. **Read-then-write race.** Two counters that COUNT at the same instant read
     the same value and both mint the same number. The collision was caught
     downstream by ``renumber_on_conflict``, but only after the fact.

Both go away when the counter is STORED rather than DERIVED, and reserved with
a single atomic UPDATE.

GAPS ARE FINE, REUSE IS NOT
---------------------------
If a sale is rolled back after reserving a number, that number is simply never
used. A gap in the series is legal and auditable (the ledger shows nothing was
issued). A reused number is neither, because it makes two documents
indistinguishable in the audit trail. So this module optimises hard for "never
twice" and not at all for "never a gap".

Note that the reservation lives in the CALLER's transaction: if the caller
rolls back, the reservation rolls back with it and the number is handed out
again — the common "sale failed validation" path leaves no gap at all.

ATOMICITY
---------
``_reserve`` issues ``UPDATE document_sequences SET last_number = <expr>`` and
then reads the row back. The UPDATE takes a row lock on Postgres and the
database write lock on SQLite, both held until the caller commits, so a second
allocator blocks rather than reading a stale value. No dialect-specific
``FOR UPDATE`` is needed and no ``RETURNING`` support is assumed.

HEALING
-------
The counter is per-database and unsynced (see ``core.models.DocumentSequence``),
so rows can arrive from elsewhere — a cloud→local pull, a data import, a
hand-typed ``invoice_no`` — carrying numbers ahead of the local counter. When a
reserved number turns out to be taken, ``next_number`` heals the counter UP to
the observed maximum and reserves again. Healing only ever raises the counter,
so the monotonic guarantee survives the repair.

The parsing/formatting helpers at the top are pure and unit-tested without a DB.
"""
import logging
import re
from typing import Callable, Iterable, Optional

from sqlalchemy import and_, case, select, update

from core.models import DocumentSequence

logger = logging.getLogger("bizassist.billing.sequence")

# Zero-pad width of the numeric tail: INV-0001. Widening later is safe — a
# wider number still sorts and compares correctly and is still unique.
DEFAULT_WIDTH = 4

# Legacy/default series for single-counter installs that send no counter_prefix.
DEFAULT_SERIES = "INV"

# Credit notes get their own series so a return never consumes a sale number.
CREDIT_NOTE_SERIES = "CN"

# Sentinel ``business_id`` for counters that are NOT owned by one business.
#
# Almost every number here is per-tenant: two shops may both hold INV-0001 and
# that is correct. B2B order numbers are the exception — ``B2BOrder.order_number``
# carries a GLOBAL ``unique=True``, because an order is a shared record between
# two tenants and both must be able to quote the same reference. A per-business
# counter would have every buyer minting ORD-<date>-0001 on the same morning and
# all but the first failing the constraint.
#
# Safe because B2B is cloud-authoritative (architecture rule 2): order creation
# only ever executes against the one cloud database, so "system-wide" really is
# one counter. ``0`` is never a real ``users.id``.
SYSTEM_SCOPE = 0

# Upper bound on the "reserved number was taken, try the next one" probe. Only
# reachable if the series is densely occupied by numbers the counter never
# issued; a bounded loop turns that into a loud error instead of a hung request.
MAX_PROBE = 1000


# ---------------------------------------------------------------------------
# PURE HELPERS (no DB — unit-tested directly)
# ---------------------------------------------------------------------------

def normalize_series(prefix: Optional[str], default: str = DEFAULT_SERIES) -> str:
    """Canonical series name: trimmed, no trailing '-', never empty.

    Callers pass a counter prefix that may or may not carry the separator
    (``"C1"`` and ``"C1-"`` are the same terminal), so both must normalise to
    the same series or the terminal would silently get two counters.
    """
    return (prefix or "").strip().rstrip("-").strip() or default


def format_number(series: str, n: int, width: int = DEFAULT_WIDTH) -> str:
    """``("INV", 7) -> "INV-0007"``. Values past the pad width simply get wider."""
    return f"{series}-{int(n):0{max(int(width), 1)}d}"


def suffix_of(number: Optional[str], series: str) -> Optional[int]:
    """Numeric tail of ``number`` if it belongs to ``series``, else None.

    Strict on purpose: only ``<series>-<digits>`` counts. A number like
    ``LCL-C1-0005`` belongs to the ``LCL-C1`` series, not to ``C1`` — treating
    it as a ``C1`` member would let one series drag another's counter forward.
    """
    if not number or not series:
        return None
    head = f"{series}-"
    if not number.startswith(head):
        return None
    tail = number[len(head):]
    if not tail.isdigit():
        return None
    try:
        return int(tail)
    except ValueError:      # pragma: no cover — isdigit already guarantees this
        return None


def max_suffix(numbers: Iterable[Optional[str]], series: str) -> int:
    """Highest numeric tail among ``numbers`` that belong to ``series`` (0 if none)."""
    best = 0
    for num in numbers or ():
        n = suffix_of(num, series)
        if n is not None and n > best:
            best = n
    return best


# ---------------------------------------------------------------------------
# DB MECHANICS
# ---------------------------------------------------------------------------

def _insert_ignore(db, values: dict):
    """INSERT that silently does nothing if the row already exists.

    Two counters can race to create the same brand-new series. Without the
    ignore, the loser raises IntegrityError and would have to roll back — which
    would take the caller's in-flight sale down with it. Dialect-specific
    because SQLAlchemy has no portable spelling for this.
    """
    table = DocumentSequence.__table__
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=["business_id", "series"]
        )
    elif dialect == "sqlite":
        stmt = table.insert().prefix_with("OR IGNORE").values(**values)
    else:                                   # pragma: no cover — no other dialect ships
        stmt = table.insert().values(**values)
    return db.execute(stmt)


def _ensure_row(db, business_id: int, series: str, *, seed: int = 0) -> bool:
    """Create the counter row if absent. Returns True if THIS call created it.

    ``seed`` is the highest number already issued in the series. It matters on
    the upgrade path: an install with INV-0001…INV-0123 already on disk must
    continue at INV-0124, not restart at INV-0001. Seeding at creation is the
    only place a counter is set from observed data; every later move is a
    monotonic bump.
    """
    existing = (
        db.query(DocumentSequence.id)
        .filter(DocumentSequence.business_id == business_id,
                DocumentSequence.series == series)
        .first()
    )
    if existing is not None:
        return False
    result = _insert_ignore(db, {
        "business_id": business_id,
        "series": series,
        "last_number": max(int(seed or 0), 0),
    })
    # rowcount 0 ⇒ a concurrent allocator created it first; harmless either way.
    created = bool(getattr(result, "rowcount", 0))
    if created and seed:
        logger.info("[SEQ] seeded series %s for biz %s at %s", series, business_id, seed)
    return created


def _reserve(db, business_id: int, series: str, *, floor: int = 0) -> int:
    """Atomically claim and return the next value of this counter.

    ``floor`` raises the counter to at least that value (healing). The CASE is
    evaluated inside the UPDATE so the read and the write are one statement —
    there is no window in which another session sees the old value and claims
    the same number.
    """
    t = DocumentSequence.__table__
    where = and_(t.c.business_id == business_id, t.c.series == series)
    floor = max(int(floor or 0), 0)
    if floor:
        # "at least floor, otherwise just advance" — never lowers the counter.
        new_value = case((t.c.last_number < floor, floor), else_=t.c.last_number + 1)
    else:
        new_value = t.c.last_number + 1
    db.execute(update(t).where(where).values(last_number=new_value))
    # Core SELECT, not the ORM: the identity map may hold a pre-UPDATE copy.
    return int(db.execute(select(t.c.last_number).where(where)).scalar_one())


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def next_number(db, business_id: int, series: Optional[str], *,
                width: int = DEFAULT_WIDTH,
                scan_max: Optional[Callable[[], int]] = None,
                is_taken: Optional[Callable[[str], bool]] = None) -> str:
    """Reserve and return the next number in ``series`` for this business.

    SIDE-EFFECTING: the returned number is consumed. Calling this twice returns
    two different numbers — it is an allocator, not a preview. Use
    ``peek_number`` if you only want to show the user what comes next.

    ``scan_max``  — lazy callable returning the highest number already present
                    in this series in the underlying table. Called at most
                    twice: once to seed a brand-new counter, once to heal a
                    counter that has fallen behind. Never called on the hot
                    path of an established series.
    ``is_taken``  — callable that answers "does a row already carry this
                    number?". Drives the heal. Omit it and the counter's word
                    is taken as final.
    """
    series = normalize_series(series)
    created = _ensure_row(db, business_id, series,
                          seed=(scan_max() if scan_max is not None else 0))

    n = _reserve(db, business_id, series)
    candidate = format_number(series, n, width)
    if is_taken is None or not is_taken(candidate):
        return candidate

    # The counter is behind numbers it never issued (rows pulled from the cloud,
    # imported, or hand-typed). Heal it up to the observed maximum in ONE jump
    # rather than crawling forward one collision at a time. Skipped when we just
    # created the row, because it was already seeded from that same maximum.
    if scan_max is not None and not created:
        observed = int(scan_max() or 0)
        if observed >= n:
            n = _reserve(db, business_id, series, floor=observed + 1)
            candidate = format_number(series, n, width)
            logger.warning("[SEQ] series %s (biz %s) healed forward to %s",
                           series, business_id, n)
            if not is_taken(candidate):
                return candidate

    # Last resort: walk forward. Reachable only if the series is pitted with
    # numbers above the counter that scan_max could not see.
    for _ in range(MAX_PROBE):
        n = _reserve(db, business_id, series)
        candidate = format_number(series, n, width)
        if not is_taken(candidate):
            return candidate

    raise RuntimeError(
        f"Could not allocate a free number in series '{series}' for business "
        f"{business_id} after {MAX_PROBE} attempts (last tried {candidate})."
    )


def peek_number(db, business_id: int, series: Optional[str],
                width: int = DEFAULT_WIDTH) -> str:
    """Read-only preview of the next number. Reserves NOTHING.

    Only safe for display. Two callers peeking concurrently see the same value,
    which is precisely the race ``next_number`` exists to avoid.
    """
    series = normalize_series(series)
    last = (
        db.query(DocumentSequence.last_number)
        .filter(DocumentSequence.business_id == business_id,
                DocumentSequence.series == series)
        .scalar()
    )
    return format_number(series, int(last or 0) + 1, width)


def current_value(db, business_id: int, series: Optional[str]) -> int:
    """Highest value handed out so far (0 when the series has never been used)."""
    series = normalize_series(series)
    return int(
        db.query(DocumentSequence.last_number)
        .filter(DocumentSequence.business_id == business_id,
                DocumentSequence.series == series)
        .scalar() or 0
    )


_LIKE_WILDCARDS = re.compile(r"([%_\\])")


def like_prefix(series: str) -> str:
    """``LIKE`` pattern matching every number in ``series``, wildcards escaped.

    A series name is owner-configured (``counter_prefix``), so an underscore in
    it would otherwise act as a single-character wildcard and pull a neighbour's
    numbers into the scan. Pair with ``escape="\\\\"`` at the call site.
    """
    return _LIKE_WILDCARDS.sub(r"\\\1", series or "") + "-%"
