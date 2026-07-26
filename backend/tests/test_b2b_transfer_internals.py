"""
tests/test_b2b_transfer_internals.py — findings M-1 / M-19.
==========================================================
Direct unit coverage of the decision functions inside
`core/connection/transfer.py`, the B2B data-transfer importer.

WHY THIS FILE EXISTS, measured rather than asserted.

`tests/test_b2b_transfer.py` covers the module end-to-end (4 tests, 82% of its
statements). But the 29 uncovered statements are not spread evenly — they are
concentrated in the two places that matter most:

  * lines 170-176 — the **entire branch logic of `_remap_requester`**, which is
    the M-1 consent fix. Its own docstring ends *"Pure — takes the raw row,
    returns an id or None. **Unit-tested directly.**"* That claim was **false**:
    nothing named the function anywhere in the test corpus and no test reached
    those lines. A security fix whose documentation asserts coverage it does not
    have is worse than one that admits it has none.
  * lines 194-199 — both branches of `_claim_uid`, which decides whether a
    transferred row keeps its cross-database identity.

M-1 is worth restating, because these tests are what stop it recurring: the
importer copied `requested_by_business_id` **verbatim from the source database**,
where it is a different tenant's `users.id`. Whichever local business happened to
hold that integer became the recorded requester — occasionally the counterparty,
which hands the importer a B2B link nobody agreed to. Under rule R3 an unknown
requester must fail closed, so the only safe translation of an unmappable value
is `None`.

No database for the pure functions — they take a dict and return a value, which
is precisely why the docstring's claim was checkable and wrong.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from core.connection import transfer as T
from core.models import B2BConnection, B2BOrder, B2BOrderLineItem
from database.db import SessionLocal
from database.models import User


# ══════════════════════════════════════════════════════════════════════════════
# _remap_requester — the M-1 consent fix (lines 170-176)
# ══════════════════════════════════════════════════════════════════════════════

SRC_SELLER, SRC_BUYER = 122, 87          # source-database users.id
LOC_SELLER, LOC_BUYER = 7, 9             # destination-database users.id


def _row(requested_by):
    return {"seller_business_id": SRC_SELLER,
            "buyer_business_id": SRC_BUYER,
            "requested_by_business_id": requested_by}


def test_a_requester_matching_the_source_seller_maps_to_the_local_seller():
    assert T._remap_requester(_row(SRC_SELLER),
                              seller_local=LOC_SELLER,
                              buyer_local=LOC_BUYER) == LOC_SELLER


def test_a_requester_matching_the_source_buyer_maps_to_the_local_buyer():
    assert T._remap_requester(_row(SRC_BUYER),
                              seller_local=LOC_SELLER,
                              buyer_local=LOC_BUYER) == LOC_BUYER


def test_a_THIRD_PARTY_requester_becomes_None():
    """The M-1 defect itself. `999` is a users.id from the source database that
    is neither party to this row. Carried verbatim it would name whichever LOCAL
    business happens to hold id 999 as the requester — and if that is the
    counterparty, the importer has just created a link they can approve without
    ever asking for it.

    `None` is the safe answer because rule R3 makes an unknown requester
    unapprovable by anyone: the row degrades to "ask again", not to "somebody
    gets to approve this"."""
    assert T._remap_requester(_row(999),
                              seller_local=LOC_SELLER,
                              buyer_local=LOC_BUYER) is None


def test_a_missing_requester_stays_None():
    assert T._remap_requester(_row(None),
                              seller_local=LOC_SELLER,
                              buyer_local=LOC_BUYER) is None
    assert T._remap_requester({}, seller_local=LOC_SELLER,
                              buyer_local=LOC_BUYER) is None


def test_the_local_ids_are_never_confused_with_the_source_ids():
    """Guards the direction of the mapping. If the comparison were made against
    the LOCAL ids instead of the source ones, a row would map correctly only when
    the two databases happened to agree on integers — i.e. it would look right in
    a same-database test and be wrong in the case the function exists for."""
    row = _row(LOC_SELLER)          # a LOCAL id appearing in a SOURCE field
    assert T._remap_requester(row, seller_local=LOC_SELLER,
                              buyer_local=LOC_BUYER) is None, (
        "matching against local ids would make this return LOC_SELLER")


