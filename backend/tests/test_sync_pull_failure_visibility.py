"""
tests/test_sync_pull_failure_visibility.py — review finding M-12.
================================================================
A row the cloud→local pull cannot apply must never disappear quietly.

THE DEFECT, as it was
--------------------
The pull worker wrapped every row in a SAVEPOINT — correct, so one bad row cannot
roll back the batch — and then::

    except Exception as row_err:
        logger.warning("[SYNC_WORKER] Pull skip %s id=%s: %s", ...)

…after which:

  1. ``_pull_done`` was incremented by ``len(records)`` regardless of how many
     rows in the batch had failed;
  2. the final progress event broadcast ``done == total``, which is what clears
     the UI banner **as a clean success**;
  3. ``_PULL_CURSOR[business_id] = _cloud_cursor`` advanced unconditionally, so
     the rejected row was **never re-pulled.**

Net effect: permanent, invisible data loss behind a green "sync complete" — the
reported symptom, *"cloud to local sync saw many glitches after successful
sync"*. It also became more likely, not less, with the N4 work: foreign-key
enforcement, six money invariants and the M-11 unique index all make the apply
path REJECT rows it would previously have written.

Third instance of one asymmetry (M-7, M-8, M-12): the push path returns its
failures in the response body where a caller can see them; the pull path, which
no caller inspects, swallowed them. So the fix lives in ``core/sync/apply_hooks``,
which both paths share (architecture rule 12).
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import inspect
import json
from datetime import timedelta

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database.db import Base, SessionLocal, sync_disabled_var
from database.models import ConflictLog, Customer, StockLedger, SyncInbox, User
from core.sync import apply_hooks
import services.sync_worker as SW
from services.dates import utc_now


@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture()
def biz(db):
    u = User(username=f"m12_{uuid.uuid4().hex[:10]}", password="x",
             business_name="M12 Co", role="owner")
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u.id
    db.query(ConflictLog).filter(ConflictLog.business_id == u.id).delete()
    db.commit()
    db.delete(u)
    db.commit()


# ── The recorder ─────────────────────────────────────────────────────────────

def test_a_rejected_row_is_recorded_for_review(db, biz):
    """The row is gone from this database, so the ONLY thing standing between the
    owner and silent data loss is this record."""
    payload = {"id": 4242, "business_id": biz, "amount_paid": -5}
    wrote = apply_hooks.log_apply_failure(
        db, business_id=biz, entity="invoice_payments", entity_id=4242,
        payload=payload, error=ValueError("CHECK constraint failed"),
        log_prefix="[TEST]")
    db.commit()
    assert wrote is True

    row = db.query(ConflictLog).filter(
        ConflictLog.business_id == biz,
        ConflictLog.entity == "invoice_payments").one()
    assert row.resolution == apply_hooks.APPLY_FAILED
    assert row.resolved_at is None, "must start UNREVIEWED so the badge counts it"
    assert "CHECK constraint failed" in row.local_payload
    assert "4242" in row.cloud_payload, (
        "the incoming payload must be preserved — it is the only copy of the row "
        "that did not land"
    )


def test_the_incoming_payload_is_kept_verbatim(db, biz):
    """Without the payload the record says 'something failed' and nothing else,
    which is not a recovery path."""
    payload = {"id": 7, "business_id": biz, "invoice_id": 99,
               "amount_paid": 1234.56, "payment_mode": "cash"}
    apply_hooks.log_apply_failure(
        db, business_id=biz, entity="invoice_payments", entity_id=7,
        payload=payload, error=ValueError("FOREIGN KEY constraint failed"))
    db.commit()
    row = db.query(ConflictLog).filter(ConflictLog.business_id == biz).one()
    import json
    assert json.loads(row.cloud_payload)["amount_paid"] == 1234.56


def test_it_surfaces_through_the_existing_conflicts_endpoint(db, biz):
    """Deliberate reuse of ConflictLog: `GET /api/sync/conflicts` already exposes
    it with an `unreviewed_count` badge, so a rejected row becomes visible in the
    product without a new endpoint. Asserted so a future refactor cannot move it
    somewhere nothing reads."""
    apply_hooks.log_apply_failure(
        db, business_id=biz, entity="invoices", entity_id=1,
        payload={"id": 1}, error=ValueError("boom"))
    db.commit()
    unreviewed = db.query(ConflictLog).filter(
        ConflictLog.business_id == biz,
        ConflictLog.resolved_at.is_(None)).count()
    assert unreviewed == 1


def test_a_non_integer_row_id_does_not_break_recording(db, biz):
    """An incoming row may have no local integer id yet. `entity_id` is NOT NULL,
    so this must degrade to 0 rather than raise — losing the record would restore
    the exact silence this closes."""
    assert apply_hooks.log_apply_failure(
        db, business_id=biz, entity="invoices", entity_id=None,
        payload={"uid": "abc"}, error=ValueError("x")) is True
    db.commit()
    assert db.query(ConflictLog).filter(
        ConflictLog.business_id == biz).one().entity_id == 0


def test_recording_never_raises(db, biz):
    """It runs inside an exception handler. If it raised it would mask the
    original error — the failure would become MORE obscure, not less."""
    apply_hooks.log_apply_failure(
        db, business_id=biz, entity="invoices", entity_id=1,
        payload={"unserialisable": object()}, error=ValueError("x"))
    # No assertion on the return value: the point is that nothing propagated.


# ── The wiring: the pull path must actually use it ────────────────────────────

def test_pull_worker_records_rejected_rows():
    """Drift guard. A recorder nobody calls is a comment (rule 16)."""
    src = inspect.getsource(SW)
    assert "log_apply_failure" in src, (
        "services/sync_worker.py no longer records rejected rows — M-12 has "
        "regressed and rows are being skipped silently again"
    )


def test_pull_worker_no_longer_merely_warns_and_skips():
    """The literal string of the old behaviour. Asserted because the failure mode
    was not a missing feature, it was a log line standing in for one."""
    src = inspect.getsource(SW)
    assert "Pull skip" not in src, (
        "the old warn-and-forget handler is back in the pull path"
    )


def test_done_count_excludes_rejected_rows():
    """`done == total` is what clears the banner. Counting `len(records)`
    unconditionally is what put a green banner over missing data."""
    src = inspect.getsource(SW)
    assert "_pull_done += len(records)" not in src, (
        "the pull progress counter counts whole batches again, so a batch with "
        "dropped rows will report 100%"
    )


def test_the_cursor_is_not_advanced_unconditionally():
    """The cursor is the difference between 'retried' and 'lost'."""
    src = inspect.getsource(SW)
    assert "_PULL_FAILED_STREAK" in src, (
        "the pull cursor no longer tracks failures — a rejected row will be "
        "skipped forever"
    )
    # The bound matters as much as the hold: an unappliable row must not stall
    # every later row behind it indefinitely.
    assert "_PULL_MAX_FAILED_STREAK" in src
    assert SW._PULL_MAX_FAILED_STREAK >= 2, "retry at least once before giving up"
    assert SW._PULL_MAX_FAILED_STREAK <= 10, (
        "an unbounded-ish retry re-introduces the outbox stall the per-row "
        "SAVEPOINT exists to prevent"
    )


def test_failure_state_is_declared_at_function_scope():
    """The cursor decision reads the failure list on every path, including the
    ones where the pull block never ran. Declared inside the block, a NameError
    there would be caught by the outer handler and turn the guard back into a
    silent skip — which is the bug, restored."""
    src = inspect.getsource(SW._sync_business_impl)
    body = src.split("\n")
    decl = next((i for i, l in enumerate(body)
                 if "_pull_row_failures: list = []" in l), None)
    assert decl is not None, "_pull_row_failures is not declared at function scope"
    use = next(i for i, l in enumerate(body) if "_failed_now" in l)
    assert decl < use


def test_progress_event_reports_a_failure_count():
    """The UI cannot stop lying about a partial sync if it is never told."""
    src = inspect.getsource(SW)
    assert '"failed":' in src, (
        "the pull progress event carries no failure count, so a partial sync is "
        "indistinguishable from a clean one at the surface the user sees"
    )


# ── Both directions, one module ──────────────────────────────────────────────

def test_the_recorder_lives_in_the_shared_hook_module():
    """M-7's lesson: an invariant private to one of the two apply paths is
    enforced in one direction only. This must not migrate into sync_worker."""
    assert hasattr(apply_hooks, "log_apply_failure")
    assert inspect.getmodule(apply_hooks.log_apply_failure) is apply_hooks


# ── M-13: the PUSH path acked rows the cloud had rejected ────────────────────
#
# The mirror image of M-12, and in one respect worse: M-12 lost cloud→local rows,
# this lost LOCAL→CLOUD rows — the shop's own sales.
#
# routes/sync.py's IntegrityError handler ended:
#
#     processed_count += 1  # ack either way so it isn't re-sent every cycle
#
# reached whether or not the uid-dedupe had actually resolved anything. When
# `deduped == "skipped"` the IntegrityError was NOT a uid collision — no uid on the
# payload, no uid column, or no existing row carrying it — so the constraint that
# fired was something else: a foreign key, one of the N4 money CHECKs, or the M-11
# one-open-shift index. The row landed nowhere, was logged at INFO, and was acked,
# so the device's outbox dropped it permanently.
#
# The N4 work made this far more reachable: constraints that did not exist before
# now reject rows that previously inserted.
#
# The ack STAYS — refusing it would stall the outbox behind a row that can never
# apply, the same poison-row trade the per-row SAVEPOINT and
# _PULL_MAX_FAILED_STREAK already make. What changed is that it is no longer
# silent.

import routes.sync as RS


@pytest.fixture
def push_db():
    """Exercise the real apply path without another test's persisted records."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    token = sync_disabled_var.set(True)
    session.add(User(id=7, username="push-review-owner", public_id="PUSH-REVIEW-BIZ",
                     role="enterprise", password="synthetic"))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        sync_disabled_var.reset(token)
        engine.dispose()


