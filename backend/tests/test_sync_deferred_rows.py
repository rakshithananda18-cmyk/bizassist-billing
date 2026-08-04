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
NOTE: the ACK DECISION itself is tested behaviourally in
`tests/test_push_outcome.py`, against the real `PushOutcome` object the worker
uses. What remains here are source-level guards for things that are NOT
observable from behaviour — a silent swallow leaves no trace to assert on, so
the only way to stop one returning is to look at the code.

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


def test_the_count_reflects_what_was_ACKED_not_what_was_SENT():
    """`total_pushed += len(chunk_changes)` is what made the log say
    'Successfully pushed 5 changes' for four applied rows."""
    src = _worker_source()
    assert "total_pushed += len(chunk_changes)" not in src, (
        "the worker is still counting what it sent rather than what landed")
    assert "total_pushed += _acked" in src


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
    # The INSERT statement itself now lives in `queue_row_if_absent` (the shared
    # guard all three raw enqueue sites route through). What this test protects
    # is unchanged: the call that decides whether a sale leaves the device must
    # not have a silent except behind it.
    ins = blk[blk.index("queue_row_if_absent("):]
    assert "pass" not in ins.split("except Exception as e:")[1][:400], (
        "the sync_queue INSERT is swallowing its exception silently again")
    assert "FAILED to queue" in ins
    assert "will NEVER be pushed" in ins
    assert "exc_info=True" in ins


def test_a_serialisation_failure_is_reported():
    """A row queued with payload=NULL is a promise the outbox cannot keep."""
    blk = _queue_change_block()
    ser = blk[blk.index("_serialize_orm_obj"):]
    ser = ser[:ser.index("queue_row_if_absent(")]
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


def test_a_queue_row_with_NO_payload_is_dead_lettered_not_pushed():
    """R-6 GAP, found 2026-07-28.

    The corrupt-payload guard was written for `json.loads` failing. A payload
    that was never there took a different route: `if item.payload:` was simply
    False, `payload_dict` stayed None, and the row was pushed as
    `payload: null`. The cloud applies `data = change.payload or {}` — an empty
    write. For a table with NOT NULL columns that comes back as a rejection;
    for one without, it would create a blank record on a money table.

    Found because a requeue tool inserted outbox rows without a payload, on the
    written-down assumption that the worker rebuilt it. It does not. The
    assumption was asserted rather than read.
    """
    src = _worker_source()
    blk = src[src.index("payload_dict = None"):]
    blk = blk[:blk.index("pairs.append(")]
    assert "if not item.payload:" in blk, (
        "a NULL payload still falls through to the push as payload: null")
    assert "No payload: cannot be pushed" in blk
    # It must dead-letter, exactly like a corrupt payload, not silently skip.
    guard = blk[blk.index("if not item.payload:"):]
    guard = guard[:guard.index("if item.payload:")]
    assert "item.synced_at = utc_now()" in guard
    assert "continue" in guard
    assert "logger.warning" in guard


def test_the_requeue_tool_builds_a_real_payload():
    """It inserted `payload = NULL` and documented that the worker would rebuild
    it. The worker does not. Pinned so the claim cannot come back."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "scripts", "reconcile_local_vs_cloud.py")
    src = open(p, encoding="utf-8").read()
    assert "def _row_payload(" in src
    blk = src[src.index("for uid, rid in f[\"never\"]:"):]
    blk = blk[:blk.index("return reopened, inserted")]
    assert "_row_payload(local, f[\"entity\"], rid)" in blk
    assert "'INSERT', ?, CURRENT_TIMESTAMP)" in blk, (
        "the INSERT must bind a payload, not a literal NULL")
    assert "if payload is None:" in blk, (
        "a row that cannot be read must be declined, not queued empty")


# ══════════════════════════════════════════════════════════════════════════════
# 6. The reconciliation arithmetic — my bug, found in production
# ══════════════════════════════════════════════════════════════════════════════
# First real push after the fix printed:
#   "sent 7, cloud applied 3, deferred 4, rejected 3 - -3 row(s) vanished"
# A NEGATIVE shortfall, which is impossible and was the tell. `applied`
# (processed_count) ALREADY includes rejected rows — routes/sync.py does
# `processed_count += 1  # ack either way` inside the IntegrityError handler —
# so adding `rejected` double-counted. And the cloud had a third acked outcome
# it reported nowhere (unknown entity, LWW cloud-wins), so the sum could not
# close even after removing the double count.

def _reconcile(sent, applied, deferred, rejected, skipped):
    """The corrected invariant: received == applied + deferred + skipped."""
    return sent - (applied + deferred + skipped)


def test_the_cloud_reports_its_deliberate_skips():
    """LWW cloud-wins and unknown-entity used to `continue` silently, so the
    device's arithmetic had a permanent unexplained remainder. Every row must
    land in exactly one bucket."""
    src = _push_source()
    assert "skipped = []" in src
    assert '"skipped": skipped' in src
    assert "unknown entity on this server" in src
    assert "cloud copy is newer (LWW)" in src
    assert "no updated_at; cloud version kept" in src


def test_a_skip_is_reported_at_INFO_not_as_a_failure():
    """A deliberate skip is a correct outcome. Logging it as an error would put
    three different meanings behind one alarming word."""
    blk = _ack_block()
    assert "SKIPPED" in blk
    assert "deliberately (acked, not an error)" in blk


def test_requeue_refreshes_the_payload_it_does_not_only_clear_synced_at():
    """THE LOOP I CREATED, minutes after adding the dead-letter guard.

    A row dead-lettered for having NO payload is ACKED (`synced_at` set), so it
    lands in the requeue tool's "acked but absent" branch. The first version of
    that branch only did `SET synced_at = NULL` — putting the same unusable row
    straight back to be dead-lettered again. Reopen, dead-letter, reopen.

    Refreshing is also more correct in general: the outbox payload is a snapshot
    from write time and a re-push should carry what the row says now.
    """
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                     "scripts", "reconcile_local_vs_cloud.py")
    src = open(p, encoding="utf-8").read()
    blk = src[src.index('for uid, rid in f["acked"]:'):]
    blk = blk[:blk.index('for uid, rid in f["never"]:')]
    assert "_row_payload(local, f[\"entity\"], rid)" in blk, (
        "the reopen path does not rebuild the payload; a payload-less row will "
        "be dead-lettered again on the next cycle, forever")
    assert "SET synced_at = NULL, payload = ?" in blk
    assert "if payload is None:" in blk, (
        "a row that no longer exists locally must not be reopened — there is "
        "nothing to send")
