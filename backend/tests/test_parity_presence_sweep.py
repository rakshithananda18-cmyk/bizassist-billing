"""
tests/test_parity_presence_sweep.py — parity compared 2 of 25 tables
=====================================================================

`_cloud_parity_check` is the only CONTINUOUS cross-database check the system
has. Until 2026-08-03 it compared exactly two tables — `invoice_line_items` and
`invoice_payments` (`CHILD_SPECS`) — plus a paid-state check on invoice headers.

Everything else was outside every question it asked:

    products · customers · vendors · inventory · stock_ledger · expenses
    godowns · purchase_invoices · purchase_orders · register_shifts
    shift_cash_movements · stock_transfers · business_settings · period_locks
    product_barcodes · payments · alert_configs · rate_limit_configs
    …and INVOICES THEMSELVES — a whole missing sale was invisible

and the sweep still logged **"cloud parity OK — no drift detected"** over all of
it. That is rule 33 — absent vs not-looked-at — in the one component whose
entire job is telling those apart.

WHAT THESE TESTS PIN
--------------------
1. A missing row in a previously-uncompared table is FOUND, in both directions.
2. It is **not repaired** — no outbox row, no inbox row. Detection only.
   (§7b.5: "absent here" has two histories and there is no
   `_cloud_only_row_fits` equivalent for a customer or a product. Auto-repairing
   on a rule nobody has written would be worse than the gap.)
3. Rows still sitting in the outbox are NOT counted — sync lag is not
   divergence, and a sweep that cries wolf on every healthy system gets ignored.
4. The all-clear states its DENOMINATOR. An "OK" that does not say how much it
   looked at is the exact false reassurance this sweep shipped for months.
5. The table list is DERIVED from MODEL_MAP, so a newly synced table joins the
   sweep automatically rather than silently sitting outside it.
"""
import os
import sys

os.environ.setdefault("JWT_SECRET",   "test-secret-for-parity-presence-abc123")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from database.db import SessionLocal
from database.models import Base, Customer, Product, SyncInbox, SyncQueue, User
from services import sync_worker as SW
from services.dates import utc_now

BID = 90711


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.fixture(scope="module", autouse=True)
def ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clean(s):
    s.query(Customer).filter(Customer.business_id == BID).delete()
    s.query(Product).filter(Product.business_id == BID).delete()
    s.query(SyncQueue).filter(SyncQueue.business_id == BID).delete()
    s.query(SyncInbox).filter(SyncInbox.business_id == BID).delete()
    s.query(User).filter(User.id == BID).delete()
    s.commit()


@pytest.fixture
def db():
    s = SessionLocal()
    _clean(s)
    s.add(User(id=BID, username=f"pres_owner_{BID}", email=f"pr{BID}@t.invalid",
               password="x", public_id=f"BA-PRE{BID}", business_name="Presence Co"))
    s.commit()
    try:
        yield s
    finally:
        s.rollback()
        _clean(s)
        s.close()


def _run(db, monkeypatch, changes):
    monkeypatch.setattr(SW, "_get_cloud_token", lambda _bid: "fake-token")
    monkeypatch.setattr(SW.httpx, "get",
                        lambda *a, **k: _FakeResponse({"changes": changes}))
    SW._LAST_PARITY.pop(BID, None)          # bypass the 6-hour rate limit
    return SW._cloud_parity_check(db, BID)


def _add_customer(s, uid, name="Walk-in"):
    c = Customer(business_id=BID, uid=uid, name=name,
                 created_at=utc_now(), updated_at=utc_now())
    s.add(c)
    s.commit()
    return c


# ═════════════════════════════════════════════════════════════════════════════
# 1. The gap itself — a table nobody was comparing
# ═════════════════════════════════════════════════════════════════════════════

def test_a_local_customer_absent_on_the_cloud_is_found(db, monkeypatch):
    """`customers` was never compared. A customer this device holds and the
    cloud does not is real divergence and used to be invisible."""
    _add_customer(db, "cust-local-only")

    summary = _run(db, monkeypatch, {"customers": []})

    assert summary["presence_local_only"] >= 1
    assert summary["presence_by_table"]["customers"]["local_only"] == 1