def _push(db, changes):
    changes = [dict(change, created_at=utc_now().isoformat()) for change in changes]
    return RS.push_changes(RS.PushPayload(changes=changes), BackgroundTasks(), db=db,
        current_user={"id": 7, "user_id": 7, "username": "push-review-owner",
                      "public_id": "PUSH-REVIEW-BIZ", "role": "enterprise"},
        _plan={"plan": "pro"})


def test_push_constraint_rejection_is_recorded_and_other_rows_commit(push_db):
    changes = [
        {"entity": "stock_ledger", "entity_id": 81, "operation": "INSERT", "payload": {
            "uid": "invalid-movement", "business_id": 7, "product_name": "Rice",
            "movement_type": "opening", "qty_delta": None, "updated_at": utc_now().isoformat()}},
        {"entity": "customers", "entity_id": 82, "operation": "INSERT", "payload": {
            "uid": "valid-customer", "business_id": 7, "name": "Alice",
            "updated_at": utc_now().isoformat()}},
    ]
    result = _push(push_db, changes)
    assert result["status"] == "success"
    assert result["received"] == result["applied"] == 2
    assert len(result["rejected"]) == 1
    assert result["rejected"][0]["uid"] == "invalid-movement"
    assert push_db.query(StockLedger).count() == 0
    assert push_db.query(Customer).one().name == "Alice"
    review = push_db.query(ConflictLog).one()
    assert review.resolution == "apply_failed"
    assert json.loads(review.cloud_payload)["uid"] == "invalid-movement"
    assert SW.PushOutcome(changes, result).is_clean