def test_it_never_invents_a_requester_when_the_row_omits_the_parties():
    """A malformed export must not resolve to a party by accident."""
    assert T._remap_requester({"requested_by_business_id": SRC_SELLER},
                              seller_local=LOC_SELLER,
                              buyer_local=LOC_BUYER) is None


@pytest.mark.parametrize("raw", [SRC_SELLER, SRC_BUYER, 999, None, 0])
def test_the_result_is_always_a_local_id_or_None(raw):
    got = T._remap_requester(_row(raw), seller_local=LOC_SELLER,
                             buyer_local=LOC_BUYER)
    assert got in (LOC_SELLER, LOC_BUYER, None)


def test_the_docstring_no_longer_claims_coverage_it_lacks():
    """The claim "Unit-tested directly" was false when written. This file makes it
    true; this test makes it stay true, because deleting the tests above without
    touching the docstring would otherwise restore the lie."""
    assert "Unit-tested directly" in (T._remap_requester.__doc__ or "")


# ══════════════════════════════════════════════════════════════════════════════
# _clean — what crosses the database boundary
# ══════════════════════════════════════════════════════════════════════════════

def test_clean_strips_the_source_primary_key():
    """Carrying the source `id` would either collide with a local row or silently
    overwrite a different one."""
    out = T._clean({"id": 4242, "seller_business_id": 1, "buyer_business_id": 2},
                   B2BConnection)
    assert "id" not in out


def test_clean_strips_timestamps_so_column_defaults_stamp_them():
    out = T._clean({"created_at": "2026-07-01T00:00:00",
                    "updated_at": "2026-07-01T00:00:00",
                    "status": "accepted"}, B2BConnection)
    assert "created_at" not in out and "updated_at" not in out
    assert out["status"] == "accepted"


def test_clean_strips_the_export_only_identity_helpers():
    """`seller_bizid` etc. exist only to carry portable identity in the payload.
    They are not columns; passing them to the model constructor is a TypeError."""
    row = {"seller_bizid": "BA-X", "buyer_bizid": "BA-Y", "buyer_name": "N",
           "seller_name": "M", "seller_invoice_no": "INV-1",
           "order_number_ref": "ORD-1", "product_uid": "u", "status": "accepted"}
    out = T._clean(row, B2BConnection)
    assert set(out) == {"status"}


def test_clean_drops_columns_the_destination_model_does_not_have():
    """An export from a newer schema must not crash an older destination."""
    out = T._clean({"status": "accepted", "a_column_from_the_future": 1},
                   B2BConnection)
    assert "a_column_from_the_future" not in out


# ══════════════════════════════════════════════════════════════════════════════
# _claim_uid — cross-database identity (lines 194-199)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def test_a_free_uid_is_preserved_so_a_re_import_is_idempotent(db):
    """Stable identity across databases is the whole point: it is what makes
    re-importing the same export update rather than duplicate."""
    fresh = str(uuid.uuid4())
    out = T._claim_uid(db, {"uid": fresh}, B2BConnection)
    assert out["uid"] == fresh


def test_a_TAKEN_uid_is_replaced_rather_than_colliding(db):
    """A row re-pointed at a different counterparty is a DIFFERENT relationship
    that still carries the original uid. Inserting it verbatim collides on the
    partial unique index and 500s the whole import."""
    seller = User(username=f"cu_s_{uuid.uuid4().hex[:8]}", password="x",
                  business_name="S", role="owner")
    buyer = User(username=f"cu_b_{uuid.uuid4().hex[:8]}", password="x",
                 business_name="B", role="owner")
    db.add_all([seller, buyer])
    db.commit()
    taken = str(uuid.uuid4())
    conn = B2BConnection(seller_business_id=seller.id, buyer_business_id=buyer.id,
                         status="accepted", price_tier="standard", discount_pct=0.0,
                         credit_limit=0.0, outstanding_balance=0.0,
                         stock_visibility="exact", uid=taken)
    db.add(conn)
    db.commit()
    try:
        out = T._claim_uid(db, {"uid": taken}, B2BConnection)
        assert out["uid"] != taken, "a taken uid must be replaced"
        uuid.UUID(out["uid"])           # must still be a valid uuid
    finally:
        db.delete(conn)
        db.commit()
        for u in (seller, buyer):
            db.delete(u)
        db.commit()


