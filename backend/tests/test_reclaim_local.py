"""
tests/test_reclaim_local.py
===========================
A new cloud identity cannot authorize replacing an existing local business.
The legacy endpoint refuses the request and retains all original local data.
"""
import os
import sys
import uuid
from unittest.mock import Mock

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app

from tests.signup_fixture import signup_payload

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limit_windows():
    """Reset the IP sliding window before every test so login calls never
    accumulate across tests and trigger the 10/min brute-force guard."""
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _cloud_accepts(monkeypatch, public_id, business_name):
    """Even valid proof of a NEW cloud account cannot authorize replacement."""
    import routes.auth as auth_routes
    confirm = Mock(return_value={"public_id": public_id, "business_name": business_name})
    monkeypatch.setattr(auth_routes, "_confirm_with_cloud", confirm)
    return confirm


def _signup(uname, public_id=None):
    body = {"username": uname, "password": "TestPass123!", "business_name": "Orphan Co"}
    if public_id:
        body["public_id"] = public_id
    return client.post("/signup", json=signup_payload(body))


def test_new_cloud_identity_cannot_rekey_existing_owner(monkeypatch):
    confirm = _cloud_accepts(monkeypatch, "BA-NEWID2", "Reborn Co")
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = _signup(uname, public_id="BA-OLDID1")
    assert r.status_code == 200, r.text
    assert r.json()["public_id"] == "BA-OLDID1"

    # Knowing the username and owning a different cloud account does not grant
    # authority over this device's existing business.
    rc = client.post("/api/auth/reclaim_local", json={
        "username": uname,
        "password": "NewPass456!",
        "public_id": "BA-NEWID2",
        "business_name": "Reborn Co",
    })
    assert rc.status_code == 409, rc.text
    assert "all local records were kept" in rc.json()["detail"]
    confirm.assert_not_called()
    original = client.post("/login", json={"username": uname, "password": "TestPass123!"})
    assert original.status_code == 200
    assert original.json()["public_id"] == "BA-OLDID1"
    assert original.json()["business_name"] == "Orphan Co"
    assert client.post("/login", json={"username": uname, "password": "NewPass456!"}).status_code == 401


def test_refused_reclaim_preserves_owner_staff_customers_products_and_identity(monkeypatch):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = _signup(uname, public_id="BA-T13-OLD")
    assert r.status_code == 200, r.text
    owner_tok = r.json()["token"]
    auth = {"Authorization": f"Bearer {owner_tok}"}

    # Seed a staff sub-account + a data row under the OLD identity.
    phone = f"+919{str(uuid.uuid4().int % 1_000_000_000).zfill(9)}"
    rs = client.post("/staff", json={
        "username": "counter_1", "password": "StaffPass123!", "role": "cashier", "phone": phone,
    }, headers=auth)
    assert rs.status_code == 201, rs.text
    rp = client.post("/products", json={
        "name": "Stale Widget", "selling_price": 10.0,
    }, headers=auth)
    assert rp.status_code in (200, 201), rp.text

    from database.db import SessionLocal
    from database.models import Customer, DeletedBusiness, Product, User
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.username == uname).one()
        owner_id = owner.id
        customer = Customer(business_id=owner_id, uid="reclaim-original-customer", name="Original customer", phone="12345")
        db.add(customer)
        db.commit()
        def original_rows():
            def values(query):
                return [{column.name: getattr(row, column.name) for column in row.__table__.columns}
                        for row in query.order_by(query.column_descriptions[0]["entity"].id)]
            return {
                "users": values(db.query(User).filter((User.id == owner_id) | (User.parent_business_id == owner_id))),
                "customers": values(db.query(Customer).filter(Customer.business_id == owner_id)),
                "products": values(db.query(Product).filter(Product.business_id == owner_id)),
                "tombstones": values(db.query(DeletedBusiness).filter(DeletedBusiness.public_id.in_(["BA-T13-OLD", "BA-T13-NEW"]))),
            }
        before = original_rows()
    finally:
        db.close()

    confirm = _cloud_accepts(monkeypatch, "BA-T13-NEW", "Clean Slate Co")
    rc = client.post("/api/auth/reclaim_local", json={
        "username": uname,
        "password": "NewPass456!",
        "public_id": "BA-T13-NEW",
        "business_name": "Clean Slate Co",
    })
    assert rc.status_code == 409, rc.text
    confirm.assert_not_called()
    # Check every persisted column before login can legitimately rotate session
    # fields. Neither credentials nor business/staff records may change.
    db = SessionLocal()
    try:
        assert original_rows() == before
    finally:
        db.close()
    login = client.post("/login", json={"username": uname, "password": "TestPass123!"})
    assert login.status_code == 200
    assert client.post("/login", json={"username": uname, "password": "NewPass456!"}).status_code == 401
    preserved_auth = {"Authorization": f"Bearer {login.json()['token']}"}

    staff_list = client.get("/staff", headers=preserved_auth)
    assert staff_list.status_code == 200, staff_list.text
    assert len(staff_list.json()) == 1

    prods = client.get("/products", headers=preserved_auth)
    assert prods.status_code == 200, prods.text
    page = prods.json()
    assert page["total"] == 1
    assert page["items"][0]["name"] == "Stale Widget"


def test_legacy_reclaim_requests_always_receive_the_compatibility_refusal(monkeypatch):
    confirm = _cloud_accepts(monkeypatch, "BA-X", "Unrelated cloud business")
    r = client.post("/api/auth/reclaim_local", json={
        "username": f"own_{uuid.uuid4().hex[:8]}", "password": "X1xxxxxx!", "public_id": "",
    })
    assert r.status_code == 409, r.text

    r = client.post("/api/auth/reclaim_local", json={
        "username": f"nobody_{uuid.uuid4().hex[:8]}", "password": "X1xxxxxx!", "public_id": "BA-X",
    })
    assert r.status_code == 409, r.text
    confirm.assert_not_called()
