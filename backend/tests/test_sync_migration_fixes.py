"""
tests/test_sync_migration_fixes.py
==================================
Regression tests for the 2026-06-26 sync/migration hardening pass
(see SYNC_MIGRATION_AUDIT.md). Each test names the finding it locks down.

  M-1  partial import isolation — a bad row must not discard rows already imported
  M-4  upsert preserves unmapped columns — ON CONFLICT DO UPDATE, not INSERT OR REPLACE
  R-1  cross-thread SSE delivery — broadcast_threadsafe reaches a main-loop subscriber
"""
import os
import sys
import asyncio
import threading
import random
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from sqlalchemy import text, inspect
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# Importing the app builds the schema (Base.metadata.create_all) on the test DB.
from main_groq import app
from database.db import SessionLocal
# routes/migrate.py is an UNMOUNTED, DEPRECATED duplicate of these endpoints —
# retained for a later cleanup pass, but it serves nothing (it declares
# /api/migrate/*; the mounted module declares /api/data-transfer/*).
# `routes/data_transfer.py` is what main_groq.py mounts, so these tests now
# exercise the code that really runs. Testing the dead copy was worse than
# useless: it reported green for code that cannot execute, while its
# `_upsert_users` kept a defect the live one had already fixed.
from routes.data_transfer import _upsert_rows, _resolve_owner_id, _import_with_remap
from services.realtime import RealtimeManager

client = TestClient(app)


def _rid() -> int:
    return random.randint(10_000_000, 99_000_000)


def _signup(business_name: str) -> dict:
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return {"bid": b["id"], "username": uname}


# ---------------------------------------------------------------------------
# M-1 — one poison row must NOT wipe rows already imported in the same txn
# ---------------------------------------------------------------------------
def test_partial_import_does_not_discard_prior_rows(monkeypatch):
    db = SessionLocal()
    good1, poison, good2 = _rid(), _rid(), _rid()
    try:
        original_execute = db.execute

        def failing_execute(statement, params=None, *args, **kwargs):
            # Make exactly the poison row's INSERT blow up.
            if isinstance(params, dict) and params.get("name") == "POISON":
                raise RuntimeError("simulated bad row")
            return original_execute(statement, params, *args, **kwargs)

        monkeypatch.setattr(db, "execute", failing_execute)

        rows = [
            {"id": good1,  "business_id": 1, "name": "GoodBefore"},
            {"id": poison, "business_id": 1, "name": "POISON"},
            {"id": good2,  "business_id": 1, "name": "GoodAfter"},
        ]
        applied = _upsert_rows(db, "customers", rows, {"customers"})

        # Only the two good rows count; the poison row was rolled back on its
        # own SAVEPOINT (the old db.rollback() would have nuked GoodBefore too).
        assert applied == 2

        monkeypatch.undo()  # restore execute for the verifying SELECT
        names = {
            r[0]
            for r in db.execute(
                text("SELECT name FROM customers WHERE id IN (:a, :b, :c)"),
                {"a": good1, "b": poison, "c": good2},
            ).fetchall()
        }
        assert names == {"GoodBefore", "GoodAfter"}  # poison absent, goods survive
    finally:
        db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# M-4 — upsert must keep columns not present in the incoming row
# ---------------------------------------------------------------------------
def test_upsert_preserves_unmapped_columns():
    db = SessionLocal()
    cid = _rid()
    try:
        _upsert_rows(db, "customers",
                     [{"id": cid, "business_id": 1, "name": "Orig", "phone": "111"}],
                     {"customers"})
        # Second upsert omits phone — DO UPDATE must leave the stored phone intact.
        # The old INSERT OR REPLACE would delete+reinsert and null it out.
        _upsert_rows(db, "customers",
                     [{"id": cid, "business_id": 1, "name": "Renamed"}],
                     {"customers"})

        row = db.execute(
            text("SELECT name, phone FROM customers WHERE id = :i"), {"i": cid}
        ).first()
        assert row[0] == "Renamed"
        assert row[1] == "111"   # preserved
    finally:
        db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# R-1 — broadcast from a worker thread must reach a main-loop subscriber
# ---------------------------------------------------------------------------
def test_broadcast_threadsafe_no_loop_is_safe():
    mgr = RealtimeManager()
    # No loop registered → returns False instead of raising / silently dropping.
    assert mgr.broadcast_threadsafe(1, {"type": "sync.trigger", "entity": "invoice"}) is False