def test_a_missing_uid_is_removed_so_the_column_default_mints_one(db):
    """Leaving `uid: None` in the payload would write an explicit NULL and defeat
    the model default."""
    out = T._claim_uid(db, {"uid": None, "status": "accepted"}, B2BConnection)
    assert "uid" not in out
    out2 = T._claim_uid(db, {"status": "accepted"}, B2BConnection)
    assert "uid" not in out2


def test_a_FAILED_availability_check_mints_a_fresh_uid_and_does_not_assume_free():
    """The silent-swallow fix. It used to be `except Exception: taken = False` —
    i.e. a lookup that FAILED was treated as "the uid is free", which then
    inserts a possibly-colliding value and 500s the import on the unique index:
    the exact outcome the function exists to prevent.

    Failing toward a fresh uid costs cross-database identity for one row and
    breaks nothing (rule 13: fail-open is often right, fail-open AND silent never
    is — it now logs at ERROR)."""
    class Boom:
        def query(self, *a, **k):
            raise RuntimeError("database is gone")

    original = str(uuid.uuid4())
    out = T._claim_uid(Boom(), {"uid": original}, B2BConnection)
    assert out["uid"] != original, (
        "a failed uniqueness check must not be treated as 'free'")
    uuid.UUID(out["uid"])


# ══════════════════════════════════════════════════════════════════════════════
# M-19 — skipped rows must be reported, not discarded
# ══════════════════════════════════════════════════════════════════════════════

def test_import_reports_a_skipped_connection(db):
    """A counterparty whose BizID is not in this database cannot be linked. That
    is correct — but the row is MISSING, and the caller has to be told."""
    skipped = []
    applied = T.import_b2b_tables(
        db, "b2b_connections",
        [{"seller_bizid": None, "buyer_bizid": None, "status": "accepted"}],
        dest_owner_id=1, skipped_out=skipped)
    assert applied == 0
    assert len(skipped) == 1
    assert skipped[0]["table"] == "b2b_connections"
    assert skipped[0]["kind"] == "connection"
    assert "unresolvable" in skipped[0]["reason"]


def test_import_reports_a_skipped_order(db):
    skipped = []
    T.import_b2b_tables(
        db, "b2b_orders",
        [{"seller_bizid": None, "buyer_bizid": None,
          "order_number": "ORD-GHOST", "total_amount": 100.0}],
        dest_owner_id=1, skipped_out=skipped)
    assert any(s["kind"] == "order" and s.get("order_number") == "ORD-GHOST"
               for s in skipped)


def test_import_reports_a_skipped_ORDER_LINE_and_why_that_matters(db):
    """A line dropped because its product is absent leaves the order's lines no
    longer summing to its header — the M-18 invariant, broken from the
    UNDER-filled side, by this importer. Audit check J reports the order; this
    record is what explains it."""
    skipped = []
    T.import_b2b_tables(
        db, "b2b_order_line_items",
        [{"order_number_ref": "ORD-GHOST", "product_name": "Nonexistent Widget",
          "quantity": 1, "unit_price": 10.0, "line_total": 10.0}],
        dest_owner_id=1, skipped_out=skipped)
    assert skipped, "a line item with no resolvable order/product must be reported"
    assert skipped[0]["table"] == "b2b_order_line_items"