def test_a_cloud_product_absent_locally_is_found(db, monkeypatch):
    """The other direction, on another previously-uncompared table."""
    summary = _run(db, monkeypatch, {
        "products": [{"id": 5, "uid": "prod-cloud-only", "name": "Sugar 50kg"}],
    })

    assert summary["presence_cloud_only"] >= 1
    assert summary["presence_by_table"]["products"]["cloud_only"] == 1


def test_matching_rows_produce_no_finding(db, monkeypatch):
    """The same uid on both sides is agreement, not drift."""
    _add_customer(db, "cust-on-both")

    summary = _run(db, monkeypatch, {
        "customers": [{"id": 9, "uid": "cust-on-both", "name": "Walk-in"}],
    })

    assert summary["presence_local_only"] == 0
    assert summary["presence_cloud_only"] == 0
    assert "customers" not in summary["presence_by_table"]


# ═════════════════════════════════════════════════════════════════════════════
# 2. Detection ONLY — the §7b.5 lesson
# ═════════════════════════════════════════════════════════════════════════════

def test_presence_findings_repair_nothing(db, monkeypatch):
    """No outbox row, no inbox row, in EITHER direction.

    There is no `_cloud_only_row_fits` equivalent for a customer — "would this
    still foot?" is invoice-shaped and does not generalise. Importing or pushing
    on a rule nobody has written is how the cloud-only scan nearly re-corrupted
    31 invoices (§7b.5). So this sweep reports and stops.
    """
    _add_customer(db, "cust-local-only")

    summary = _run(db, monkeypatch, {
        "products": [{"id": 5, "uid": "prod-cloud-only", "name": "Sugar 50kg"}],
    })

    assert summary["presence_local_only"] >= 1
    assert summary["presence_cloud_only"] >= 1

    queued = db.query(SyncQueue).filter(
        SyncQueue.business_id == BID, SyncQueue.entity.in_(("customers", "products"))
    ).count()
    inboxed = db.query(SyncInbox).filter(
        SyncInbox.business_id == BID, SyncInbox.entity.in_(("customers", "products"))
    ).count()
    assert queued == 0, "the presence sweep must not queue repairs"
    assert inboxed == 0, "the presence sweep must not import cloud rows"


# ═════════════════════════════════════════════════════════════════════════════
# 3. Sync lag is not divergence
# ═════════════════════════════════════════════════════════════════════════════

def test_a_row_still_in_the_outbox_is_not_counted(db, monkeypatch):
    """A row written two seconds ago has not been pushed yet. Counting it as
    'missing on the cloud' would make this sweep cry wolf on every healthy
    system, and a check nobody believes is worse than no check."""
    cust = _add_customer(db, "cust-pending-push")
    db.add(SyncQueue(business_id=BID, entity="customers", entity_id=cust.id,
                     operation="INSERT", payload="{}", created_at=utc_now(),
                     synced_at=None))
    db.commit()

    summary = _run(db, monkeypatch, {"customers": []})

    assert summary["presence_local_only"] == 0, (
        "a row still queued for push is sync lag, not divergence"
    )


def test_a_row_already_pushed_IS_counted(db, monkeypatch):
    """The complement, so the exclusion above cannot silently swallow
    everything: once the outbox row is acked, absence on the cloud is real."""
    cust = _add_customer(db, "cust-already-pushed")
    db.add(SyncQueue(business_id=BID, entity="customers", entity_id=cust.id,
                     operation="INSERT", payload="{}", created_at=utc_now(),
                     synced_at=utc_now()))
    db.commit()

    summary = _run(db, monkeypatch, {"customers": []})

    assert summary["presence_local_only"] == 1, (
        "an ACKED row that is not on the cloud is exactly what parity is for"
    )


# ═════════════════════════════════════════════════════════════════════════════
# 4. The denominator
# ═════════════════════════════════════════════════════════════════════════════

