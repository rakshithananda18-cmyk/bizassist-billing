"""
tests/test_godown_uid_resolution.py
===================================
`godown_id` named a DIFFERENT warehouse in the other database.

`_serialize_orm_obj` only emits a portable `*_uid` for DECLARED ForeignKeys, and
`resolve_parent_fk_uids` only inspects declared ones on the way back in. All six
godown columns were plain `Column(Integer)`, so neither side ever looked at
them: the LOCAL godown id was written straight through, unverified, onto a row
in a database that numbers its godowns independently.

`godowns` is synced AND carries a `uid`, so the machinery to do this correctly
already existed and was simply unwired. Declaring ForeignKey("godowns.id") turns
both halves on at once — which is what this test pins.
"""
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient      # noqa: E402
from sqlalchemy import text                     # noqa: E402
from main_groq import app                       # noqa: E402
from database.db import SessionLocal            # noqa: E402
from database.models import Inventory           # noqa: E402
from core.models import Godown                  # noqa: E402

client = TestClient(app)


def _hybrid_business():
    uname = f"gd_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Godown Co",
    })
    assert r.status_code == 200, r.text
    acct = r.json()
    bid = acct["user"]["id"] if isinstance(acct.get("user"), dict) else acct["id"]
    db = SessionLocal()
    try:
        db.execute(text("UPDATE users SET settings = :s WHERE id = :b"), {
            "s": json.dumps({"general": {"hosting_mode": "hybrid"}}), "b": bid,
        })
        db.commit()
    finally:
        db.close()
    return bid


def test_push_payload_carries_a_portable_godown_reference():
    bid = _hybrid_business()

    db = SessionLocal()
    try:
        g = Godown(business_id=bid, name="Main Warehouse")
        db.add(g)
        db.commit()
        db.refresh(g)
        local_godown_id, godown_uid = g.id, g.uid
        assert godown_uid, "godowns must carry a uid for this to be resolvable at all"

        db.execute(text("DELETE FROM sync_queue WHERE business_id = :b"), {"b": bid})
        db.commit()

        db.add(Inventory(business_id=bid, product_name="Widget", stock=3.0,
                         godown_id=local_godown_id))
        db.commit()

        row = db.execute(text(
            "SELECT payload FROM sync_queue WHERE business_id = :b AND entity = 'inventory' "
            "AND operation = 'INSERT' ORDER BY id DESC LIMIT 1"
        ), {"b": bid}).fetchone()
        assert row and row[0], "the inventory INSERT should have been queued"
        payload = json.loads(row[0])

        # The durable reference is what the receiver resolves against its OWN
        # godowns table. Without it the raw integer is all there is, and it
        # points at whichever warehouse happens to hold that id over there.
        assert payload.get("godown_uid") == godown_uid or \
               payload.get("godown_id_uid") == godown_uid, (
            "no portable godown reference in the payload — the receiver has "
            f"nothing but the local id {local_godown_id} to go on: {sorted(payload)}"
        )
    finally:
        db.close()


def test_receiver_rejects_a_godown_id_it_cannot_verify():
    """The other half of the same rule (M-9): an unverifiable FK is never
    written as-is. `inventory.godown_id` is nullable, so the row survives with
    the link dropped rather than being attached to an unrelated warehouse."""
    from database.sync_map import resolve_parent_fk_uids

    bid = _hybrid_business()
    db = SessionLocal()
    try:
        # A godown id that belongs to no one in this database.
        data = {"business_id": bid, "product_name": "Widget", "stock": 1.0,
                "godown_id": 999999}
        deferred = resolve_parent_fk_uids(db, Inventory, data, business_id=bid)

        assert not deferred, "a nullable FK must not strand the row"
        assert data["godown_id"] is None, (
            "an unverifiable godown id was written through — that is exactly the "
            "wrong-warehouse link this FK exists to prevent"
        )
    finally:
        db.close()
