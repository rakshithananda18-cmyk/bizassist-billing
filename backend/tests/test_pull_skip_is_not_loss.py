"""
tests/test_pull_skip_is_not_loss.py — a declined row is not a delivered row
===========================================================================

WHAT THIS PINS
--------------
`_apply_pulled_row` has five paths that return `_Applied("skipped")`. The class
docstring used to assert that all five were deliberate and that "nothing is lost,
so this is NOT inbox material". Three of the five are decisions. Two are
failures:

    no-uid      the row cannot be matched, so we decline to write it — but the
                row is REAL and still on the cloud.
    clock-skew  the cloud `updated_at` is >5 min ahead of this machine. That is
                a clock problem; the same row applies cleanly once the clocks
                agree, IF anyone still has it.

In both, the pull cursor advances past a row this database never received, and
the cloud never offers it again (its `updated_at` has not changed and the cursor
is now past it). That is M-12, in the one branch that claimed exemption.

WHAT IT COST — LCL-OW-0037, reconstructed from the live database 2026-08-01
---------------------------------------------------------------------------
    30 Jul 11:43:09 UTC   a ₹124 settlement is recorded ON THE CLOUD against
                          cloud invoice 835 (= local 869, LCL-OW-0037).
    30 Jul 11:43:26 UTC   the pull begins failing: "read operation timed out"
                          (the HTTP timeout was 10.0s then; it is 60.0s now)
                          and keeps failing for the next 55 minutes of logs.
    ...                   the payment never reaches the local database. No
                          successful SyncLog exists for that business between
                          08 Jul 19:13 and 31 Jul 19:38.
    31 Jul 18:58:56 UTC   the local invoice still reads paid_amount 0.0 /
                          "Pending", so the owner settles it AGAIN by cheque.
                          That pushes up.
    →                     the cloud holds ₹248 against a ₹124 invoice.

Nothing in the system reported this. The audit row for the cloud's insert IS in
the local database — but only because `table_alterations` had no `updated_at`
and was therefore replicated in full on every pull, which was itself a bug and
has since been removed. The only reason this was reconstructable is a defect we
fixed.

THE TESTS BELOW USE THE REAL MODULES against a real sqlite database. There is no
source-string matching in the behavioural assertions — a test that greps for a
line of code passes just as happily when the line is dead.
"""
import json
import os
import sys
from datetime import timedelta

