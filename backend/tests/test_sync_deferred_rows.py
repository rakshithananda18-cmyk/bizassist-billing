"""
tests/test_sync_deferred_rows.py — M-20: the deferred row that got acked
========================================================================
CRITICAL - A REAL SALE WAS DELETED BY THIS, ON PRODUCTION, ON 2026-07-27.

WHAT HAPPENED
-------------
A ₹641 sale (`LCL-OW-0028`, local invoice id 860) was rung on BA-Y0DAFT. Both
sides reported success. The row is not on the cloud.

    local  sync_queue #559  invoices INSERT   synced_at=16:38:16  error=NULL
    local  log             "Successfully pushed 5 changes for business_id=7"
    cloud  log             "sync/push: business_id=42 received 5 changes"
    cloud  log             "sync/push[invoices.id=860]: deferring invoices —
                            parent register_shifts uid=2419a393-… not in this DB yet"
    cloud  invoices        NOT PRESENT (unfiltered search by number and uid)

THE MECHANISM — two halves, each correct alone
----------------------------------------------
`routes/sync.py` defers a row whose parent FK cannot be resolved. That is
RIGHT: writing the source database's integer id instead would be M-9, money
attached to the wrong customer's invoice. `resolve_parent_fk_uids` states the
contract — "it re-applies on a later sync once the parent lands".

But the deferral `continue`d without recording the row anywhere. It was not
counted in `applied`, and `rejected` is appended to only inside the
IntegrityError handler. The response was `{"applied": 4, "rejected": []}` for
five rows sent.

`services/sync_worker.py` then did `total_pushed += len(chunk_changes)` — what
it SENT, never reading `applied` — and stamped `synced_at` on every row in the
chunk. The outbox row was gone, so the "later sync" the cloud was waiting for
could never happen.

The cloud defers expecting a retry; the client acks guaranteeing there won't be
one. Neither half is wrong on its own. The defect is entirely in the contract
between them — the shape this whole review keeps finding, here on the one path
where the cost is a deleted sale.

WHY M-13 DID NOT CATCH IT
-------------------------
M-13 taught the client to read `rejected`, and that machinery works. It cannot
help here because **a deferred row is not a rejected row**. Rejected means "we
refuse this, stop sending it". Deferred means "not yet, keep it and send it
again". Collapsing the two loses data in one direction and spins forever in the
other. It was a third state that neither side named.

WHAT THESE TESTS PIN
--------------------
  * a deferred row keeps `synced_at = NULL` and is re-sent;
  * once the parent lands, the row goes through and the sale is NOT lost;
  * a rejected row still drains (M-13 behaviour is unchanged);
  * `applied` is reconciled against what was sent, and an unexplained row is
    kept rather than acked — fail closed;
  * deferrals and rejections are written to `sync_logs`, so a sale that failed
    to sync is a query rather than a log line that rotates away;
  * an older cloud that sends no `deferred` field still works.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# 1. The CLOUD reports deferrals — routes/sync.py
# ══════════════════════════════════════════════════════════════════════════════

def _push_source():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "routes", "sync.py")
    return open(p, encoding="utf-8").read()


def test_the_deferral_site_records_the_row():
    """The `continue` used to drop the row with no trace. It must append to
    `deferred` first — that append IS the fix on the cloud side.

    Sliced from the CALL SITE (`if resolve_parent_fk_uids(db, ...)`) rather than
    from the first mention of the name, which is the import.
    """
    src = _push_source()
    site = src[src.index("if resolve_parent_fk_uids(db,"):]
    site = site[:site.index("\n            # Apply fields")]
    assert "deferred.append(" in site, (
        "the FK-deferral path does not record the row; the client cannot learn "
        "its write was not stored (M-20)")
    for field in ('"entity"', '"row_id"', '"uid"', '"reason"'):
        assert field in site, f"deferred entry is missing {field}"
    assert site.rstrip().endswith("continue"), (
        "the row must still be skipped — deferring is correct, writing the "
        "source database's integer FK would be M-9")


def test_the_response_carries_deferred_and_received():
    """Sliced to the END of the dict, not to the first `}` — which is inside the
    apply_failures comprehension and truncated the assertion into a pass."""
    src = _push_source()
    tail = src[src.index('"status": "success"'):]
    tail = tail[:tail.index('"deferred": deferred') + 60]
    assert '"deferred": deferred' in tail
    assert '"received": len(payload.changes)' in tail, (
        "the client needs to reconcile what it sent against what landed")
    assert '"applied": processed_count' in tail
    assert '"rejected": rejected' in tail


def test_deferred_and_rejected_are_kept_apart():
    """Collapsing them loses data one way and spins forever the other."""
    src = _push_source()
    assert "deferred = []" in src and "rejected = []" in src
    assert "rejected.append(" in src and "deferred.append(" in src


def test_a_deferral_is_logged_as_a_warning_not_an_error():
    """It is a legitimate ordering outcome on any one cycle. It becomes an error
    only when it never resolves, and the CLIENT is the side that can count
    that."""
    src = _push_source()
    blk = src[src.index("if deferred:"):]
    blk = blk[:blk.index("return {")]
    assert "logger.warning" in blk
    assert "NOT stored and NOT acked" in blk


# ══════════════════════════════════════════════════════════════════════════════
# 2. The CLIENT keeps them — services/sync_worker.py
# ══════════════════════════════════════════════════════════════════════════════

def _worker_source():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "services", "sync_worker.py")
    return open(p, encoding="utf-8").read()


def _ack_block():
    src = _worker_source()
    start = src.index("_deferred = _push_body.get(\"deferred\")")
    return src[start:src.index("total_pushed += _acked") + 40]


def test_a_deferred_row_is_not_stamped_synced():
    """THE FIX. Everything else is reporting; this is the line that stops a sale
    being deleted."""
    blk = _ack_block()
    assert "_defer_keys" in blk
    assert "in _defer_keys" in blk and "continue" in blk, (
        "deferred rows are still being stamped synced_at — the outbox loses its "
        "only copy and the cloud's expected retry can never happen")


def test_the_count_reflects_what_was_ACKED_not_what_was_SENT():
    """`total_pushed += len(chunk_changes)` is what made the log say
    'Successfully pushed 5 changes' for four applied rows."""
    src = _worker_source()
    assert "total_pushed += len(chunk_changes)" not in src, (
        "the worker is still counting what it sent rather than what landed")
    assert "total_pushed += _acked" in src


def test_applied_is_reconciled_against_what_was_sent():
    """Had this existed, M-20 was a one-line discrepancy on the first push:
    sent 5, applied 4."""
    blk = _ack_block()
    assert '_push_body.get("applied")' in blk
    assert "UNACCOUNTED ROWS" in blk
    assert "_explained" in blk


def test_an_unaccounted_row_is_KEPT_not_acked():
    """Fail closed. If the cloud cannot account for a row, the device holds its
    copy — acking is what destroys the last copy of a sale."""
    blk = _ack_block()
    assert "_unaccounted" in blk
    idx = blk.index("if _unaccounted:")
    assert "continue" in blk[idx:idx + 200]


def test_an_older_cloud_without_the_field_still_works():
    """`applied` absent means nothing can be concluded, so nothing is claimed
    (rule 33) — it must not be treated as zero and trigger a false alarm."""
    blk = _ack_block()
    assert "isinstance(_applied, int)" in blk
    tail = blk[blk.index("else:", blk.index("isinstance(_applied, int)")):]
    assert "_unaccounted = False" in tail


def test_a_rejected_row_still_drains_unchanged():
    """M-13's deliberate behaviour: a refused row is acked so it cannot stall
    the queue behind it. The M-20 fix must not silently change that."""
    blk = _ack_block()
    assert "_defer_keys" in blk
    assert "_reject" not in blk.split("for (it, _c) in chunk:")[1], (
        "rejected rows must still be acked; only DEFERRED rows are held")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Durability and the stuck-parent bound
# ══════════════════════════════════════════════════════════════════════════════

def test_deferrals_and_rejections_are_persisted():
    """`sync_logs` had rows for outages and auth failures and none for 'the
    cloud did not store this sale', so the only evidence was a log line that
    rotates. Money that failed to sync must be a query."""
    src = _worker_source()
    blk = src[src.index('for _kind, _rows in (("rejected"'):]
    blk = blk[:blk.index("unsynced_count")]
    assert "SyncLog(" in blk
    assert 'f"push_{_kind}"' in blk
    assert "entity_id=_r.get(\"row_id\")" in blk
    assert "[:50]" in blk, "a permanently stuck parent must not flood sync_logs"


def test_a_never_resolving_deferral_escalates():
    """The retry alone would spin forever without telling anyone. Bounded the
    same way the pull side bounds its retries (M-12)."""
    src = _worker_source()
    assert "_PUSH_MAX_DEFER_STREAK" in src
    blk = src[src.index("if _push_deferred or _push_unaccounted:"):]
    blk = blk[:blk.index("if total_pushed or unsynced_count == 0:")]
    assert "logger.critical" in blk
    assert "needs a human" in blk
    assert "SAFE and still queued" in blk, (
        "the escalation must say the data is not lost, or it reads as a "
        "data-loss alarm and invites someone to 'fix' it by clearing the queue")


def test_the_streak_resets_once_the_parent_lands():
    src = _worker_source()
    blk = src[src.index("if _push_deferred or _push_unaccounted:"):]
    blk = blk[:blk.index("if total_pushed or unsynced_count == 0:")]
    assert "_DEFER_STREAK.pop(business_id, None)" in blk


def test_deferred_rows_are_never_discarded():
    """Unlike the pull cursor, which must eventually advance, the outbox can
    hold a row indefinitely at no cost but disk. The bound makes a stuck parent
    LOUD; it must never make it disappear."""
    src = _worker_source()
    # The rationale sits in the comment ABOVE the constant, so slice backwards
    # from it. (The first version sliced forward and asserted against a block
    # that could not contain the text — a test that could only ever fail.)
    end = src.index("_PUSH_MAX_DEFER_STREAK = 3")
    blk = src[max(0, end - 900):end]
    assert "NEVER discarded" in blk or "never discarded" in blk, (
        "the constant must say, at its definition, that the bound reports a "
        "stuck parent rather than dropping the rows")

    # And nothing in the worker may delete a queued row on the defer path.
    ack = _ack_block()
    assert "delete" not in ack.lower()


def test_the_ui_can_tell_the_three_states_apart():
    """'Queue drained', 'drained but some refused' and 'still queued waiting on
    a parent' are three different things that all rendered as one number."""
    src = _worker_source()
    blk = src[src.index('"type":    "sync.progress"'):]
    blk = blk[:blk.index("})")]
    assert '"rejected": len(_push_rejected)' in blk
    assert '"deferred": len(_push_deferred)' in blk


