"""
tests/test_batch_price_tiers.py
===============================
A batch carried selling price, cost and MRP — but not wholesale or distributor.

That left a real gap. "New Batch" mode exists so a delivery at a different price
lands on the BATCH instead of overwriting the product, but with only three of the
five tiers stored, a batch-specific wholesale rate had nowhere to go: the owner
could either clobber the product's wholesale tier or lose the distinction
entirely. POS reads batch prices through getPriceOptions, so a tier the batch
cannot store is a tier the cashier can never pick for that stock.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient      # noqa: E402
from main_groq import app                       # noqa: E402

client = TestClient(app)


def _account():
    uname = f"bt_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Batch Tier Co",
    })
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _product(auth, **over):
    body = {"name": f"Widget {uuid.uuid4().hex[:5]}", "selling_price": 100.0,
            "cost_price": 60.0, "wholesale_price": 80.0, "distributor_price": 70.0,
            "mrp": 120.0, "unit": "pcs"}
    body.update(over)
    r = client.post("/products", json=body, headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"] if "id" in r.json() else r.json()["product"]["id"]


def _batches(auth, pid):
    r = client.get(f"/products/{pid}/stock", headers=auth)
    assert r.status_code in (200, 201), r.text
    return r.json().get("batches", [])


def test_a_batch_records_its_own_wholesale_and_distributor():
    """The point of New Batch mode: this delivery's trade rates live on the
    batch, and the product's own tiers are free to stay where they were."""
    auth = _account()
    pid = _product(auth)

    r = client.post(f"/products/{pid}/stock/adjustment", headers=auth, json={
        "qty_delta": 10, "batch_no": "B-NEW", "note": "intake",
        "selling_price": 111.0, "cost_price": 66.0, "mrp": 130.0,
        "wholesale_price": 88.0, "distributor_price": 77.0,
    })
    assert r.status_code in (200, 201), r.text

    b = next((x for x in _batches(auth, pid) if x.get("batch_no") == "B-NEW"), None)
    assert b is not None, "the batch was not created"
    assert b["wholesale_price"] == 88.0, (
        "a batch-specific wholesale rate was dropped — the only way left to "
        f"record it is overwriting the product tier: {b}"
    )
    assert b["distributor_price"] == 77.0
    assert b["selling_price"] == 111.0


def test_a_batch_inherits_the_product_tiers_when_not_given():
    """Omitted means unchanged, matching selling/cost/mrp — so an intake that
    does not mention wholesale still leaves the batch priced sensibly."""
    auth = _account()
    pid = _product(auth)

    r = client.post(f"/products/{pid}/stock/adjustment", headers=auth, json={
        "qty_delta": 5, "batch_no": "B-INHERIT", "note": "intake",
    })
    assert r.status_code in (200, 201), r.text

    b = next((x for x in _batches(auth, pid) if x.get("batch_no") == "B-INHERIT"), None)
    assert b is not None
    assert b["wholesale_price"] == 80.0, "should fall back to the product's tier"
    assert b["distributor_price"] == 70.0


def test_two_batches_hold_different_wholesale_rates():
    """The distinction that could not be expressed before."""
    auth = _account()
    pid = _product(auth)

    for batch, whsl in (("B-OLD", 80.0), ("B-NEW", 95.0)):
        r = client.post(f"/products/{pid}/stock/adjustment", headers=auth, json={
            "qty_delta": 5, "batch_no": batch, "note": "intake",
            "wholesale_price": whsl,
        })
        assert r.status_code in (200, 201), r.text

    got = {b["batch_no"]: b["wholesale_price"] for b in _batches(auth, pid)}
    assert got.get("B-OLD") == 80.0 and got.get("B-NEW") == 95.0, got


def test_updating_an_existing_batch_with_ONLY_a_wholesale_rate():
    """The gate bug, pinned. The batch-pricing block was entered only when
    selling/cost/mrp was present, so a second delivery that changed nothing but
    the trade rate silently did nothing — and looked identical to success."""
    auth = _account()
    pid = _product(auth)

    r = client.post(f"/products/{pid}/stock/adjustment", headers=auth, json={
        "note": "intake", "qty_delta": 5, "batch_no": "B-1", "selling_price": 100.0, "wholesale_price": 80.0,
    })
    assert r.status_code in (200, 201), r.text

    # Second delivery, same batch, ONLY the wholesale rate moves.
    r = client.post(f"/products/{pid}/stock/adjustment", headers=auth, json={
        "note": "intake", "qty_delta": 5, "batch_no": "B-1", "wholesale_price": 91.0,
    })
    assert r.status_code in (200, 201), r.text

    b = next(x for x in _batches(auth, pid) if x.get("batch_no") == "B-1")
    assert b["wholesale_price"] == 91.0, f"the update was dropped: {b}"
    assert b["selling_price"] == 100.0, "an untouched tier must not be disturbed"


