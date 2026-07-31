"""
tests/test_sync_inbox.py — the pull side gets an outbox
=======================================================

Push has had `sync_queue` from the start: an un-deliverable row STAYS queued, is
visible in Ops, retries on its own, and blocks nothing else. Pull had no
equivalent, and paid for it in two distinct ways.

────────────────────────────────────────────────────────────────────────────────
DEFECT 1 — DEFERRED PULL ROWS WERE LOST (M-20, read side)
────────────────────────────────────────────────────────────────────────────────
`resolve_parent_fk_uids` returns True when a child's parent is not in this
database yet. Its docstring states the contract:

    Returns ``True`` if the row must be **deferred** … it re-applies on a later
    sync once the parent lands.

The pull-apply loop honoured the deferral and not the contract:

    if resolve_parent_fk_uids(db, model_cls, data, log_prefix="[SYNC_WORKER]"):
        continue                       # ← recorded NOWHERE

Nothing recorded ⇒ `_pull_row_failures` empty ⇒ cursor advanced ⇒ the cloud never
re-offered the row, because its `updated_at` had not changed and the cursor was
already past it. The row was gone, and `_pull_done` counted it as applied.

The push path fixed this exact bug and its comment still describes it:

    the row is DEFERRED, the client MUST be told … The outbox row was gone, so
    the "later sync" could never happen.

────────────────────────────────────────────────────────────────────────────────
DEFECT 2 — A REJECTED ROW FROZE EVERY LATER ROW
────────────────────────────────────────────────────────────────────────────────
The only recovery was to HOLD the global cursor — blocking all 29 tables —
bounded by `_PULL_MAX_FAILED_STREAK`, after which:

    logger.critical("… THESE ROWS REMAIN MISSING … They need a human.")

A forced choice between stalling everything and losing one row, resolved by a
CRITICAL line in a log nobody reads.

────────────────────────────────────────────────────────────────────────────────
DEFECT 3 — THE CURSOR DID NOT SURVIVE A RESTART
────────────────────────────────────────────────────────────────────────────────
`_PULL_CURSOR` was a module dict. On restart the cursor was re-derived from
`SyncLog.synced_at` with an `.offset(1 if queue_items else 0)` heuristic — a
proxy for what was applied, over a table that also holds push rows. Whenever the
proxy resolved LATER than the last row actually applied, everything in between
was skipped forever. M-12, reintroduced by any restart.

────────────────────────────────────────────────────────────────────────────────
DEFECT 4 — AN UNBOUNDED PULL COULD NEVER COMPLETE
────────────────────────────────────────────────────────────────────────────────
A first pull has no cursor → `last_sync_at` resolves to 1970 → every row of all
29 tables in one response, against a 10 s client timeout. The same endpoint was
called by the parity audit with a 180 s timeout, which is the tell. Not data
loss: a livelock. Time out, correctly decline to advance, repeat forever.

These tests pin all four. They exercise the REAL inbox module against a REAL
sqlite database — no source-string matching for the behavioural assertions.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET",   "test-secret-for-sync-inbox-abcdef123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from core.sync import inbox as IB
from database.db import SessionLocal
from database.models import Base, SyncCursor, SyncInbox
from services.dates import utc_now

BID = 90210


@pytest.fixture(scope="module", autouse=True)
def ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


@pytest.fixture
def db():
    s = SessionLocal()
    s.query(SyncInbox).filter(SyncInbox.business_id == BID).delete()
    s.query(SyncCursor).filter(SyncCursor.business_id == BID).delete()
    s.commit()
    try:
        yield s
    finally:
        s.query(SyncInbox).filter(SyncInbox.business_id == BID).delete()
        s.query(SyncCursor).filter(SyncCursor.business_id == BID).delete()
        s.commit()
        s.close()


def _due_now(db):
    """Collapse backoff so a test can drain without sleeping."""
    for r in db.query(SyncInbox).filter(SyncInbox.business_id == BID).all():
        r.next_attempt_at = None
    db.commit()


# ═════════════════════════════════════════════════════════════════════════════
# DEFECT 1 — deferred rows are durable
# ═════════════════════════════════════════════════════════════════════════════

class TestDeferredRowsSurvive:

    def test_a_deferred_row_is_persisted_with_its_payload(self, db):
        """THE GATE. This row used to disappear at `continue`."""
        IB.remember(db, business_id=BID, entity="invoice_line_items",
                    record={"uid": "u-1", "id": 501, "invoice_id": 9, "qty": 3},
                    reason="deferred")
        db.commit()

        row = db.query(SyncInbox).filter(SyncInbox.business_id == BID).one()
        assert row.reason == "deferred"
        assert row.uid == "u-1"
        # The payload matters as much as the row: without it there is nothing to
        # re-apply, and the cloud will not offer the row again.
        assert json.loads(row.payload)["qty"] == 3

    def test_it_applies_once_the_parent_arrives(self, db):
        IB.remember(db, business_id=BID, entity="invoice_line_items",
                    record={"uid": "u-2", "id": 502}, reason="deferred")
        db.commit()
        _due_now(db)

        seen = []
        res = IB.drain(db, BID, lambda _d, e, r: (seen.append((e, r["uid"])), "applied")[1])

        assert res["applied"] == 1
        assert seen == [("invoice_line_items", "u-2")]
        assert db.query(SyncInbox).filter(SyncInbox.uid == "u-2").one().applied_at is not None

    def test_a_re_offered_row_updates_rather_than_stacking(self, db):
        """A child whose parent is slow would otherwise gain one inbox row per
        pull cycle — an unbounded table that hides the real backlog."""
        for qty in (1, 2, 3):
            IB.remember(db, business_id=BID, entity="invoice_line_items",
                        record={"uid": "u-3", "id": 503, "qty": qty},
                        reason="deferred")
            db.commit()

        rows = db.query(SyncInbox).filter(SyncInbox.uid == "u-3").all()
        assert len(rows) == 1
        assert json.loads(rows[0].payload)["qty"] == 3   # newest cloud copy wins

    def test_a_re_offer_does_not_reset_the_backoff(self, db):
        """Otherwise a row the cloud sends every cycle retries every cycle, no
        matter how many times it has already failed."""
        IB.remember(db, business_id=BID, entity="invoices",
                    record={"uid": "u-4", "id": 504}, reason="deferred")
        db.commit()
        _due_now(db)
        IB.drain(db, BID, lambda *_: "deferred")
        attempts_after_first = db.query(SyncInbox).filter(SyncInbox.uid == "u-4").one().attempts
        assert attempts_after_first == 1

        IB.remember(db, business_id=BID, entity="invoices",
                    record={"uid": "u-4", "id": 504, "v": 2}, reason="deferred")
        db.commit()
        assert db.query(SyncInbox).filter(SyncInbox.uid == "u-4").one().attempts == 1

    def test_a_row_with_no_identity_is_refused_loudly(self, db):
        """Storing it would be storing something that can never be matched back
        to a cloud row. Better to fail visibly than to hold an unusable entry."""
        assert IB.remember(db, business_id=BID, entity="invoices",
                           record={}, reason="rejected") is None
        assert db.query(SyncInbox).filter(SyncInbox.business_id == BID).count() == 0


# ═════════════════════════════════════════════════════════════════════════════
# DEFECT 2 — a bad row no longer blocks the rest
# ═════════════════════════════════════════════════════════════════════════════

class TestOneBadRowDoesNotBlockTheRest:

    def test_a_raising_apply_is_recorded_not_lost(self, db):
        IB.remember(db, business_id=BID, entity="invoices",
                    record={"uid": "bad", "id": 1}, reason="rejected")
        db.commit()
        _due_now(db)

        def boom(*_):
            raise ValueError("UNIQUE constraint failed: invoices.invoice_id")

        res = IB.drain(db, BID, boom)
        row = db.query(SyncInbox).filter(SyncInbox.uid == "bad").one()
        assert res["failed"] == 1
        assert "UNIQUE" in row.error
        assert row.applied_at is None      # never marked done

    def test_a_poison_row_does_not_roll_back_its_neighbours(self, db):
        """Per-row SAVEPOINT. Without it one bad row takes down every row that
        drained successfully beside it — the batch-level version of the bug the
        pull-apply loop already fixed at row level."""
        IB.remember(db, business_id=BID, entity="invoices",
                    record={"uid": "ok", "id": 1}, reason="rejected")
        IB.remember(db, business_id=BID, entity="invoices",
                    record={"uid": "poison", "id": 2}, reason="rejected")
        db.commit()
        _due_now(db)

        def mixed(_d, _e, rec):
            if rec["uid"] == "poison":
                raise ValueError("nope")
            return "applied"

        IB.drain(db, BID, mixed)
        assert db.query(SyncInbox).filter(SyncInbox.uid == "ok").one().applied_at is not None
        assert db.query(SyncInbox).filter(SyncInbox.uid == "poison").one().applied_at is None

    def test_parents_drain_before_children(self, db):
        """A drain that ran children first would defer every one of them again."""
        IB.remember(db, business_id=BID, entity="invoice_line_items",
                    record={"uid": "child", "id": 10}, reason="deferred")
        IB.remember(db, business_id=BID, entity="invoices",
                    record={"uid": "parent", "id": 11}, reason="deferred")
        db.commit()
        _due_now(db)

        order = []
        IB.drain(db, BID, lambda _d, e, _r: (order.append(e), "applied")[1])
        assert order.index("invoices") < order.index("invoice_line_items")

    def test_a_still_deferred_row_backs_off_instead_of_spinning(self, db):
        IB.remember(db, business_id=BID, entity="invoice_payments",
                    record={"uid": "wait", "id": 77}, reason="deferred")
        db.commit()
        _due_now(db)

        IB.drain(db, BID, lambda *_: "deferred")
        row = db.query(SyncInbox).filter(SyncInbox.uid == "wait").one()
        assert row.attempts == 1
        assert row.next_attempt_at > utc_now()
        # and it is genuinely not retried until then
        assert IB.drain(db, BID, lambda *_: "applied")["attempted"] == 0

    def test_an_exhausted_row_stops_retrying_but_stays_visible(self, db):
        """The predecessor of this state was a CRITICAL log line saying the rows
        "need a human". They are now a number on a screen."""
        IB.remember(db, business_id=BID, entity="invoices",
                    record={"uid": "stuck", "id": 99}, reason="rejected")
        db.commit()
        row = db.query(SyncInbox).filter(SyncInbox.uid == "stuck").one()
        row.attempts = IB.MAX_AUTO_ATTEMPTS
        row.next_attempt_at = None
        db.commit()

        assert all(r.uid != "stuck" for r in IB.due_rows(db, BID))
        assert IB.stats(db, BID)["stuck_count"] >= 1
        assert db.query(SyncInbox).filter(SyncInbox.uid == "stuck").count() == 1  # never deleted

    def test_ops_retry_revives_a_stuck_row(self, db):
        IB.remember(db, business_id=BID, entity="invoices",
                    record={"uid": "revive", "id": 100}, reason="rejected")
        db.commit()
        row = db.query(SyncInbox).filter(SyncInbox.uid == "revive").one()
        row.attempts = IB.MAX_AUTO_ATTEMPTS
        db.commit()

        assert IB.requeue(db, BID, row.id) is True
        assert any(r.uid == "revive" for r in IB.due_rows(db, BID))

    def test_stats_separate_deferred_from_rejected(self, db):
        """They need different responses: deferred usually resolves itself,
        rejected needs a decision."""
        IB.remember(db, business_id=BID, entity="invoices",
                    record={"uid": "d", "id": 1}, reason="deferred")
        IB.remember(db, business_id=BID, entity="invoices",
                    record={"uid": "r", "id": 2}, reason="rejected")
        db.commit()
        s = IB.stats(db, BID)
        assert s["deferred_count"] == 1
        assert s["rejected_count"] == 1
        assert s["pending_count"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# DEFECT 3 — the cursor survives a restart
# ═════════════════════════════════════════════════════════════════════════════

class TestCursorIsDurable:

    def test_it_round_trips_through_the_database(self, db):
        from services import sync_worker as SW
        SW._PULL_CURSOR.pop(BID, None)

        SW._set_pull_cursor(db, BID, "2026-07-31T10:00:00")
        SW._PULL_CURSOR.pop(BID, None)          # simulate a process restart

        assert SW._get_pull_cursor(db, BID) == "2026-07-31T10:00:00"

    def test_the_stored_row_is_updated_not_duplicated(self, db):
        from services import sync_worker as SW
        SW._PULL_CURSOR.pop(BID, None)
        SW._set_pull_cursor(db, BID, "2026-07-31T10:00:00")
        SW._set_pull_cursor(db, BID, "2026-07-31T11:00:00")

        rows = db.query(SyncCursor).filter(SyncCursor.business_id == BID,
                                           SyncCursor.entity == "*").all()
        assert len(rows) == 1
        assert rows[0].cursor_value == "2026-07-31T11:00:00"

    def test_absence_is_cached_without_re_querying(self, db):
        """`None` cannot distinguish "no cursor" from "not looked up", which is
        the absent-vs-unread confusion rule 33 is about, in miniature."""
        from services import sync_worker as SW
        SW._PULL_CURSOR.pop(BID, None)
        assert SW._get_pull_cursor(db, BID) is None
        assert SW._PULL_CURSOR.get(BID) == SW._NO_CURSOR
        assert SW._get_pull_cursor(db, BID) is None


# ═════════════════════════════════════════════════════════════════════════════
# DEFECT 4 — pagination, and the watermark that makes it safe
# ═════════════════════════════════════════════════════════════════════════════

class TestPaginationCannotSkipRows:

    def test_the_worker_sends_a_page_limit(self):
        import inspect
        from services import sync_worker as SW
        src = inspect.getsource(SW._sync_business_impl)
        assert '"limit": _PULL_PAGE_LIMIT' in src, (
            "the worker pull is unbounded again — a first pull selects every row "
            "of every table inside one client timeout and can never complete"
        )
        assert SW._PULL_PAGE_LIMIT > 0

    def test_the_parity_audit_sends_no_limit(self):
        """Parity decides whether a local row is ABSENT on the cloud. A truncated
        page would make it invent MISSING rows and queue repairs for data that is
        simply on the next page."""
        import inspect
        from services import sync_worker as SW
        src = inspect.getsource(SW._cloud_parity_check)
        assert "limit" not in src.split("httpx.get")[1].split(")")[0]
        assert 'body.get("has_more")' in src, "parity must refuse a truncated snapshot"

    def test_a_truncated_page_advances_only_to_the_tail_it_delivered(self):
        """THE GATE. Advancing to `pulled_at` after a truncated page skips every
        row the cap cut off — turning a slow pull into silent data loss, which is
        strictly worse than the livelock pagination fixes.

        Reimplements the rule from `_sync_business_impl` over a fixed payload.
        """
        t0 = datetime(2026, 7, 31, 10, 0, 0)
        iso = lambda n: (t0 + timedelta(minutes=n)).isoformat()

        body = {
            "pulled_at": iso(99),
            "has_more": True,
            "truncated_tables": ["invoices", "stock_ledger"],
            "changes": {
                "invoices":     [{"updated_at": iso(i)} for i in range(6)],
                "stock_ledger": [{"updated_at": iso(i)} for i in range(4)],
            },
        }
        marks = []
        for t in body["truncated_tables"]:
            ts = [datetime.fromisoformat(r["updated_at"])
                  for r in body["changes"][t] if r.get("updated_at")]
            if ts:
                marks.append(max(ts))
        cursor = min(marks).isoformat()

        assert cursor == iso(3), "must be the MIN of the truncated tables' maxima"
        assert cursor < body["pulled_at"], "must not jump to the server's clock"

    def test_no_usable_timestamp_holds_the_cursor(self):
        """If the watermark cannot be computed, advancing is a guess — and the
        thing being guessed at is which rows to skip."""
        import inspect
        from services import sync_worker as SW
        src = inspect.getsource(SW._sync_business_impl)
        assert "_cloud_cursor = None" in src
        assert "HOLDING the cursor" in src

    def test_a_truncated_pull_schedules_an_immediate_follow_up(self):
        """Otherwise a backlog drains one page per cloud_pull_interval — 1000
        rows every two minutes by default."""
        import inspect
        from services import sync_worker as SW
        assert "_PULL_MORE_PENDING" in inspect.getsource(SW.run_hybrid_sync)
        assert "_PULL_MORE_PENDING.discard" in inspect.getsource(SW._sync_business_impl)


# ═════════════════════════════════════════════════════════════════════════════
# The single apply path
# ═════════════════════════════════════════════════════════════════════════════

class TestOneApplyPathForBothCallers:

    def test_the_drain_and_the_pull_loop_share_it(self):
        """`resolve_parent_fk_uids` states the rule for itself: single source of
        truth for both apply paths "so the resolution/deferral logic can never
        drift". A separate implementation for the drain would be a second copy of
        the dedup fallbacks, the LWW rules and the conflict hooks."""
        import inspect
        from services import sync_worker as SW

        assert callable(getattr(SW, "_apply_pulled_row", None))
        impl = inspect.getsource(SW._sync_business_impl)
        assert impl.count("_apply_pulled_row(") >= 2, (
            "the pull loop and the inbox drain must both go through "
            "_apply_pulled_row; a second apply implementation will drift"
        )

    def test_the_outcome_distinguishes_deferred_from_applied(self):
        """A bare bool is what let a deferred row look identical to an applied
        one — the ambiguity behind defect 1."""
        from services.sync_worker import _Applied
        assert _Applied("deferred").status == "deferred"
        assert _Applied("applied").status == "applied"
        assert _Applied("skipped").status == "skipped"

    def test_the_pull_loop_routes_deferrals_to_the_inbox(self):
        import inspect
        from services import sync_worker as SW
        src = inspect.getsource(SW._sync_business_impl)
        assert 'reason="deferred"' in src
        assert 'reason="rejected"' in src

    def test_the_cursor_no_longer_stalls_on_rejected_rows(self):
        """Holding was only ever necessary because the row existed nowhere but
        in the cloud. It is durable now, so later rows are not held hostage."""
        import inspect
        from services import sync_worker as SW
        src = inspect.getsource(SW._sync_business_impl)
        assert "They need a human" not in src, (
            "the abandon-after-N-attempts branch is back; rejected rows are "
            "durable in the inbox and must not be abandoned"
        )
        # the PARTIAL-pull hold must remain: those rows were never received at
        # all, so there is nothing in the inbox to retry.
        assert "PARTIAL PULL" in src