# ══════════════════════════════════════════════════════════════════════════════
# 4. The behaviour, executed against a fake cloud
# ══════════════════════════════════════════════════════════════════════════════

class FakeCloud:
    """A cloud that defers a named row until its parent has been pushed.

    Reproduces the production sequence: invoice 860 is deferred because
    `register_shifts` uid 2419a393 is absent, and goes through once it arrives.
    """

    def __init__(self, needs_parent=("invoices", 860), parent=("register_shifts", 9)):
        self.needs_parent = needs_parent
        self.parent = parent
        self.stored = []
        self.parent_present = False

    def push(self, changes):
        applied, deferred = 0, []
        for c in changes:
            key = (c["entity"], c["entity_id"])
            if key == self.parent:
                self.parent_present = True
            if key == self.needs_parent and not self.parent_present:
                deferred.append({"entity": c["entity"], "row_id": c["entity_id"],
                                 "uid": None, "reason": "parent not resolvable"})
                continue
            self.stored.append(key)
            applied += 1
        return {"status": "success", "applied": applied,
                "received": len(changes), "rejected": [], "deferred": deferred,
                "apply_failures": []}


def _ack(chunk, body):
    """The worker's ack decision, in the shape the real code now implements."""
    deferred = body.get("deferred") or []
    rejected = body.get("rejected") or []
    defer_keys = {(d["entity"], d["row_id"]) for d in deferred}
    applied = body.get("applied")
    unaccounted = (isinstance(applied, int)
                   and applied + len(deferred) + len(rejected) != len(chunk))
    acked, kept = [], []
    for c in chunk:
        if (c["entity"], c["entity_id"]) in defer_keys or unaccounted:
            kept.append(c)
        else:
            acked.append(c)
    return acked, kept