os.environ.setdefault("JWT_SECRET",   "test-secret-for-pull-skip-abcdef123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from core.sync import inbox as IB
from database.db import SessionLocal
from database.models import Base, Customer, SyncInbox
from services.dates import utc_now
from services.sync_worker import _Applied, _apply_pulled_row

BID = 90310


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
    s.query(Customer).filter(Customer.business_id == BID).delete()
    s.commit()
    try:
        yield s
    finally:
        s.rollback()
        s.query(SyncInbox).filter(SyncInbox.business_id == BID).delete()
        s.query(Customer).filter(Customer.business_id == BID).delete()
        s.commit()
        s.close()


# ═════════════════════════════════════════════════════════════════════════════
# 1. The outcome object can tell a decision from a failure
# ═════════════════════════════════════════════════════════════════════════════

class TestSkipReasonsAreDistinguishable:

    def test_the_two_recoverable_reasons_report_themselves_as_lost(self):
        for reason in ("no-uid", "clock-skew"):
            assert _Applied("skipped", reason=reason).is_lost, (
                f"{reason!r} leaves the row on the cloud and not here, so it "
                f"must be inbox material"
            )

    def test_the_three_deliberate_reasons_do_not(self):
        # These are decisions taken with BOTH copies in hand. Retrying them
        # would re-lose the same comparison every cycle, for ever.
        for reason in ("no-identity", "lww-local-newer", "no-updated-at"):
            assert not _Applied("skipped", reason=reason).is_lost, (
                f"{reason!r} is a decision, not a delivery failure — retrying it "
                f"would spin"
            )

    def test_applied_and_deferred_are_never_lost(self):
        assert not _Applied("applied").is_lost
        assert not _Applied("deferred").is_lost      # deferred has its own path

    def test_every_recoverable_reason_has_a_held_message(self):
        """The two sets must not drift.

        `_Applied.RECOVERABLE_SKIPS` decides what the pull inboxes;
        `inbox._HELD_OUTCOMES` decides what a DRAIN counts as still-held. A
        reason in the first and not the second would be recorded once and then
        stamped `applied_at` on its first retry — recorded, then silently
        discarded, which is worse than not recording it.
        """
        for reason in _Applied.RECOVERABLE_SKIPS:
            assert reason in IB._HELD_OUTCOMES, (
                f"{reason!r} is inboxed by the pull but the drain would treat it "
                f"as delivered"
            )


# ═════════════════════════════════════════════════════════════════════════════
# 2. The real apply path produces those reasons
# ═════════════════════════════════════════════════════════════════════════════

class TestRealApplyPathTagsItsSkips:

    def test_a_row_with_no_uid_is_skipped_as_no_uid(self, db):
        """THE GATE for the LCL-OW-0037 shape.

        `Customer` has a `uid` column, so a pulled row without one cannot be
        matched. Before this change the outcome was an untagged "skipped" and
        the caller had no way to know a real row had just been dropped.
        """
        out = _apply_pulled_row(
            db, BID, "customers", Customer,
            {"id": 4242, "name": "Cloud Only", "business_id": BID},
        )
        assert out.status == "skipped"
        assert out.reason == "no-uid"
        assert out.is_lost

    def test_a_future_dated_row_is_skipped_as_clock_skew(self, db):
        far_future = (utc_now() + timedelta(hours=3)).isoformat()
        out = _apply_pulled_row(
            db, BID, "customers", Customer,
            {"id": 4243, "uid": "u-skew-1", "name": "Tomorrow",
             "business_id": BID, "updated_at": far_future},
        )
        assert out.status == "skipped"
        assert out.reason == "clock-skew"
        assert out.is_lost

    def test_a_normal_row_still_applies(self, db):
        """The guard rails must not have closed the road.

        Without this, every assertion above is satisfied by an apply path that
        rejects everything.
        """
        out = _apply_pulled_row(
            db, BID, "customers", Customer,
            {"id": 4244, "uid": "u-ok-1", "name": "Normal",
             "business_id": BID, "updated_at": utc_now().isoformat()},
        )
        assert out.status == "applied"
        assert not out.is_lost
        db.flush()
        assert db.query(Customer).filter(Customer.uid == "u-ok-1").first() is not None


# ═════════════════════════════════════════════════════════════════════════════
# 3. A held row stays held across a drain
# ═════════════════════════════════════════════════════════════════════════════

class TestDrainDoesNotSwallowADeclinedRow:

    def _drain_once(self, db, outcome):
        for r in db.query(SyncInbox).filter(SyncInbox.business_id == BID).all():
            r.next_attempt_at = None
        db.commit()
        return IB.drain(db, BID, lambda _db, _ent, _rec: outcome)

    def test_a_no_uid_row_is_not_stamped_applied(self, db):
        """The bug this closes lives INSIDE the recovery mechanism.

        `drain` treated every outcome that was not the literal string "deferred"
        as success and set `applied_at`. A row re-declined for having no uid
        would therefore be recorded by the pull, retried once, marked delivered,
        and vanish — the inbox reproducing the exact failure it was built to
        prevent, one layer further in.
        """
        IB.remember(db, business_id=BID, entity="invoice_payments",
                    record={"id": 835, "uid": None, "amount_paid": 124.0},
                    reason="no-uid", error="row has no uid")
        db.commit()

        # remember() needs SOMETHING to match on; id alone is enough.
        row = db.query(SyncInbox).filter(SyncInbox.business_id == BID).one()
        assert row.remote_id == 835

        res = self._drain_once(db, "no-uid")
        assert res["deferred"] == 1
        assert res["applied"] == 0

        db.refresh(row)
        assert row.applied_at is None, "a declined row must not be marked delivered"
        assert row.reason == "no-uid", "the operator must see WHY, not 'deferred'"

    def test_a_clock_skew_row_is_not_stamped_applied(self, db):
        IB.remember(db, business_id=BID, entity="customers",
                    record={"id": 77, "uid": "u-skew-2"},
                    reason="clock-skew", error="clock skew")
        db.commit()
        res = self._drain_once(db, "clock-skew")
        assert res["deferred"] == 1
        row = db.query(SyncInbox).filter(SyncInbox.uid == "u-skew-2").one()
        assert row.applied_at is None
        assert row.reason == "clock-skew"

    def test_a_row_that_does_apply_is_still_stamped(self, db):
        """Counter-test: the held set must not swallow real successes."""
        IB.remember(db, business_id=BID, entity="customers",
                    record={"id": 78, "uid": "u-ok-2"}, reason="deferred")
        db.commit()
        res = self._drain_once(db, "applied")
        assert res["applied"] == 1
        row = db.query(SyncInbox).filter(SyncInbox.uid == "u-ok-2").one()
        assert row.applied_at is not None


# ═════════════════════════════════════════════════════════════════════════════
# 4. Ops can see the new reasons
# ═════════════════════════════════════════════════════════════════════════════

class TestStatsReportEveryReason:

    def test_reason_counts_covers_reasons_beyond_the_two_named_buckets(self, db):
        """`deferred_count` and `rejected_count` are a closed enumeration.

        Two reasons were added on 2026-08-01 and would have landed in neither,
        so the Ops panel would show a non-zero `pending_count` with nothing
        accounting for it — a number an operator cannot act on.
        """
        IB.remember(db, business_id=BID, entity="customers",
                    record={"id": 1, "uid": "u-a"}, reason="no-uid")
        IB.remember(db, business_id=BID, entity="customers",
                    record={"id": 2, "uid": "u-b"}, reason="cloud-only")
        IB.remember(db, business_id=BID, entity="customers",
                    record={"id": 3, "uid": "u-c"}, reason="deferred")
        db.commit()

        s = IB.stats(db, BID)
        assert s["pending_count"] == 3
        assert s["reason_counts"] == {"no-uid": 1, "cloud-only": 1, "deferred": 1}
        # And the sum of the buckets accounts for every pending row.
        assert sum(s["reason_counts"].values()) == s["pending_count"]
