"""
tests/test_uid_cross_db.py
==========================
Step 3 (R-3) — regression tests that lock down the shipped uid match-key
behaviour (STEP3_UID_PLAN.md §7). These are the prerequisite Phase C needs
before it retires the id-fallback / `?remap_ids` natural-key crutches.

  - cross-DB no-collision : same source `id`, different `uid` → never overwrites
    the wrong row (the match is on `uid`, not the per-DB autoincrement `id`).
  - child FK by parent uid : a parent matched/deduped by `uid` feeds the child-FK
    rewrite, so a child row lands on the correct destination parent id.
  - id fallback           : a row with NO `uid` still imports (natural-key match)
    and dedups on re-import — safe during the transition window.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from sqlalchemy import text, inspect
from fastapi.testclient import TestClient

# Importing the app builds the schema (Base.metadata.create_all) on the test DB.
from main_groq import app
from database.db import SessionLocal
from routes.migrate import _import_with_remap

client = TestClient(app)


def _signup(business_name: str) -> dict:
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    return {"bid": r.json()["id"], "username": uname}


# ---------------------------------------------------------------------------
# cross-DB no-collision — same SOURCE id, different uid → distinct rows.
# The classic "two-ID problem": local id=10 != cloud id=10. Matching on `uid`
# (not `id`) must keep them as two separate rows, never overwrite one with the
# other.
# ---------------------------------------------------------------------------
def test_uid_no_collision_same_source_id_diff_uid():
    owner = _signup("NoCollision Co")
    bid = owner["bid"]
    SRC = 600001                                   # SAME source id for BOTH rows
    uid_a, uid_b = str(uuid.uuid4()), str(uuid.uuid4())
    db = SessionLocal()
    try:
        existing = set(inspect(db.bind).get_table_names())

        a = [{"id": SRC, "business_id": 4242, "uid": uid_a,
              "name": "ProdA", "barcode": "NC-A",
              "selling_price": 1.0, "track_inventory": True}]
        assert _import_with_remap(db, "products", a, bid, 4242, existing, {}) == 1

        # Same SOURCE id, different uid + natural key → must INSERT, not overwrite A.
        b = [{"id": SRC, "business_id": 4242, "uid": uid_b,
              "name": "ProdB", "barcode": "NC-B",
              "selling_price": 2.0, "track_inventory": True}]
        assert _import_with_remap(db, "products", b, bid, 4242, existing, {}) == 1

        rows = db.execute(
            text("SELECT uid, barcode FROM products WHERE business_id = :b AND uid IN (:ua, :ub)"),
            {"b": bid, "ua": uid_a, "ub": uid_b},
        ).fetchall()
        got = {r[0]: r[1] for r in rows}
        assert got.get(uid_a) == "NC-A"            # original untouched
        assert got.get(uid_b) == "NC-B"            # inserted as a distinct row
    finally:
        db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# child FK by parent uid — a parent deduped on uid (under a NEW source id) feeds
# the id_maps used to rewrite the child's FK to the correct destination parent.
# ---------------------------------------------------------------------------
def test_child_fk_resolves_to_uid_deduped_parent():
    owner = _signup("ChildFK Co")
    bid = owner["bid"]
    SRC_OWNER = 9001
    uid_p = str(uuid.uuid4())
    db = SessionLocal()
    try:
        existing = set(inspect(db.bind).get_table_names())

        # Seed the parent product (carries uid_p).
        p1 = [{"id": 770001, "business_id": SRC_OWNER, "uid": uid_p,
               "name": "ParentProd", "barcode": "CFK-1",
               "selling_price": 3.0, "track_inventory": True}]
        assert _import_with_remap(db, "products", p1, bid, SRC_OWNER, existing, {}) == 1
        dest_pid = db.execute(
            text("SELECT id FROM products WHERE uid = :u AND business_id = :b"),
            {"u": uid_p, "b": bid},
        ).scalar()
        assert dest_pid is not None

        # Re-import the SAME parent under a DIFFERENT source id → dedups on uid,
        # recording the destination id for child-FK rewrites.
        id_maps: dict = {}
        p2 = [{"id": 770999, "business_id": SRC_OWNER, "uid": uid_p,
               "name": "ParentProd", "barcode": "CFK-1",
               "selling_price": 3.0, "track_inventory": True}]
        assert _import_with_remap(db, "products", p2, bid, SRC_OWNER, existing, id_maps) == 0
        assert id_maps["products"][770999] == dest_pid

        # Child inventory references the NEW source parent id (770999) → its FK
        # must be rewritten to the existing destination parent id.
        inv_uid = str(uuid.uuid4())
        inv = [{"id": 770500, "business_id": SRC_OWNER, "product_id": 770999, "uid": inv_uid,
                "product_name": "ParentProd", "stock": 7}]
        assert _import_with_remap(db, "inventory", inv, bid, SRC_OWNER, existing, id_maps) == 1
        fk = db.execute(
            text("SELECT product_id FROM inventory "
                 "WHERE product_name = 'ParentProd' AND business_id = :b"),
            {"b": bid},
        ).scalar()
        assert fk == dest_pid
    finally:
        db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# id fallback REMOVED — a pre-uid row (no `uid` key) is now REJECTED.
# Phase C makes `uid` mandatory.
# ---------------------------------------------------------------------------
def test_id_fallback_row_without_uid_is_rejected():
    owner = _signup("IdFallback Co")
    bid = owner["bid"]
    SRC_OWNER = 8800
    db = SessionLocal()
    try:
        existing = set(inspect(db.bind).get_table_names())

        # No `uid` key at all.
        p = [{"id": 880001, "business_id": SRC_OWNER,
              "name": "NoUidProd", "barcode": "IDF-1",
              "selling_price": 4.0, "track_inventory": True}]
        
        # Phase C strictly rejects rows without a uid.
        assert _import_with_remap(db, "products", p, bid, SRC_OWNER, existing, {}) == 0
        
        cnt = db.execute(
            text("SELECT COUNT(*) FROM products WHERE barcode = 'IDF-1' AND business_id = :b"),
            {"b": bid},
        ).scalar()
        assert cnt == 0
    finally:
        db.rollback()
        db.close()