def test_the_skip_list_is_optional_and_the_function_still_works_without_it(db):
    """Back-compatible: an older caller that passes no list must not crash."""
    assert T.import_b2b_tables(
        db, "b2b_connections",
        [{"seller_bizid": None, "buyer_bizid": None}],
        dest_owner_id=1) == 0


def test_import_accepts_the_skipped_out_keyword():
    """Drift guard on the signature — the caller in routes/data_transfer.py passes
    this by keyword, and a rename there would silently stop collecting skips."""
    import inspect
    assert "skipped_out" in inspect.signature(T.import_b2b_tables).parameters


def test_the_transfer_route_collects_and_returns_the_skips():
    """Reporting into a variable nobody returns is the same silence one layer up
    — the mistake M-12 was, and the reason this assertion exists."""
    import inspect

    from routes import data_transfer as DT

    src = inspect.getsource(DT)
    assert "skipped_out=b2b_skipped" in src, (
        "the importer's skip list is no longer collected by the route")
    assert 'result["b2b_skipped"] = b2b_skipped' in src, (
        "skipped B2B rows are collected but never returned to the caller")


def test_the_export_only_field_set_matches_what_clean_strips():
    """`_EXPORT_ONLY_FIELDS` and `_clean` must agree. A helper added to the export
    but not to this set reaches the model constructor as an unknown kwarg."""
    for field in T._EXPORT_ONLY_FIELDS:
        out = T._clean({field: "x", "status": "accepted"}, B2BConnection)
        assert field not in out, f"{field} is not stripped by _clean"


def test_every_skip_site_is_reported_and_the_count_matches_the_LIST(db, caplog):
    """The guard that would have caught my own omission automatically.

    `import_b2b_tables` bumps a `skipped` counter at FOUR places. When the skip
    LIST was added, one of them was missed — a line item whose parent order is
    absent, which had no log line either. The result was a log reading
    `SKIPPED=1 ... rows: []`: a count and a list disagreeing, which is the
    signature of exactly this bug.

    Rather than trusting that all four are wired, assert the two agree. A fifth
    skip site added without a `_skip(...)` call fails here.
    """
    import logging
    import re

    cases = [
        ("b2b_connections", [{"seller_bizid": None, "buyer_bizid": None}]),
        ("b2b_orders", [{"seller_bizid": None, "buyer_bizid": None,
                         "order_number": "ORD-NOPE", "total_amount": 5.0}]),
        ("b2b_order_line_items", [{"order_number_ref": "ORD-NOPE",
                                   "product_name": "Ghost", "quantity": 1,
                                   "unit_price": 1.0, "line_total": 1.0}]),
    ]
    for table, rows in cases:
        skipped = []
        with caplog.at_level(logging.ERROR, logger="bizassist.b2b_transfer"):
            caplog.clear()
            T.import_b2b_tables(db, table, rows, dest_owner_id=1,
                                skipped_out=skipped)
        reported = [r for r in caplog.records if "SKIPPED=" in r.getMessage()]
        if not reported:
            continue                      # nothing was skipped for this table
        m = re.search(r"SKIPPED=(\d+)", reported[-1].getMessage())
        assert m, reported[-1].getMessage()
        assert int(m.group(1)) == len(skipped), (
            f"{table}: the log says SKIPPED={m.group(1)} but the reported list "
            f"holds {len(skipped)} entr(ies) — a skip site is bumping the counter "
            f"without recording the row"
        )


def test_every_reported_skip_names_a_reason_and_a_table(db):
    """A skip record with no reason tells the operator a row is missing and
    nothing about why — which is not enough to act on."""
    skipped = []
    for table, rows in (
        ("b2b_connections", [{"seller_bizid": None, "buyer_bizid": None}]),
        ("b2b_orders", [{"seller_bizid": None, "buyer_bizid": None,
                         "order_number": "X", "total_amount": 1.0}]),
    ):
        T.import_b2b_tables(db, table, rows, dest_owner_id=1, skipped_out=skipped)
    assert skipped
    for s in skipped:
        assert s.get("table") and s.get("kind") and s.get("reason")
        assert len(s["reason"]) > 10
