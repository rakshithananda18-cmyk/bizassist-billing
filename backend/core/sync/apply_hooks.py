"""
core/sync/apply_hooks.py — invariants that must hold after ANY sync apply
=========================================================================
Single source of truth for the work that has to happen *after* a synced row is
written, on BOTH sides of the wire.

THE BUG THIS CLOSES (review finding M-7)
----------------------------------------
Reported symptom: *"I synced invoices from cloud to local — the history shows
the payment, but the invoice is still Pending."*

``Invoice.paid_amount`` and ``Invoice.status`` are a PROJECTION of the
append-only ``invoice_payments`` ledger, so they have to be re-derived every
time either side of that relationship lands. The cloud did exactly that:
``routes/sync.py::push_changes`` called ``_reconcile_invoice_paid_state`` on
every invoice and every payment it received.

The local pull worker did not — because the function lived *inside the route
module*, where ``services/sync_worker.py`` could not reach it. So the
correction ran in one direction only, and every invoice pulled down kept
whatever status happened to be serialised on the cloud at the moment the
snapshot was taken.

It is made worse by batch ordering: ``invoice_payments`` is in the pull
worker's ``_child_last`` group, so within a single batch the invoice is applied
**before** its payment rows exist. At that instant there is genuinely nothing to
reconcile against — the reconciliation *must* also fire when the payment lands,
which is precisely the hook that was missing.

THE REAL DEFECT IS THE DUPLICATION, NOT THE MISSING CALL
--------------------------------------------------------
``database/sync_map.py`` already carries this exact lesson in its header (R-7):
the table→model map used to be copy-pasted into both sync modules, and a table
added to one but not the other silently stopped syncing in one direction. That
was fixed by extracting the map. The *apply logic* was never given the same
treatment, so it drifted the same way, for the same reason, with a worse
symptom — wrong money on screen rather than missing rows.

Everything that must be true after an apply now lives here, and both paths call
``run_post_apply``. A new invariant added here is automatically enforced in both
directions; there is no longer a place to add one to only half the system.
``tests/test_sync_apply_parity.py`` fails if either path stops calling it.

NO SILENT FAILURES
------------------
Every hook reports what it did. A hook that cannot complete returns a failure
in the result rather than raising (one bad row must not stall the outbox) and
the caller logs it at ERROR. Nothing here swallows an exception quietly.
"""
import json
import logging
from datetime import datetime

from sqlalchemy import func

# ConflictLog lives in database/models.py, NOT core/models.py. Imported at module
# scope on purpose: a wrong import here must break at startup, not be swallowed
# by a per-call `except Exception` and silently disable conflict logging.
from database.models import ConflictLog

logger = logging.getLogger("bizassist.sync.apply_hooks")


# Entities whose arrival requires the invoice paid-state projection to be
# recomputed. Both directions, both sides of the invoice↔payment relationship.
PAID_STATE_ENTITIES = frozenset({"invoices", "invoice_payments"})


# Money/audit rows where a concurrent edit resolved by last-write-wins must never
# be resolved SILENTLY. LWW still lands the data — we only remove the silence, by
# recording what the losing side held so the owner can review it.
#
# (M-8) This used to live in routes/sync.py and therefore applied to PUSH only.
# A financial row overwritten by an incoming PULL is the same silent-lost-edit
# the push path was hardened against — it was simply invisible in the other
# direction, for the same structural reason M-7 had.
FINANCIAL_ENTITIES = frozenset({
    "invoices",
    "invoice_line_items",
    "payments",
    "invoice_payments",
    "purchase_invoices",
    "purchase_invoice_line_items",
    "purchase_orders",
    "purchase_order_line_items",
    "expenses",
    "stock_ledger",
    "b2b_ledgers",
})

# Columns that always differ between two copies of the same row and therefore
# say nothing about whether a MEANINGFUL edit happened.
_CONFLICT_IGNORED_COLUMNS = frozenset({
    "updated_at", "created_at", "synced_at", "last_synced_at",
    "sync_status", "id", "_sa_instance_state",
})