def test_push_uid_replay_is_idempotent_and_keeps_newer_record(push_db):
    stamp = utc_now() - timedelta(days=1)
    change = {"entity": "customers", "entity_id": 9999, "operation": "INSERT", "payload": {
        "uid": "replayed-customer", "business_id": 7, "name": "Alice", "updated_at": stamp.isoformat()}}
    for _ in range(2):
        result = _push(push_db, [change])
        assert result["applied"] == 1
        assert not result["rejected"]
    row = push_db.query(Customer).one()
    assert row.id != change["entity_id"]
    assert row.uid == change["payload"]["uid"]
    older = dict(change, payload=dict(change["payload"], name="Stale name",
                                     updated_at=(stamp - timedelta(days=1)).isoformat()))
    result = _push(push_db, [older])
    assert result["applied"] == 0
    assert len(result["skipped"]) == 1
    assert not result["rejected"]
    assert push_db.query(Customer).one().name == "Alice"


@pytest.mark.parametrize("supplied_owner", ["omitted", None, 42])
def test_push_assigns_verified_business_even_when_payload_omits_owner(push_db, supplied_owner):
    payload = {"uid": "scoped-insert", "name": "Visible to owner",
               "updated_at": utc_now().isoformat()}
    if supplied_owner != "omitted":
        payload["business_id"] = supplied_owner
    result = _push(push_db, [{"entity": "customers", "entity_id": 991,
                             "operation": "INSERT", "payload": payload}])
    assert result["applied"] == 1
    assert not result["rejected"]
    assert push_db.query(Customer).one().business_id == 7
    pulled = RS.pull_changes(current_user={"username": "push-review-owner",
        "public_id": "PUSH-REVIEW-BIZ", "role": "enterprise"},
        _plan={"plan": "pro"}, db=push_db)
    assert [row["uid"] for row in pulled["changes"]["customers"]] == ["scoped-insert"]