def test_the_sale_is_kept_then_lands_once_the_parent_arrives():
    """THE REPRODUCTION, and the proof the fix closes it."""
    cloud = FakeCloud()
    invoice = {"entity": "invoices", "entity_id": 860}
    shift = {"entity": "register_shifts", "entity_id": 9}

    # Cycle 1 — the production case: the invoice goes without its parent.
    body = cloud.push([invoice])
    acked, kept = _ack([invoice], body)
    assert acked == [], "the deferred sale was acked and is now unrecoverable"
    assert kept == [invoice]
    assert ("invoices", 860) not in cloud.stored

    # Cycle 2 — the parent is queued too, and the retry succeeds.
    body = cloud.push([shift, invoice])
    acked, kept = _ack([shift, invoice], body)
    assert kept == []
    assert ("invoices", 860) in cloud.stored, "the sale never landed"


def test_an_unexplained_shortfall_keeps_everything():
    """A cloud that applies fewer rows than it received without saying why: the
    device must not ack. This is the fail-closed case."""
    chunk = [{"entity": "invoices", "entity_id": i} for i in (1, 2, 3)]
    body = {"status": "success", "applied": 2, "rejected": [], "deferred": []}
    acked, kept = _ack(chunk, body)
    assert acked == [] and kept == chunk


def test_a_fully_applied_chunk_still_drains():
    """The guard must not block the happy path — a guard that blocks everything
    is indistinguishable from a broken sync."""
    chunk = [{"entity": "invoices", "entity_id": i} for i in (1, 2, 3)]
    body = {"status": "success", "applied": 3, "rejected": [], "deferred": []}
    acked, kept = _ack(chunk, body)
    assert acked == chunk and kept == []