class ApplyResult:
    """What the post-apply hooks did for one row.

    Deliberately not a bare bool: the caller needs to distinguish "nothing to do"
    from "tried and failed", because the second one means a money figure on
    screen is wrong and has to be logged.
    """

    __slots__ = ("entity", "row_id", "reconciled", "repost", "conflict_logged", "errors")

    def __init__(self, entity: str, row_id=None):
        self.entity = entity
        self.row_id = row_id
        self.reconciled = False      # paid-state projection was corrected
        self.repost = None           # RepostResult from the journal re-derivation
        self.conflict_logged = False  # a financial overwrite was flagged for review
        self.errors = []             # list[str] — empty means clean

    @property
    def ok(self) -> bool:
        return not self.errors

    def __repr__(self):                                     # pragma: no cover
        return (f"<ApplyResult {self.entity}#{self.row_id} "
                f"reconciled={self.reconciled} errors={self.errors}>")


# ---------------------------------------------------------------------------
# PURE HELPERS for conflict detection — testable without a database
# ---------------------------------------------------------------------------

def parse_dt(value):
    """Parse a synced timestamp. Returns None when it cannot be parsed.

    NOT SILENT (review finding M-5). Both sync modules carried an identical
    ``except: return None``. The None is load-bearing and correct — callers read
    it as "cannot prove this version is newer" and conservatively keep what they
    have (R-5) — but it meant a row with a malformed ``updated_at`` would stop
    syncing forever with no signal at all. An empty value is normal and stays
    quiet; a NON-empty value that fails to parse is a real data defect and is
    logged.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as e:
        logger.warning(
            "[SYNC_HOOKS] unparseable timestamp %r (%s) — treating as unknown, so "
            "last-write-wins will conservatively keep the existing row. A row "
            "whose updated_at never parses will never sync.", value, e,
        )
        return None


def row_to_dict(row) -> dict:
    """Serialize a row/ORM object to a plain dict, stripping internal SA state."""
    if hasattr(row, "__dict__"):
        d = {k: v for k, v in row.__dict__.items() if k != "_sa_instance_state"}
    else:
        d = dict(row._mapping)
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def payloads_differ(incoming: dict, existing: dict) -> bool:
    """True when ``incoming`` carries a MEANINGFUL change versus ``existing``.

    Compared only on the keys the peer actually sent, ignoring bookkeeping
    columns that always differ, so a no-op re-sync of an unchanged row is not
    flagged as a conflict and does not spam the owner's review list.

    Values are compared as strings because the same value crosses the
    SQLite↔Postgres boundary in different Python types (``123`` vs ``"123"``,
    ``Decimal`` vs ``float``) — comparing natively would flag every row.
    """
    for k, v in (incoming or {}).items():
        if k in _CONFLICT_IGNORED_COLUMNS:
            continue
        if k not in (existing or {}):
            continue
        if str(existing.get(k)) != str(v):
            return True
    return False


def is_financial_overwrite(entity: str, incoming: dict, existing_row,
                           incoming_updated_at, existing_updated_at) -> bool:
    """Should this apply be recorded as a reviewable financial overwrite?

    True only when ALL of these hold:
      · the entity is a money/audit record,
      · we have both timestamps to compare (an unknown one proves nothing),
      · the incoming version is NEWER, so it is about to win under LWW, and
      · the two versions actually differ on a meaningful column.

    Pure, so the exact conditions can be tested without two databases — this is
    the predicate that decides whether an owner ever finds out their invoice was
    edited on two devices.
    """
    if entity not in FINANCIAL_ENTITIES or existing_row is None:
        return False
    if incoming_updated_at is None or existing_updated_at is None:
        return False
    if not incoming_updated_at > existing_updated_at:
        return False
    return payloads_differ(incoming, row_to_dict(existing_row))


# ---------------------------------------------------------------------------
# PURE HELPER — the projection rule itself, testable without a database
# ---------------------------------------------------------------------------

def derive_paid_state(total_paid: float, grand_total: float) -> str:
    """The invoice status implied by how much has been paid against it.

    Extracted and pure so the rule can be tested exhaustively (including the
    float-boundary cases that decide whether a customer sees "Paid" or is chased
    for a rupee) without standing up two databases.

    ``grand_total <= 0`` cannot be "Paid" by paying nothing — a zero-value
    document is Pending until a real receipt exists, which keeps a malformed or
    half-synced row from silently presenting as settled.
    """
    paid = round(float(total_paid or 0.0), 2)
    grand = round(float(grand_total or 0.0), 2)
    if grand > 0 and paid >= grand:
        return "Paid"
    if paid > 0:
        return "Partial"
    return "Pending"


# ---------------------------------------------------------------------------
# HOOK 1 — invoice paid-state projection
# ---------------------------------------------------------------------------

def reconcile_invoice_paid_state(db, inv) -> bool:
    """Re-derive ``Invoice.paid_amount`` + ``status`` from the payment ledger.

    The ledger is the truth; the two columns on the invoice are a cache of it.
    Recomputing from THIS database's own payment rows — and ignoring whatever
    the peer sent — is what stops a stale device pushing ``paid_amount=0`` /
    ``status=Pending`` and "un-paying" an invoice settled elsewhere.

    Returns True when it actually changed something.

    Leaves the invoice alone when it has NO payment rows here. That covers two
    real cases and must not be mistaken for "unpaid": legacy invoices imported
    with a paid status and no ledger rows, and an invoice that arrived in a
    batch whose payment rows have not applied yet (the pull worker applies
    ``invoice_payments`` last). The payment's own hook corrects it moments later.
    """
    if inv is None or getattr(inv, "id", None) is None:
        return False

    from core.models import InvoicePayment
    from services.dates import utc_now

    total_paid, n = (
        db.query(func.coalesce(func.sum(InvoicePayment.amount_paid), 0.0),
                 func.count(InvoicePayment.id))
        .filter(InvoicePayment.business_id == inv.business_id,
                InvoicePayment.invoice_id == inv.id)
        .one()
    )
    if not n:
        return False

    total_paid = round(total_paid or 0.0, 2)
    grand = round((inv.total_amount or getattr(inv, "amount", 0.0) or 0.0), 2)
    new_status = derive_paid_state(total_paid, grand)

    if round(inv.paid_amount or 0.0, 2) == total_paid and inv.status == new_status:
        return False

    logger.info("[SYNC_HOOKS] corrected invoice #%s biz=%s: %s/%.2f -> %s/%.2f",
                inv.id, inv.business_id, inv.status, (inv.paid_amount or 0.0),
                new_status, total_paid)
    inv.paid_amount = total_paid
    inv.status = new_status
    # Bump updated_at ONLY on a real change, so the correction propagates on the
    # next sync without two peers bouncing an unchanged row back and forth.
    if hasattr(inv, "updated_at"):
        inv.updated_at = utc_now()
    return True


def reconcile_parent_invoice_of_payment(db, pay) -> bool:
    """A payment landed — re-derive its parent invoice's paid state.

    This is the hook that actually fixes the reported bug on a pull: the invoice
    is applied before its payments in the same batch, so reconciling at invoice
    time finds an empty ledger and correctly does nothing. The correction has to
    happen here, when the payment arrives.
    """
    inv_id = getattr(pay, "invoice_id", None)
    if not inv_id:
        return False
    from database.models import Invoice
    inv = (
        db.query(Invoice)
        .filter(Invoice.id == inv_id, Invoice.business_id == pay.business_id)
        .first()
    )
    if inv is None:
        # Parent not here yet (child applied before parent). Not an error: the
        # invoice's own hook reconciles it when it lands, because by then the
        # payment row exists.
        return False
    return reconcile_invoice_paid_state(db, inv)


# ---------------------------------------------------------------------------
# THE ENTRY POINT — both sync paths call exactly this
# ---------------------------------------------------------------------------

def log_financial_conflict(db, *, business_id: int, entity: str, entity_id,
                           incoming: dict, existing_row,
                           incoming_updated_at, existing_updated_at,
                           log_prefix: str = "sync") -> bool:
    """Record a reviewable ConflictLog when a financial row is about to be
    overwritten by a newer concurrent version. Returns True if one was written.

    Call this BEFORE the overwrite — it snapshots the version that is about to
    be lost. LWW behaviour is unchanged; the data still lands. All this does is
    make sure the owner can see that a money record was edited in two places,
    instead of one version disappearing without trace.

    (M-8) Now shared, so it applies to the PULL direction too. It previously
    lived in ``routes/sync.py``, which meant a financial row clobbered by an
    incoming pull was silently lost — the exact failure the push path had
    already been hardened against.
    """
    if not is_financial_overwrite(entity, incoming, existing_row,
                                  incoming_updated_at, existing_updated_at):
        return False
    # Imported at module scope (see the top of this file), NOT here. The first
    # version imported it inside this try block from the WRONG module, and the
    # `except Exception` below turned that ImportError into a silent `return
    # False` — so conflict logging stopped working entirely and said nothing.
    # A silent failure inside the function whose job is removing silent failures.
    # A module-level import fails loudly at startup instead.
    try:
        db.add(ConflictLog(
            business_id=business_id,
            entity=entity,
            entity_id=entity_id,
            local_updated_at=incoming_updated_at,
            cloud_updated_at=existing_updated_at,
            local_payload=json.dumps(incoming, default=str),
            cloud_payload=json.dumps(row_to_dict(existing_row), default=str),
            resolved_at=None,                    # unreviewed
            resolution="review_needed",
        ))
        logger.warning(
            "[SYNC_HOOKS] %s: financial overwrite flagged for review — %s.id=%s "
            "(incoming %s > existing %s)",
            log_prefix, entity, entity_id, incoming_updated_at, existing_updated_at,
        )
        return True
    except Exception as e:
        # Losing the conflict RECORD must not lose the data write, but it must
        # not be quiet either — an unlogged overwrite is the silent-lost-edit
        # this whole mechanism exists to prevent.
        logger.error("[SYNC_HOOKS] %s: FAILED to record conflict for %s.id=%s: %s",
                     log_prefix, entity, entity_id, e, exc_info=True)
        return False


def log_master_data_conflict(
    db, *, business_id: int, entity: str, entity_id,
    incoming: dict, existing_row,
    incoming_updated_at, existing_updated_at,
    resolution: str = "cloud_won",
    log_prefix: str = "sync",
) -> bool:
    """Record a ConflictLog when a non-financial master-data row (products,
    customers, inventory, etc.) is silently overwritten by LWW.

    Financial rows are handled by ``log_financial_conflict`` with resolution
    ``review_needed``. Master-data rows don't need owner review, but the losing
    version should not vanish without trace — it's logged with resolution
    ``cloud_won`` / ``local_won`` so the history is queryable.

    Skips rows where payloads don't actually differ (no-op re-syncs) to avoid
    noise in the audit log.
    """
    if entity in FINANCIAL_ENTITIES:
        return False   # handled by log_financial_conflict with review_needed
    if existing_row is None:
        return False
    if incoming_updated_at is None or existing_updated_at is None:
        return False
    if not payloads_differ(incoming, row_to_dict(existing_row)):
        return False   # identical content — no point logging
    try:
        db.add(ConflictLog(
            business_id=business_id,
            entity=entity,
            entity_id=entity_id,
            local_updated_at=incoming_updated_at,
            cloud_updated_at=existing_updated_at,
            local_payload=json.dumps(incoming, default=str),
            cloud_payload=json.dumps(row_to_dict(existing_row), default=str),
            resolved_at=None,
            resolution=resolution,
        ))
        logger.info(
            "[SYNC_HOOKS] %s: master-data LWW overwrite logged (%s) — %s.id=%s "
            "(incoming %s, existing %s)",
            log_prefix, resolution, entity, entity_id,
            incoming_updated_at, existing_updated_at,
        )
        return True
    except Exception as e:
        logger.error(
            "[SYNC_HOOKS] %s: FAILED to record master-data conflict for %s.id=%s: %s",
            log_prefix, entity, entity_id, e, exc_info=True,
        )
        return False


def run_post_apply(db, entity: str, obj, *, log_prefix: str = "sync") -> ApplyResult:
    """Enforce every post-apply invariant for one just-written synced row.

    Call this from EVERY sync apply path, after the row is flushed and before
    the batch commits. It composes within the caller's transaction.

    Never raises. A failure here concerns one row; letting it propagate would
    abort the batch and stall every row queued behind it. Failures are collected
    on the result and logged at ERROR so they are visible rather than silent.

    Hooks, in order:
      1. invoice paid-state projection (M-7) — must run on both invoices and
         payments, because either can arrive first.
      2. journal re-derivation (M-2) — this database posts its own entry for the
         document that landed.
    """
    result = ApplyResult(entity, getattr(obj, "id", None))
    if obj is None:
        return result

    # ── 1. Paid-state projection ────────────────────────────────────────────
    if entity in PAID_STATE_ENTITIES:
        try:
            if entity == "invoices":
                result.reconciled = reconcile_invoice_paid_state(db, obj)
            else:
                result.reconciled = reconcile_parent_invoice_of_payment(db, obj)
            db.flush()
        except Exception as e:
            logger.error("[SYNC_HOOKS] %s: paid-state reconcile FAILED for %s#%s: %s",
                         log_prefix, entity, result.row_id, e, exc_info=True)
            result.errors.append(f"paid_state: {e}")

    # ── 2. Journal re-derivation ────────────────────────────────────────────
    # Runs AFTER the projection so the entry is posted against the corrected
    # amounts — post_sale reads paid_amount to split Cash vs Accounts Receivable,
    # so posting first would book the wrong side of a settled invoice.
    from core.accounting import repost as _repost
    rp = _repost.repost_synced_row(db, entity, obj, log_prefix=log_prefix)
    result.repost = rp
    if not rp.ok:
        result.errors.append(f"journal: {rp.error}")

    return result


# ---------------------------------------------------------------------------
# HOOK 4 — a row that could not be applied at all (M-12)
# ---------------------------------------------------------------------------

APPLY_FAILED = "apply_failed"


def log_apply_failure(db, *, business_id: int, entity: str, entity_id,
                      payload: dict, error: Exception,
                      log_prefix: str = "sync") -> bool:
    """Record a row that the apply path REJECTED, so it is never silently lost.

    WHY THIS EXISTS (review finding M-12)
    -------------------------------------
    The pull worker wrapped each row in a SAVEPOINT — correct, so one bad row
    cannot roll back the batch — and then handled the failure like this::

        except Exception as row_err:
            logger.warning("[SYNC_WORKER] Pull skip %s id=%s: %s", ...)

    ...after which ``_pull_done`` was incremented by the whole batch length, the
    final progress event broadcast ``done == total`` (clearing the UI banner as a
    clean success) and the pull cursor advanced past the window. So a row that
    failed to apply was:

      · reported only at WARNING, un-aggregated, among ordinary sync chatter;
      · counted as applied;
      · presented to the user as a successful sync;
      · **never re-pulled, because the cursor had moved on.**

    That is permanent, invisible data loss with a green banner — the reported
    symptom "cloud→local sync shows glitches after a successful sync".

    It is also the THIRD instance of the same asymmetry (M-7, M-8, now M-12): the
    push path surfaces its failures to the caller in the response body, and the
    pull path, which no caller inspects, swallowed them. So this lives here, in
    the module both apply paths share (architecture rule 12).

    Recorded as a ``ConflictLog`` row with ``resolution = "apply_failed"``
    deliberately: that table is already exposed by ``GET /api/sync/conflicts``
    with an ``unreviewed_count`` badge, which is exactly the surface a rejected
    row needs. Reusing it means the failure becomes visible in the product
    without a new endpoint, and the mechanism built to stop silent lost EDITS now
    also stops silent lost ROWS.

    Returns True if a record was written. Never raises: this runs inside an
    exception handler, and failing here must not mask the original error — but it
    logs, because a bookkeeping failure inside the function whose job is removing
    silent failures is precisely the trap ``log_financial_conflict`` documents
    above.
    """
    orig = getattr(error, "orig", error)
    detail = str(orig).strip().splitlines()[0] if str(orig).strip() else repr(orig)

    logger.error(
        "[SYNC_HOOKS] %s: row REJECTED and NOT applied — %s id=%s: %s. This row "
        "is missing from this database; it is recorded for review and will be "
        "re-pulled.",
        log_prefix, entity, entity_id, detail,
    )
    try:
        db.add(ConflictLog(
            business_id=business_id,
            entity=entity,
            # entity_id is NOT NULL and an incoming row may have no local id yet.
            entity_id=int(entity_id) if isinstance(entity_id, int) else 0,
            local_updated_at=None,
            cloud_updated_at=None,
            local_payload=json.dumps({"apply_error": detail}, default=str),
            cloud_payload=json.dumps(payload, default=str),
            resolved_at=None,                     # unreviewed
            resolution=APPLY_FAILED,
        ))
        db.flush()
        return True
    except Exception as e:
        logger.error(
            "[SYNC_HOOKS] %s: could not RECORD the rejected row %s id=%s (%s). "
            "The rejection itself is logged above, so the row is not invisible, "
            "but it will not appear in the conflicts review list.",
            log_prefix, entity, entity_id, e,
        )
        return False