def test_a_row_with_no_batch_number_also_carries_the_tiers():
    """Not every intake names a batch. The unbatched projection row must hold
    the tiers too, or POS loses them for exactly the simplest case."""
    auth = _account()
    pid = _product(auth)
    r = client.post(f"/products/{pid}/stock/adjustment", headers=auth, json={
        "note": "intake", "qty_delta": 3, "wholesale_price": 84.0, "distributor_price": 74.0,
    })
    assert r.status_code in (200, 201), r.text

    rows = _batches(auth, pid)
    assert rows, "no inventory projection was created"
    assert any(x.get("wholesale_price") == 84.0 for x in rows), rows


def test_an_explicit_zero_unsets_a_tier():
    """0 is a deliberate 'this tier does not apply'. It must persist as 0 —
    getPriceOptions then drops it, so POS stops offering it."""
    auth = _account()
    pid = _product(auth)
    r = client.post(f"/products/{pid}/stock/adjustment", headers=auth, json={
        "note": "intake", "qty_delta": 2, "batch_no": "B-ZERO", "wholesale_price": 0,
    })
    assert r.status_code in (200, 201), r.text
    b = next(x for x in _batches(auth, pid) if x.get("batch_no") == "B-ZERO")
    assert b["wholesale_price"] == 0


def test_removing_stock_still_records_the_tiers():
    """A negative delta is a valid movement; it must not bypass batch pricing."""
    auth = _account()
    pid = _product(auth)
    client.post(f"/products/{pid}/stock/adjustment", headers=auth,
                json={"note": "intake", "qty_delta": 10, "batch_no": "B-RET", "wholesale_price": 80.0})
    r = client.post(f"/products/{pid}/stock/adjustment", headers=auth,
                    json={"note": "intake", "qty_delta": -3, "batch_no": "B-RET", "wholesale_price": 82.0})
    assert r.status_code in (200, 201), r.text
    b = next(x for x in _batches(auth, pid) if x.get("batch_no") == "B-RET")
    assert b["wholesale_price"] == 82.0


def test_a_non_finite_tier_is_rejected():
    """NaN/Infinity must never reach a money column."""
    auth = _account()
    pid = _product(auth)
    # Asserted against the validator, not the endpoint. Round-tripping NaN
    # through HTTP fails inside FastAPI's own 422 renderer (it echoes the
    # offending value, and NaN is not JSON) — which tests the framework's error
    # formatting rather than this guard.
    import math
    import pytest
    from core.api.products import StockAdjustmentRequest

    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            StockAdjustmentRequest(qty_delta=1, note="intake", batch_no="B-NF",
                                   wholesale_price=bad)
        with pytest.raises(ValueError):
            StockAdjustmentRequest(qty_delta=1, note="intake", batch_no="B-NF",
                                   distributor_price=bad)

    # …and a finite one is fine, so the guard is not simply rejecting everything.
    ok = StockAdjustmentRequest(qty_delta=1, note="intake", batch_no="B-NF",
                                wholesale_price=88.0)
    assert math.isfinite(ok.wholesale_price)


def test_the_tiers_cross_the_sync_boundary():
    """`inventory` is a synced table, so a new column is only useful if it is
    actually serialised into the outbox payload."""
    import json as _json
    from database.models import _serialize_orm_obj, Inventory
    from database.db import SessionLocal

    cols = set(Inventory.__table__.columns.keys())
    assert {"wholesale_price", "distributor_price"} <= cols

    db = SessionLocal()
    try:
        row = db.query(Inventory).filter(Inventory.wholesale_price.isnot(None)).first()
        if row is None:
            return  # nothing to serialise in this run; the column check above stands
        payload = _serialize_orm_obj(row, db.connection())
        assert "wholesale_price" in payload and "distributor_price" in payload, sorted(payload)
    finally:
        db.close()


def test_a_negative_tier_is_rejected():
    """Same guard as the other money fields — a negative price must not reach
    the ledger."""
    auth = _account()
    pid = _product(auth)
    r = client.post(f"/products/{pid}/stock/adjustment", headers=auth, json={
        "note": "intake", "qty_delta": 1, "batch_no": "B-BAD", "wholesale_price": -5,
    })
    assert r.status_code == 422, r.text