def test_broadcast_threadsafe_delivers_to_subscriber():
    mgr = RealtimeManager()
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run_loop():
        asyncio.set_event_loop(loop)
        mgr.set_loop(loop)
        ready.set()
        loop.run_forever()

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    assert ready.wait(2.0)

    async def _subscribe():
        return mgr.subscribe(7)  # asyncio.Queue() binds to THIS loop

    q = asyncio.run_coroutine_threadsafe(_subscribe(), loop).result(2.0)

    # Call from the main (worker-simulating) thread — different thread than loop.
    assert mgr.broadcast_threadsafe(7, {"type": "sync.trigger", "entity": "invoice"}) is True

    got = asyncio.run_coroutine_threadsafe(q.get(), loop).result(2.0)
    assert got["entity"] == "invoice"

    loop.call_soon_threadsafe(loop.stop)
    t.join(2.0)


# ---------------------------------------------------------------------------
# Owner resolution (D9): BizID, or REFUSE.
#
# This section used to read "BizID confirmed by username → username → JWT id",
# which described `routes/migrate.py`'s resolver. The mounted module requires the
# BizID and raises 403 without it. The fallbacks were the leak they look like a
# kindness against: a token's numeric `id` means nothing in another database, so
# resolving to it targets whichever local business holds that number.
# ---------------------------------------------------------------------------
def test_resolve_owner_bizid_confirmed_by_username():
    owner = _signup("BizID Resolve Co")
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT id, public_id, username FROM users WHERE id = :i"),
            {"i": owner["bid"]},
        ).first()
        oid, pub, uname = int(row[0]), row[1], row[2]
        nonexistent_user = f"nope_{uuid.uuid4().hex[:6]}"

        # ── THE RESOLVER IS NOW FAIL-CLOSED ──────────────────────────────────
        # These assertions used to describe `routes/migrate.py`'s resolver, which
        # fell back to username and then to the raw JWT id. That module is
        # deprecated and unmounted; the MOUNTED one calls
        # `resolve_business_id_in_db(..., require_public_id=True)`, which is the
        # hardening from `e770402` ("enforce strict BizID public_id tenant
        # resolution … to eliminate integer ID leaks").
        #
        # The fallbacks were the leak. A token's numeric `id` means nothing in
        # another database — the same business is 7 locally and 42 on the cloud —
        # so resolving to it silently targets whichever local business happens to
        # hold that number. Refusing is the only safe answer.
        #
        # Repointing this test off the dead module is what exposed the gap: it
        # had been green against a resolver that does not run.

        # 1. BizID + matching username → resolves.
        assert _resolve_owner_id({"public_id": pub, "username": uname, "id": 999_999}, db) == oid

        # 2. Unknown BizID → REFUSED. Not a username fallback.
        with pytest.raises(HTTPException) as ei:
            _resolve_owner_id({"public_id": "missing-bizid", "username": uname, "id": 999_999}, db)
        assert ei.value.status_code == 403

        # 3. Correct BizID resolves on the BizID alone. The old resolver also
        #    required the username to agree, because BizIDs were minted per-DB
        #    and could collide; `public_id` is now UNIQUE-indexed, so the BizID
        #    is sufficient and a wrong username no longer changes the answer.
        assert _resolve_owner_id({"public_id": pub, "username": nonexistent_user, "id": 999_999}, db) == oid

        # 4. No BizID at all → ALSO refused. `_resolve_owner_id` passes
        #    require_public_id=True, so the username/JWT-id fallbacks further
        #    down `resolve_business_id_in_db` are unreachable from this path.
        #    A data-transfer import writes another database's rows into this one;
        #    doing that on an identity that could not be proven is the whole
        #    class of bug the BizID work exists to close.
        with pytest.raises(HTTPException) as ei2:
            _resolve_owner_id({"username": uname, "id": 999_999}, db)
        assert ei2.value.status_code == 403
    finally:
        db.close()


