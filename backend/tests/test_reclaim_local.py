"""
tests/test_reclaim_local.py
===========================
Signup self-heal: re-registering a username whose cloud account was deleted (so
the username is free on the cloud) but whose stale LOCAL mirror still exists must
RECLAIM the local row onto the new BizID instead of hard-400ing.

The test DB is sqlite → _DB_MODE == 'local', so the local-only reclaim endpoint
is active here.
"""
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app

client = TestClient(app)


def _signup(uname, public_id=None):
    body = {"username": uname, "password": "TestPass123!", "business_name": "Orphan Co"}
    if public_id:
        body["public_id"] = public_id
    return client.post("/signup", json=body)


def test_reclaim_rekeys_orphan_and_logs_in():
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = _signup(uname, public_id="BA-OLDID1")
    assert r.status_code == 200, r.text
    assert r.json()["public_id"] == "BA-OLDID1"

    # Re-register (as the frontend does after a fresh cloud signup mints a new
    # BizID): the local mirror still exists → reclaim onto the new BizID.
    rc = client.post("/api/auth/reclaim_local", json={
        "username": uname,
        "password": "NewPass456!",
        "public_id": "BA-NEWID2",
        "business_name": "Reborn Co",
    })
    assert rc.status_code == 200, rc.text
    body = rc.json()
    assert body["public_id"] == "BA-NEWID2"
    assert body["business_name"] == "Reborn Co"
    assert body.get("token")

    # The new password works; the old one no longer does.
    assert client.post("/login", json={"username": uname, "password": "NewPass456!"}).status_code == 200
    assert client.post("/login", json={"username": uname, "password": "TestPass123!"}).status_code == 401


def test_reclaim_rekey_purges_staff_and_data_and_writes_tombstone():
    """T1.3 (MASTER_REVIEW §9.A): delete-and-recreate lifecycle must leave a
    CLEAN business — re-key + 0 stale staff + 0 stale data + a tombstone row
    recording the retired BizID."""
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = _signup(uname, public_id="BA-T13-OLD")
    assert r.status_code == 200, r.text
    owner_tok = r.json()["token"]
    auth = {"Authorization": f"Bearer {owner_tok}"}

    # Seed a staff sub-account + a data row under the OLD identity.
    rs = client.post("/staff", json={
        "username": "counter_1", "password": "StaffPass123!", "role": "cashier",
    }, headers=auth)
    assert rs.status_code == 201, rs.text
    rp = client.post("/products", json={
        "name": "Stale Widget", "selling_price": 10.0,
    }, headers=auth)
    assert rp.status_code in (200, 201), rp.text

    # Cloud account deleted + re-registered → reclaim onto the NEW BizID.
    rc = client.post("/api/auth/reclaim_local", json={
        "username": uname,
        "password": "NewPass456!",
        "public_id": "BA-T13-NEW",
        "business_name": "Clean Slate Co",
    })
    assert rc.status_code == 200, rc.text
    assert rc.json()["public_id"] == "BA-T13-NEW"
    new_tok = rc.json()["token"]
    new_auth = {"Authorization": f"Bearer {new_tok}"}

    # Clean re-key: new password works, old refused.
    assert client.post("/login", json={"username": uname, "password": "NewPass456!"}).status_code == 200
    assert client.post("/login", json={"username": uname, "password": "TestPass123!"}).status_code == 401

    # 0 stale staff — the sub-account was purged with the old tenant.
    staff_list = client.get("/staff", headers=new_auth)
    assert staff_list.status_code == 200, staff_list.text
    assert staff_list.json() == []

    # 0 stale data — no product from the old identity survives.
    prods = client.get("/products", headers=new_auth)
    assert prods.status_code == 200, prods.text
    page = prods.json()
    assert page["total"] == 0, f"stale products survived the re-key: {page['items']}"

    # Tombstone row records the RETIRED BizID with reason 'reclaim_rekey'.
    from database.db import SessionLocal
    from database.models import DeletedBusiness
    s = SessionLocal()
    try:
        tomb = (s.query(DeletedBusiness)
                  .filter(DeletedBusiness.public_id == "BA-T13-OLD")
                  .order_by(DeletedBusiness.id.desc())
                  .first())
        assert tomb is not None, "expected a DeletedBusiness tombstone for the retired BizID"
        assert tomb.reason == "reclaim_rekey"
        assert tomb.username == uname
    finally:
        s.close()


def test_reclaim_requires_public_id_and_existing_account():
    # Missing public_id → 400.
    r = client.post("/api/auth/reclaim_local", json={
        "username": f"own_{uuid.uuid4().hex[:8]}", "password": "X1xxxxxx!", "public_id": "",
    })
    assert r.status_code == 400, r.text

    # No such local account → 404.
    r = client.post("/api/auth/reclaim_local", json={
        "username": f"nobody_{uuid.uuid4().hex[:8]}", "password": "X1xxxxxx!", "public_id": "BA-X",
    })
    assert r.status_code == 404, r.text