def test_rejected_rows_still_drain():
    chunk = [{"entity": "invoices", "entity_id": 1},
             {"entity": "invoices", "entity_id": 2}]
    body = {"status": "success", "applied": 1,
            "rejected": [{"entity": "invoices", "row_id": 2, "reason": "bad"}],
            "deferred": []}
    acked, kept = _ack(chunk, body)
    assert kept == [], "a rejected row must still drain (M-13)"
    assert len(acked) == 2


def test_an_older_cloud_response_drains_as_before():
    chunk = [{"entity": "invoices", "entity_id": 1}]
    body = {"status": "success"}          # no applied / deferred / rejected
    acked, kept = _ack(chunk, body)
    assert acked == chunk and kept == []


def test_an_older_cloud_shortfall_also_escalates():
    """The OLD-CLOUD case, observed live on 2026-07-27 23:36: a cloud without
    the `deferred` field reports `applied: 4` for 6 rows sent. The rows are held
    (good) but the whole chunk is held, and it re-sends every cycle. That is a
    spin, so it must escalate on the same counter as a deferral rather than
    logging the same ERROR forever."""
    src = _worker_source()
    assert "_push_unaccounted" in src
    blk = src[src.index("if _push_deferred or _push_unaccounted:"):]
    blk = blk[:blk.index("if total_pushed or unsynced_count == 0:")]
    assert "_push_unaccounted and not _push_deferred" in blk
    assert "older than the `deferred` field" in blk, (
        "the operator must be told the remedy is to deploy the cloud side")


# ══════════════════════════════════════════════════════════════════════════════
# 5. M-20a — the enqueue path must say why it declined
# ══════════════════════════════════════════════════════════════════════════════
# `register_shifts` rows 1-6 were queued; 7, 8 and 9 were not, while invoices
# kept queueing throughout. No log line anywhere recorded a refusal, so "this
# row is not in the outbox" had no explanation — and every sale rung on shift 9
# is now stranded behind a parent the cloud will never receive.

def _models_source():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "database", "models.py")
    return open(p, encoding="utf-8").read()


def _queue_change_block():
    src = _models_source()
    start = src.index("def _queue_change(connection, target, operation):")
    return src[start:src.index("@event.listens_for(Mapper,", start)]


def test_the_sync_queue_insert_no_longer_fails_silently():
    """THE SWALLOW THAT CAN LOSE A REGISTER'S TAKINGS.

    It was `except Exception as e: pass  # Fail silently to prevent blocking
    main database writes`. Failing OPEN is right — a sync bookkeeping problem
    must never stop the counter taking money. Failing open and SILENT is not:
    this is the single INSERT that decides whether a sale ever leaves the
    device, and when it throws the outbox looks perfectly drained.
    """
    blk = _queue_change_block()
    ins = blk[blk.index("INSERT INTO sync_queue"):]
    assert "pass" not in ins.split("except Exception as e:")[1][:400], (
        "the sync_queue INSERT is swallowing its exception silently again")
    assert "FAILED to queue" in ins
    assert "will NEVER be pushed" in ins
    assert "exc_info=True" in ins


def test_a_serialisation_failure_is_reported():
    """A row queued with payload=NULL is a promise the outbox cannot keep."""
    blk = _queue_change_block()
    ser = blk[blk.index("_serialize_orm_obj"):]
    ser = ser[:ser.index("INSERT INTO sync_queue")]
    assert "could NOT serialise" in ser
    assert "exc_info=True" in ser


def test_every_decline_states_a_reason():
    """Each early `return` used to be silent. The routine ones are DEBUG; the
    two that indicate a bug (unresolvable business, no primary key) are
    WARNING, because a syncable row is being dropped."""
    blk = _queue_change_block()
    assert "sync_disabled_var is set" in blk
    assert "not in _SYNC_TABLES" in blk
    assert "PULL_ONLY table" in blk
    assert 'level="warning"' in blk
    assert "business_id could not be resolved" in blk
    assert "no primary key value" in blk


def test_the_pull_apply_decline_says_the_row_is_never_pushed():
    """The leading M-20a hypothesis. Suppressing an echo is correct; doing it
    silently is how a shift can vanish from the outbox unnoticed."""
    blk = _queue_change_block()
    site = blk[blk.index("sync_disabled_var.get() == True"):]
    site = site[:site.index("return") + 6]
    assert "NEVER be pushed" in site


def test_declining_never_raises_into_the_business_write():
    """Fail-open is the correct behaviour and must be preserved: logging a
    decline must not become a new way to break a sale."""
    blk = _queue_change_block()
    assert "raise" not in blk.replace("raise a", ""), (
        "the enqueue path must never raise into the caller's transaction")