def test_push_failed_hook_keeps_repair_and_client_outbox_until_retry(push_db, monkeypatch):
    change = {"entity": "stock_ledger", "entity_id": 89, "operation": "INSERT", "payload": {
        "uid": "repair-movement", "business_id": 7, "product_name": "Rice",
        "movement_type": "opening", "qty_delta": 10, "updated_at": utc_now().isoformat()}}
    failed = apply_hooks.ApplyResult("stock_ledger", 89)
    failed.errors.append("Temporary derived-state failure")
    with monkeypatch.context() as patch:
        patch.setattr(apply_hooks, "run_post_apply", lambda *args, **kwargs: failed)
        result = _push(push_db, [change])
    assert result["applied"] == 0
    assert len(result["apply_failures"]) == len(result["deferred"]) == 1
    assert SW.PushOutcome([change], result).should_hold("stock_ledger", 89)
    repair = push_db.query(SyncInbox).one()
    assert repair.applied_at is None
    assert json.loads(repair.payload)["_sync_repair_only"] is True
    assert push_db.query(StockLedger).one().qty_delta == 10
    result = _push(push_db, [change])
    assert result["applied"] == 1
    assert not result["deferred"]
    assert push_db.query(StockLedger).count() == 1
    assert push_db.query(SyncInbox).one().applied_at is not None


def test_equal_version_financial_refusal_remains_reviewable(push_db):
    stamp = utc_now() - timedelta(days=1)
    row = StockLedger(business_id=7, uid="equal-review", product_name="Rice",
                      movement_type="opening", qty_delta=10, updated_at=stamp)
    push_db.add(row)
    push_db.commit()
    result = _push(push_db, [{"entity": "stock_ledger", "entity_id": 19, "operation": "UPDATE",
        "payload": {"uid": row.uid, "qty_delta": 20, "updated_at": stamp.isoformat()}}])
    assert len(result["rejected"]) == 1
    assert push_db.query(StockLedger).one().qty_delta == 10
    review = push_db.query(ConflictLog).one()
    assert review.resolution == "review_needed"
    assert json.loads(review.local_payload)["qty_delta"] == 20
    assert json.loads(review.cloud_payload)["qty_delta"] == 10


def test_pulled_equal_version_financial_conflict_is_reviewed_once(push_db):
    stamp = utc_now() - timedelta(days=1)
    row = StockLedger(business_id=7, uid="pull-equal-review", product_name="Rice",
                      movement_type="opening", qty_delta=10, updated_at=stamp)
    push_db.add(row)
    push_db.commit()
    result = SW._apply_pulled_row(push_db, 7, "stock_ledger", StockLedger,
        {"id": 999, "uid": row.uid, "qty_delta": 20, "updated_at": stamp.isoformat()})
    push_db.commit()
    assert result.reason == "version-conflict"
    assert push_db.query(StockLedger).one().qty_delta == 10
    review = push_db.query(ConflictLog).one()
    assert review.resolution == "review_needed"
    assert json.loads(review.local_payload)["qty_delta"] == 10
    assert json.loads(review.cloud_payload)["qty_delta"] == 20


def test_the_push_client_reads_the_rejected_field():
    """Reporting into a response nobody reads is the same silence one layer up."""
    src = inspect.getsource(SW)
    assert '"rejected"' in src or "'rejected'" in src, (
        "services/sync_worker.py ignores the cloud's `rejected` list, so a "
        "refused write is invisible on the device too"
    )
    assert "_push_rejected" in src


def test_no_stray_non_ascii_in_the_sync_modules():
    """Housekeeping with a reason: an editing slip left a CJK character inside a
    comment in this module earlier in this pass. On a Windows console with a
    non-UTF-8 code page that can turn a log line or a traceback into a
    UnicodeEncodeError — a silent-failure source in the module whose job is
    removing them."""
    for mod in (SW, RS, apply_hooks):
        src = inspect.getsource(mod)
        bad = [(i + 1, line) for i, line in enumerate(src.split("\n"))
               if any(ord(ch) > 0x2500 for ch in line)]
        assert not bad, f"{mod.__name__} has stray non-ASCII: {bad[:3]}"