# ---------------------------------------------------------------------------
# R-3 entity-id remap: fresh ids + FK rewrite + natural-key idempotency
# ---------------------------------------------------------------------------
def test_import_remap_assigns_new_ids_and_rewrites_fk():
    owner = _signup("Remap Co")
    bid = owner["bid"]
    LOCAL_OWNER = 1234567  # pretend the source DB used a different owner id
    db = SessionLocal()
    try:
        existing = set(inspect(db.bind).get_table_names())
        id_maps: dict = {}

        # Product carries a source id that must NOT be reused on the destination.
        prods = [{
            "id": 999001, "business_id": LOCAL_OWNER, "name": "RemapWidget",
            "barcode": "BCD-REMAP-1", "selling_price": 10.0, "track_inventory": True,
        }]
        n1 = _import_with_remap(db, "products", prods, bid, LOCAL_OWNER, existing, id_maps)
        assert n1 == 1
        new_pid = id_maps["products"][999001]
        assert new_pid != 999001                      # got a fresh id

        # Inventory references the OLD product id → must be rewritten to new_pid.
        inv = [{
            "id": 999002, "business_id": LOCAL_OWNER, "product_id": 999001,
            "product_name": "RemapWidget", "stock": 5,
        }]
        n2 = _import_with_remap(db, "inventory", inv, bid, LOCAL_OWNER, existing, id_maps)
        assert n2 == 1
        row = db.execute(
            text("SELECT product_id, business_id FROM inventory "
                 "WHERE product_name = 'RemapWidget' AND business_id = :b"),
            {"b": bid},
        ).first()
        assert row[0] == new_pid                       # FK rewritten
        assert row[1] == bid                           # owner remapped LOCAL_OWNER → bid

        # Idempotency: re-importing the product dedups on its barcode (no duplicate).
        _import_with_remap(db, "products", prods, bid, LOCAL_OWNER, existing, {})
        cnt = db.execute(
            text("SELECT COUNT(*) FROM products WHERE barcode = 'BCD-REMAP-1' AND business_id = :b"),
            {"b": bid},
        ).scalar()
        assert cnt == 1
    finally:
        db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# LWW merge mode: insert new, keep newer, never blindly overwrite
# ---------------------------------------------------------------------------
def test_merge_lww_keeps_newer_inserts_new():
    db = SessionLocal()
    cid = _rid()
    cid2 = _rid()
    try:
        # Seed a local row with a NEWER timestamp.
        _upsert_rows(db, "customers",
                     [{"id": cid, "business_id": 1, "name": "NewLocal", "updated_at": "2026-06-26T12:00:00"}],
                     {"customers"})
        # Merge an OLDER incoming version → must be KEPT (not overwritten).
        _upsert_rows(db, "customers",
                     [{"id": cid, "business_id": 1, "name": "OldIncoming", "updated_at": "2026-06-20T00:00:00"}],
                     {"customers"}, merge=True)
        assert db.execute(text("SELECT name FROM customers WHERE id=:i"), {"i": cid}).scalar() == "NewLocal"

        # Merge a NEWER incoming version → applied.
        _upsert_rows(db, "customers",
                     [{"id": cid, "business_id": 1, "name": "NewerIncoming", "updated_at": "2026-06-27T00:00:00"}],
                     {"customers"}, merge=True)
        assert db.execute(text("SELECT name FROM customers WHERE id=:i"), {"i": cid}).scalar() == "NewerIncoming"

        # Merge a brand-new row → inserted.
        _upsert_rows(db, "customers",
                     [{"id": cid2, "business_id": 1, "name": "FreshRow", "updated_at": "2026-06-26T00:00:00"}],
                     {"customers"}, merge=True)
        assert db.execute(text("SELECT COUNT(*) FROM customers WHERE id=:i"), {"i": cid2}).scalar() == 1
    finally:
        db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# Step 3 / R-3 Phase B.1 — remap import dedups on durable `uid` FIRST, ahead of
