"""
tests/test_bulk_product_active.py
=================================
Bulk deactivate/reactivate from the catalogue table.

ALL-OR-NOTHING is the contract: either every selected product flips or none
does. After the action, the table you are looking at is the truth. A partial
apply would leave a 40-row selection half-done with no way to tell which half
without re-reading every row.

Registered in the ACTION registry (services/actions.py) rather than as a
bespoke /api/bulk route, so it inherits the preview→confirm step, the
fingerprint drift check, the replay wall and the daily cap — and so the AI
agent can propose it and render the same preview.
"""
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest                                        # noqa: E402
from fastapi.testclient import TestClient            # noqa: E402
from main_groq import app                            # noqa: E402
from database.db import SessionLocal                 # noqa: E402
from database.models import Product                  # noqa: E402
from services import actions as A                    # noqa: E402

client = TestClient(app)


def _signup(name="Bulk Co"):
    uname = f"blk_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": name})
    assert r.status_code == 200, r.text
    b = r.json()
    return b["id"], {"Authorization": f"Bearer {b['token']}"}


def _products(bid, n=3, active=True):
    db = SessionLocal()
    try:
        made = []
        for i in range(n):
            p = Product(business_id=bid, name=f"Item {uuid.uuid4().hex[:5]}",
                        selling_price=10.0, is_active=active)
            db.add(p)
            made.append(p)
        db.commit()
        return [p.id for p in made]
    finally:
        db.close()


def _active_map(ids):
    db = SessionLocal()
    try:
        return {p.id: bool(p.is_active)
                for p in db.query(Product).filter(Product.id.in_(ids)).all()}
    finally:
        db.close()


# ── the happy path ───────────────────────────────────────────────────────────

def test_preview_changes_nothing():
    """A preview that mutates is not a preview."""
    bid, _ = _signup()
    ids = _products(bid, 3)
    pv = A.preview("bulk_set_product_active", bid, {"ids": ids, "active": False})
    assert pv["executable"] is True
    assert len(pv["items"]) == 3
    assert all(v is True for v in _active_map(ids).values()), "preview wrote to the DB"


def test_execute_flips_every_selected_row():
    bid, _ = _signup()
    ids = _products(bid, 4)
    res = A.execute("bulk_set_product_active", bid, {"ids": ids, "active": False})
    assert res["ok"] is True and res["executed"] == 4
    assert all(v is False for v in _active_map(ids).values())


def test_reactivate_is_the_same_action_with_a_flag():
    bid, _ = _signup()
    ids = _products(bid, 2, active=False)
    res = A.execute("bulk_set_product_active", bid, {"ids": ids, "active": True})
    assert res["executed"] == 2
    assert all(v is True for v in _active_map(ids).values())


def test_rows_already_in_the_target_state_are_not_counted():
    """The number confirmed must equal the number that changes."""
    bid, _ = _signup()
    already_off = _products(bid, 2, active=False)
    on = _products(bid, 1, active=True)
    pv = A.preview("bulk_set_product_active", bid,
                   {"ids": already_off + on, "active": False})
    assert len(pv["items"]) == 1, "already-inactive rows were counted as changes"
    res = A.execute("bulk_set_product_active", bid,
                    {"ids": already_off + on, "active": False})
    assert res["executed"] == 1


# ── all-or-nothing ───────────────────────────────────────────────────────────

def test_one_unreadable_id_stops_the_whole_batch():
    """The core contract. 9 good ids + 1 bad must leave all 9 untouched."""
    bid, _ = _signup()
    ids = _products(bid, 9)
    before = _active_map(ids)

    res = A.execute("bulk_set_product_active", bid,
                    {"ids": ids + [99_999_999], "active": False})

    assert res["ok"] is False
    assert res["executed"] == 0
    assert res["blocked"] and res["blocked"][0]["id"] == 99_999_999
    assert _active_map(ids) == before, "a partial apply landed despite all-or-nothing"


def test_preview_refuses_to_offer_a_batch_it_cannot_complete():
    bid, _ = _signup()
    ids = _products(bid, 3)
    pv = A.preview("bulk_set_product_active", bid,
                   {"ids": ids + [99_999_999], "active": False})
    assert pv["executable"] is False, "offered Confirm on a batch that must fail"
    assert pv["blocked"]


# ── tenant isolation ─────────────────────────────────────────────────────────

def test_another_businesss_products_are_never_touched():
    """The tenant filter is in the id-selection query itself.

    A cross-tenant id reads as not-found rather than forbidden — the same choice
    every route here makes, so probing tells an attacker nothing.
    """
    mine_bid, _ = _signup("Mine")
    theirs_bid, _ = _signup("Theirs")
    mine = _products(mine_bid, 2)
    theirs = _products(theirs_bid, 2)
    before = _active_map(theirs)

    res = A.execute("bulk_set_product_active", mine_bid,
                    {"ids": mine + theirs, "active": False})

    assert res["ok"] is False, "a cross-tenant id was accepted"
    assert {b["id"] for b in res["blocked"]} == set(theirs)
    assert _active_map(theirs) == before
    assert all(v is True for v in _active_map(mine).values()), "own rows changed anyway"


# ── input handling ───────────────────────────────────────────────────────────

def test_empty_selection_is_refused_not_applied_to_everything():
    """An empty id list must never widen into 'all rows'."""
    bid, _ = _signup()
    ids = _products(bid, 3)
    res = A.execute("bulk_set_product_active", bid, {"ids": [], "active": False})
    assert res["executed"] == 0
    assert all(v is True for v in _active_map(ids).values())


def test_junk_ids_do_not_crash_the_action():
    bid, _ = _signup()
    res = A.execute("bulk_set_product_active", bid,
                    {"ids": ["abc", None, 1.5], "active": False})
    assert res["ok"] is False and res["executed"] == 0


# ── registry wiring ──────────────────────────────────────────────────────────

def test_it_is_a_registered_action_so_the_rails_apply():
    """Registration is what gives it preview/confirm, the fingerprint drift
    check, the replay wall, the daily cap and AI access. A bespoke route would
    have had none of them."""
    assert A.is_action("bulk_set_product_active")
    from services.action_rails import daily_cap
    assert daily_cap("bulk_set_product_active") == 200

def test_the_preview_fingerprint_moves_when_the_selection_moves():
    """The confirm token binds to this. Two different selections must not share
    a fingerprint, or a confirm could apply to the wrong batch."""
    bid, _ = _signup()
    a = _products(bid, 2)
    b = _products(bid, 2)
    fa = A.preview_fingerprint(A.preview("bulk_set_product_active", bid, {"ids": a, "active": False}))
    fb = A.preview_fingerprint(A.preview("bulk_set_product_active", bid, {"ids": b, "active": False}))
    assert fa != fb
