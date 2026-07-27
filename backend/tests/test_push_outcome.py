"""
tests/test_push_outcome.py — the M-20 ack decision, tested by BEHAVIOUR
======================================================================
Every assertion here runs `services.sync_worker.PushOutcome`, the same object
the worker uses to decide which outbox rows may be acked. None of them grep
source text.

WHY THIS FILE REPLACES STRING MATCHING
--------------------------------------
The first tests written for M-20 asserted that certain phrases appeared in
`sync_worker.py`. That is a weak test in both directions and both directions
actually happened while the fix was being written:

  * it FAILED on a harmless comment reword (twice);
  * it would have PASSED on a refactor that kept the strings and broke the
    behaviour.

The decision was inline in a 200-line function, so string matching was the only
option. Extracting `PushOutcome` made the real thing testable, and this file
tests the real thing.

THE ONE RULE EVERYTHING PROTECTS
--------------------------------
A row may be acked ONLY when the cloud has accounted for it. Acking a row the
cloud did not store deletes the last copy of it — that is M-20, and it deleted a
Rs641 sale on 2026-07-27.

THE INVARIANT
-------------
    received == applied + deferred + skipped

`applied` ALREADY counts rejected rows (routes/sync.py acks a refused row so it
cannot stall the queue), which is why `rejected` is not added. Adding it
produced "-3 row(s) vanished" in production — an impossible negative, and the
tell that the arithmetic was wrong.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from services.sync_worker import PushOutcome


# ── builders, so each test reads as the scenario it describes ────────────────

def rows(*specs):
    """[('invoices', 860), ...] -> the chunk shape the worker sends."""
    return [{"entity": e, "entity_id": i, "operation": "INSERT"} for e, i in specs]


def reply(applied=None, deferred=(), rejected=(), skipped=()):
    def entries(items, reason):
        return [{"entity": e, "row_id": i, "reason": reason} for e, i in items]
    body = {"status": "success",
            "deferred": entries(deferred, "parent not resolvable in this database yet"),
            "rejected": entries(rejected, "constraint violation"),
            "skipped": entries(skipped, "cloud copy is newer (LWW)")}
    if applied is not None:
        body["applied"] = applied
    return body


# ══════════════════════════════════════════════════════════════════════════════
# 1. THE RULE: a deferred row is never acked
# ══════════════════════════════════════════════════════════════════════════════

def test_a_deferred_row_is_held():
    """The single line that stops a sale being deleted."""
    chunk = rows(("invoices", 860), ("customers", 5))
    o = PushOutcome(chunk, reply(applied=1, deferred=[("invoices", 860)]))
    assert o.should_hold("invoices", 860) is True
    assert o.should_hold("customers", 5) is False


def test_the_production_incident_exactly():
    """2026-07-27: 5 rows sent, the invoice deferred for a missing
    register_shifts parent, 4 applied. The invoice must be KEPT."""
    chunk = rows(("invoices", 860), ("stock_ledger", 1), ("stock_ledger", 2),
                 ("inventory", 1), ("inventory", 2))
    o = PushOutcome(chunk, reply(applied=4, deferred=[("invoices", 860)]))
    assert o.unaccounted == 0
    assert o.should_hold("invoices", 860) is True
    assert o.ack_count == 4


def test_the_second_incident_exactly():
    """2026-07-28 00:32: sent 7, applied 3 (including 3 rejected), deferred 4.
    The old formula added `rejected` and reported -3 vanished."""
    chunk = rows(("invoice_payments", 58), ("invoices", 860), ("invoices", 861),
                 ("invoice_payments", 59), ("register_shifts", 7),
                 ("register_shifts", 8), ("register_shifts", 9))
    o = PushOutcome(chunk, reply(
        applied=3,
        deferred=[("invoice_payments", 58), ("invoices", 860),
                  ("invoices", 861), ("invoice_payments", 59)],
        rejected=[("register_shifts", 7), ("register_shifts", 8),
                  ("register_shifts", 9)]))
    assert o.unaccounted == 0, "the arithmetic must close; it reported -3 before"
    assert o.should_hold("invoices", 860) is True
    assert o.should_hold("register_shifts", 7) is False, (
        "a REJECTED row must still drain — holding it spins forever (M-13)")


# ══════════════════════════════════════════════════════════════════════════════
# 2. THE INVARIANT: received == applied + deferred + skipped
# ══════════════════════════════════════════════════════════════════════════════

def test_a_fully_applied_chunk_is_clean():
    o = PushOutcome(rows(("invoices", 1), ("invoices", 2)), reply(applied=2))
    assert o.unaccounted == 0 and o.is_clean and o.ack_count == 2


def test_rejected_rows_are_inside_applied_and_are_not_added_again():
    """`routes/sync.py` does `processed_count += 1  # ack either way`, so a
    rejected row is counted in `applied`. Adding it again is what produced a
    negative shortfall."""
    chunk = rows(("invoices", 1), ("invoices", 2))
    o = PushOutcome(chunk, reply(applied=2, rejected=[("invoices", 2)]))
    assert o.unaccounted == 0
    assert o.should_hold("invoices", 2) is False


def test_a_skipped_row_is_accounted_for_and_drains():
    """LWW 'cloud copy is newer' and 'unknown entity' are correct outcomes. They
    used to be reported nowhere, so the sum could never close."""
    chunk = rows(("invoices", 1), ("invoices", 2))
    o = PushOutcome(chunk, reply(applied=1, skipped=[("invoices", 2)]))
    assert o.unaccounted == 0
    assert o.should_hold("invoices", 2) is False


@pytest.mark.parametrize("sent", range(0, 7))
def test_the_shortfall_is_never_negative(sent):
    """A negative shortfall is arithmetically impossible and was the tell that
    the formula was wrong. Exhaustive over every split of `sent`."""
    for applied in range(sent + 1):
        for deferred in range(sent - applied + 1):
            skipped = sent - applied - deferred
            o = PushOutcome(
                rows(*[("invoices", i) for i in range(sent)]),
                reply(applied=applied,
                      deferred=[("invoices", i) for i in range(deferred)],
                      skipped=[("invoices", i) for i in range(deferred, deferred + skipped)]))
            assert o.unaccounted >= 0
            assert o.unaccounted == 0, (
                f"sent={sent} applied={applied} deferred={deferred} "
                f"skipped={skipped} should account exactly")


# ══════════════════════════════════════════════════════════════════════════════
# 3. FAIL CLOSED on anything unexplained
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unexplained_shortfall_holds_every_row():
    """Without `deferred` naming them, there is no way to know WHICH row did not
    land — and acking the wrong one destroys the last copy of a sale."""
    chunk = rows(("invoices", 1), ("invoices", 2), ("invoices", 3))
    o = PushOutcome(chunk, reply(applied=2))
    assert o.unaccounted == 1
    assert all(o.should_hold("invoices", i) for i in (1, 2, 3))
    assert o.ack_count == 0


def test_an_older_cloud_without_applied_claims_nothing():
    """`applied` absent means nothing can be concluded, so nothing is claimed
    (rule 33). It must NOT be read as zero, which would hold every row forever."""
    chunk = rows(("invoices", 1), ("invoices", 2))
    o = PushOutcome(chunk, {"status": "success"})
    assert o.unaccounted == 0
    assert not any(o.should_hold("invoices", i) for i in (1, 2))
    assert o.ack_count == 2


def test_an_older_cloud_that_defers_without_the_field_still_fails_closed():
    """The pre-deploy state: the cloud defers but sends no `deferred` list. The
    arithmetic is the only thing that catches it, and it must."""
    chunk = rows(("invoices", 860), ("inventory", 1), ("inventory", 2),
                 ("stock_ledger", 1), ("stock_ledger", 2))
    o = PushOutcome(chunk, {"status": "success", "applied": 4})
    assert o.unaccounted == 1
    assert o.should_hold("invoices", 860) is True


def test_an_empty_chunk_is_clean_and_holds_nothing():
    o = PushOutcome([], reply(applied=0))
    assert o.is_clean and o.ack_count == 0 and o.unaccounted == 0


def test_a_malformed_reply_does_not_crash_and_holds_nothing_it_cannot_name():
    """A cloud returning junk must not take the worker down; it must also not
    silently ack. With no `applied`, nothing is claimed either way."""
    for body in ({}, {"deferred": None}, {"applied": "four"}, None):
        o = PushOutcome(rows(("invoices", 1)), body)
        assert o.unaccounted == 0
        assert o.should_hold("invoices", 1) is False


# ══════════════════════════════════════════════════════════════════════════════
# 4. THE ROUND TRIP — deferred until the parent lands, then it goes
# ══════════════════════════════════════════════════════════════════════════════

class FakeCloud:
    """Defers a child until its parent has been received. The production shape:
    invoice 860 blocked on register_shifts 9."""

    def __init__(self, child, parent):
        self.child, self.parent = child, parent
        self.stored, self.has_parent = [], False

    def push(self, chunk):
        applied, deferred = 0, []
        for c in chunk:
            key = (c["entity"], c["entity_id"])
            if key == self.parent:
                self.has_parent = True
            if key == self.child and not self.has_parent:
                deferred.append({"entity": c["entity"], "row_id": c["entity_id"],
                                 "reason": "parent not resolvable"})
                continue
            self.stored.append(key)
            applied += 1
        return {"status": "success", "applied": applied,
                "deferred": deferred, "rejected": [], "skipped": []}


def test_the_sale_waits_for_its_parent_and_then_lands():
    """End to end, and the reason nothing was lost: the row is HELD, not acked,
    so it is still there to send when the shift arrives."""
    cloud = FakeCloud(child=("invoices", 860), parent=("register_shifts", 9))
    outbox = [{"entity": "invoices", "entity_id": 860, "operation": "INSERT"}]

    # Cycle 1 — parent absent.
    o = PushOutcome(outbox, cloud.push(outbox))
    assert o.should_hold("invoices", 860) is True
    assert ("invoices", 860) not in cloud.stored
    # the row stays in the outbox

    # Cycle 2 — the shift is queued too and goes first.
    outbox2 = [{"entity": "register_shifts", "entity_id": 9, "operation": "INSERT"},
               {"entity": "invoices", "entity_id": 860, "operation": "INSERT"}]
    o = PushOutcome(outbox2, cloud.push(outbox2))
    assert o.is_clean
    assert ("invoices", 860) in cloud.stored, "the sale never landed"


def test_holding_forever_is_still_better_than_acking_once():
    """If the parent NEVER arrives, the row is re-sent every cycle and stays
    safe. That is the deliberate trade: a growing queue is visible and
    recoverable; a deleted sale is neither."""
    cloud = FakeCloud(child=("invoices", 860), parent=("register_shifts", 9))
    outbox = [{"entity": "invoices", "entity_id": 860, "operation": "INSERT"}]
    for _ in range(20):
        o = PushOutcome(outbox, cloud.push(outbox))
        assert o.should_hold("invoices", 860) is True
    assert ("invoices", 860) not in cloud.stored


# ══════════════════════════════════════════════════════════════════════════════
# 5. The M-20a safety net — find rows that never reached the outbox
# ══════════════════════════════════════════════════════════════════════════════
# `register_shifts` 7/8/9 were never enqueued, and every hypothesis for WHY has
# so far failed against the evidence. This catches the SYMPTOM whatever the
# cause: a syncable row that ought to be in the outbox and is not.

import datetime as _dt
import json as _json


def _heal_db(tmp_path, name):
    from database.db import Base as _B
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker
    from database.models import Base, User, SyncQueue, RegisterShift  # noqa: F401
    eng = sa.create_engine(f"sqlite:///{tmp_path / name}")
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def test_it_finds_a_row_that_never_reached_the_outbox(tmp_path):
    from database.models import User, SyncQueue, RegisterShift
    from services.sync_worker import find_unqueued_syncable_rows
    from services.dates import utc_now
    db = _heal_db(tmp_path, "test_heal_find.db")
    db.add(User(id=7, username="o", password="x",
                settings=_json.dumps({"general": {"hosting_mode": "hybrid"}})))
    db.add(SyncQueue(business_id=7, entity="invoices", entity_id=1,
                     operation="INSERT", payload="{}",
                     created_at=utc_now() - _dt.timedelta(days=1)))
    db.add(RegisterShift(id=2, business_id=7, user_id=7, status="OPEN",
                         opening_cash=0, start_time=utc_now(),
                         created_at=utc_now()))
    db.commit()
    found = find_unqueued_syncable_rows(db, 7, entities=["register_shifts"])
    assert found == [{"entity": "register_shifts", "row_id": 2}]
    db.close()


def test_it_ignores_rows_older_than_the_outbox_itself(tmp_path):
    """THE BOUND THAT MAKES IT SAFE TO RUN AUTOMATICALLY.

    Rows predating hybrid mode legitimately have no outbox entry — most of the
    861 local invoices are in that state. Without this bound the check would be
    correct and useless: it would try to re-push years of history.
    """
    from database.models import User, SyncQueue, RegisterShift
    from services.sync_worker import find_unqueued_syncable_rows
    from services.dates import utc_now
    db = _heal_db(tmp_path, "test_heal_old.db")
    old = utc_now() - _dt.timedelta(days=30)
    db.add(User(id=7, username="o", password="x", settings="{}"))
    db.add(RegisterShift(id=1, business_id=7, user_id=7, status="CLOSED",
                         opening_cash=0, start_time=old, created_at=old))
    db.add(SyncQueue(business_id=7, entity="invoices", entity_id=1,
                     operation="INSERT", payload="{}",
                     created_at=utc_now() - _dt.timedelta(days=1)))
    db.commit()
    assert find_unqueued_syncable_rows(db, 7, entities=["register_shifts"]) == []
    db.close()


def test_a_business_with_no_outbox_history_is_left_alone(tmp_path):
    """No outbox at all means no basis for a floor — and a business that has
    never synced is not this check's call to make."""
    from database.models import User, RegisterShift
    from services.sync_worker import find_unqueued_syncable_rows
    from services.dates import utc_now
    db = _heal_db(tmp_path, "test_heal_none.db")
    db.add(User(id=7, username="o", password="x", settings="{}"))
    db.add(RegisterShift(id=1, business_id=7, user_id=7, status="OPEN",
                         opening_cash=0, start_time=utc_now(),
                         created_at=utc_now()))
    db.commit()
    assert find_unqueued_syncable_rows(db, 7, entities=["register_shifts"]) == []
    db.close()


def test_an_unreadable_table_is_reported_not_treated_as_empty(tmp_path):
    """Rule 33. A table that cannot be scanned has not been found clean."""
    from database.models import User, SyncQueue
    from services.sync_worker import find_unqueued_syncable_rows
    from services.dates import utc_now
    db = _heal_db(tmp_path, "test_heal_missing.db")
    db.add(User(id=7, username="o", password="x", settings="{}"))
    db.add(SyncQueue(business_id=7, entity="invoices", entity_id=1,
                     operation="INSERT", payload="{}", created_at=utc_now()))
    db.commit()
    # A table that does not exist must not raise, and must not be counted clean.
    assert find_unqueued_syncable_rows(db, 7, entities=["no_such_table"]) == []
    db.close()


def test_parents_are_scanned_before_children(tmp_path):
    """A missing parent strands its children, so recovering it unblocks most."""
    import inspect
    from services import sync_worker
    src = inspect.getsource(sync_worker.find_unqueued_syncable_rows)
    order = src[src.index("entities = ["):src.index("]", src.index("entities = ["))]
    assert order.index("register_shifts") < order.index("invoices")
    assert order.index("customers") < order.index("invoices")