# the fuzzy natural key. Same uid + a CHANGED natural key must still match the
# same row (no duplicate); the matched destination id feeds child-FK rewrites.
# ---------------------------------------------------------------------------
def test_import_remap_dedups_on_uid_over_natural_key():
    owner = _signup("UID Dedup Co")
    bid = owner["bid"]
    LOCAL_OWNER = 7654321          # source DB used a different owner id
    UID = str(uuid.uuid4())
    db = SessionLocal()
    try:
        existing = set(inspect(db.bind).get_table_names())

        # First import: product carrying a uid and barcode UID-B1.
        p1 = [{
            "id": 555001, "business_id": LOCAL_OWNER, "uid": UID,
            "name": "UidWidget", "barcode": "UID-B1",
            "selling_price": 5.0, "track_inventory": True,
        }]
        assert _import_with_remap(db, "products", p1, bid, LOCAL_OWNER, existing, {}) == 1
        dest_id = db.execute(
            text("SELECT id FROM products WHERE uid = :u AND business_id = :b"),
            {"u": UID, "b": bid},
        ).scalar()
        assert dest_id is not None

        # Second import: SAME uid, but a DIFFERENT barcode (natural key) and a
        # different source id. Natural-key match would FAIL (new barcode) and
        # insert a duplicate; uid match must catch it → dedup, no insert.
        id_maps: dict = {}
        p2 = [{
            "id": 555999, "business_id": LOCAL_OWNER, "uid": UID,
            "name": "UidWidget Renamed", "barcode": "UID-B2-DIFFERENT",
            "selling_price": 9.0, "track_inventory": True,
        }]
        assert _import_with_remap(db, "products", p2, bid, LOCAL_OWNER, existing, id_maps) == 0
        # The matched destination id is recorded so child FKs rewrite to it.
        assert id_maps["products"][555999] == dest_id
        # Still exactly one row despite the changed barcode.
        assert db.execute(
            text("SELECT COUNT(*) FROM products WHERE uid = :u AND business_id = :b"),
            {"u": UID, "b": bid},
        ).scalar() == 1
    finally:
        db.rollback()
        db.close()


def test_import_does_not_merge_different_uid_invoices_sharing_a_number():
    """(§9.3b backstop) Two DIFFERENT bills that independently minted the same
    invoice_id (e.g. local 'C1-0001' and cloud 'C1-0001') must NOT be merged on
    migrate — uid mismatch means different sales. Skipping the invoice_id natural
    key when a uid is present keeps both bills (no silent lost sale)."""
    owner = _signup("Invoice Clash Co")
    bid = owner["bid"]
    LOCAL_OWNER = 7651234
    uid_cloud = str(uuid.uuid4())
    uid_local = str(uuid.uuid4())
    db = SessionLocal()
    try:
        existing = set(inspect(db.bind).get_table_names())

        # Destination already has a cloud-origin bill numbered C1-0001 (uid_cloud).
        cloud_row = [{"id": 901001, "business_id": LOCAL_OWNER, "uid": uid_cloud,
                      "invoice_id": "C1-0001", "amount": 100.0}]
        assert _import_with_remap(db, "invoices", cloud_row, bid, LOCAL_OWNER, existing, {}) == 1

        # Now import a DIFFERENT bill that also got numbered C1-0001 (uid_local).
        local_row = [{"id": 901999, "business_id": LOCAL_OWNER, "uid": uid_local,
                      "invoice_id": "C1-0001", "amount": 250.0}]
        inserted = _import_with_remap(db, "invoices", local_row, bid, LOCAL_OWNER, existing, {})
        assert inserted == 1, "the different-uid bill must be INSERTED, not natural-merged away"

        # ── CONTRACT CHANGED (M-3 × §9.3b, Jul-2026) ─────────────────────────
        # This test previously asserted BOTH bills keep the number 'C1-0001'.
        # That is no longer permitted: invoices now carries a partial unique
        # index on (business_id, invoice_id), because a reused invoice number is
        # a Rule 46 breach and made two documents indistinguishable in the audit
        # trail.
        #
        # The original INTENT — never silently lose a sale — is unchanged and
        # still asserted below. What changed is how the clash is resolved: the
        # second bill is RENUMBERED into the next free slot in its series (the
        # same thing `create_sale_invoice(renumber_on_conflict=True)` does when
        # two counters clash), rather than being merged away or duplicating a
        # number. Both sales survive; neither number is shared.
        both = db.execute(
            text("SELECT uid, invoice_id FROM invoices "
                 "WHERE uid IN (:u1, :u2) AND business_id = :b"),
            {"u1": uid_cloud, "u2": uid_local, "b": bid},
        ).fetchall()
        assert len(both) == 2, "a sale was lost — the §9.3b guarantee still holds"
        assert {r[0] for r in both} == {uid_cloud, uid_local}

        numbers = {r[0]: r[1] for r in both}
        assert numbers[uid_cloud] == "C1-0001", "the first bill keeps its number"
        assert numbers[uid_local] != "C1-0001", "the clashing bill must be renumbered"
        assert str(numbers[uid_local]).startswith("C1-"), "renumbered within its own series"
    finally:
        db.rollback()
        db.close()