def test_summary_reports_its_own_coverage(db, monkeypatch):
    """"No drift detected" is meaningless without "…across how much?".

    This sweep spent months reporting parity OK while comparing 2 of 25 tables.
    Anything rendering the result must be able to show both numbers.
    """
    summary = _run(db, monkeypatch, {})

    assert summary["tables_compared"] > 2, (
        "the whole point of this change is comparing more than CHILD_SPECS"
    )
    assert summary["tables_total"] >= summary["tables_compared"]


def test_coverage_includes_the_tables_that_were_missing(db, monkeypatch):
    """Named explicitly. `invoices` is the one that matters most — a whole
    missing SALE was outside every question parity asked."""
    covered = set(SW._parity_presence_tables())
    for table in ("invoices", "customers", "products", "expenses",
                  "stock_ledger", "purchase_invoices", "register_shifts"):
        assert table in covered, f"{table} is still outside the sweep"


def test_table_list_is_derived_not_hardcoded(db, monkeypatch):
    """A newly synced table must join the sweep automatically. Hard-coding is
    how 23 of 25 tables came to be uncompared in the first place."""
    from database.sync_map import MODEL_MAP

    covered = set(SW._parity_presence_tables())
    for name in covered:
        assert name in MODEL_MAP, f"{name} is swept but not in MODEL_MAP"

    # Every table with both identity columns must be present — no silent omissions.
    for name, model in MODEL_MAP.items():
        cols = {c.name for c in model.__table__.columns}
        if "uid" in cols and "business_id" in cols:
            assert name in covered, (
                f"{name} carries uid + business_id but is not swept"
            )


# ═════════════════════════════════════════════════════════════════════════════
# 5. Unreadable is not empty (rule 33)
# ═════════════════════════════════════════════════════════════════════════════

def test_cloud_rows_without_a_uid_are_counted_separately(db, monkeypatch):
    """A cloud row with no uid cannot be matched by uid at all. That is NOT
    evidence the local row is absent — it is an unanswerable question, and
    conflating the two is how a stalled pull reads as corruption."""
    summary = _run(db, monkeypatch, {
        "customers": [{"id": 3, "name": "No UID Co"}],       # no uid key
    })

    assert summary["presence_no_uid"] >= 1
    assert summary["presence_cloud_only"] == 0, (
        "a row that cannot be matched must not be reported as cloud-only"
    )


def test_an_unreadable_table_is_reported_not_reported_as_empty(db, monkeypatch):
    """The same rule one level up: if the LOCAL scan of a table raises, that
    table is unknown, not empty.

    Without the guard the exception would escape the loop and cost every
    remaining table its comparison. With a naive `except: continue` the table
    would silently contribute nothing and the summary would still say parity is
    fine — the exact false all-clear this sweep exists to end. So the table is
    named in `errors`, left OUT of `presence_by_table` (no finding is asserted
    about it), and the sweep carries on with the others."""
    _add_customer(db, "cust-local-only")

    real_execute = db.execute

    def _unreadable_customers(stmt, *a, **kw):
        if "FROM customers" in str(stmt):
            raise RuntimeError("no such table: customers")
        return real_execute(stmt, *a, **kw)

    monkeypatch.setattr(db, "execute", _unreadable_customers)

    summary = _run(db, monkeypatch, {
        "products": [{"id": 5, "uid": "prod-cloud-only", "name": "Sugar 50kg"}],
    })

    assert any("presence customers" in e for e in summary["errors"]), summary["errors"]
    # Unknown, so no verdict is recorded for it either way.
    assert "customers" not in summary["presence_by_table"]
    # …and the failure was contained: the next table was still compared.
    assert summary["presence_by_table"]["products"]["cloud_only"] == 1


def test_a_failing_sweep_does_not_cost_the_caller_the_parity_findings(db, monkeypatch):
    """The sweep is an ADDITION to parity, so it must not be able to take
    parity down with it. If it throws, the §5 findings computed before it still
    reach the caller and the failure is recorded rather than swallowed."""
    def _boom(*a, **kw):
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(SW, "_parity_presence_sweep", _boom)

    summary = _run(db, monkeypatch, {"customers": []})

    assert any("presence sweep failed" in e for e in summary["errors"]), summary["errors"]
    # Parity itself still answered.
    assert summary["business_id"] == BID
    assert "paid_state" in summary
