"""
tests/test_desktop_recovery_checks_cloud.py — desktop recovery needs the cloud's word
======================================================================================
Two loopback-only routes act on the claim "the cloud just accepted these
credentials":

  * POST /api/auth/reconcile_password — sets the local owner's password,
  * POST /api/auth/reclaim_local      — refuses legacy identity replacement.

They used to take that claim from the request. On a shared shop computer that
meant anyone who knew the owner's username — every cashier does, staff sign in
with it — and the BizID shown on screen could reset the owner's password, or
wipe the business, with a plain POST. Password reconciliation now confirms the
same cloud identity; legacy reclaim always refuses without network access or
local changes, even when a different cloud account accepts the password.
"""
import os
import sys
import uuid
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import routes.auth as auth_routes
from main_groq import app

from tests.signup_fixture import signup_payload

client = TestClient(app)
OLD_PW, NEW_PW = "TestPass123!", "NewPass456!"


@pytest.fixture(autouse=True)
def clear_rate_limit_windows():
    from services.rate_limiter import _ip_window, _upload_window
    _ip_window.clear()
    _upload_window.clear()


def _owner_with_product(public_id):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json=signup_payload({"username": uname, "password": OLD_PW,
                                     "business_name": "Sri Lakshmi Medicals", "public_id": public_id}))
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.post("/products", headers=h, json={"name": "Paracetamol 500", "selling_price": 20.0}).status_code in (200, 201)
    return uname


def _cloud(answer):
    """Stand-in for _confirm_with_cloud: a dict (accepted) or an HTTPException."""
    def confirm(username, password):
        if isinstance(answer, HTTPException):
            raise answer
        return {"role": "enterprise", **answer}
    return confirm


def _login(uname, pw):
    return client.post("/login", json={"username": uname, "password": pw}).status_code


def _products_left(uname):
    r = client.post("/login", json={"username": uname, "password": OLD_PW})
    if r.status_code != 200:
        r = client.post("/login", json={"username": uname, "password": NEW_PW})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    return client.get("/products", headers=h).json()["total"]


# ── the cloud check itself ──────────────────────────────────────────────────

class TestConfirmWithCloud:

    def test_signs_in_to_the_cloud_with_the_typed_credentials(self):
        with patch("httpx.post", return_value=MagicMock(status_code=200, json=lambda: {"public_id": "BA-CLOUD1"})) as post:
            assert auth_routes._confirm_with_cloud("ravi", NEW_PW) == {"public_id": "BA-CLOUD1"}
        url = post.call_args.args[0]
        assert url.endswith("/login")
        assert post.call_args.kwargs["json"] == {"username": "ravi", "password": NEW_PW}

    def test_a_refusal_is_401_and_an_outage_is_503(self):
        with patch("httpx.post", return_value=MagicMock(status_code=401)):
            with pytest.raises(HTTPException) as e:
                auth_routes._confirm_with_cloud("ravi", "guess")
        assert e.value.status_code == 401
        with patch("httpx.post", side_effect=OSError("offline")):
            with pytest.raises(HTTPException) as e:
                auth_routes._confirm_with_cloud("ravi", NEW_PW)
        assert e.value.status_code == 503


# ── reconcile_password ──────────────────────────────────────────────────────

class TestReconcilePassword:

    def _post(self, uname, public_id):
        return client.post("/api/auth/reconcile_password",
                           json={"username": uname, "password": NEW_PW, "public_id": public_id})

    def test_the_attack_a_cashier_could_run_is_refused(self, monkeypatch):
        """Right username and BizID, but the cloud does not know this password."""
        uname = _owner_with_product("BA-RCN-A1")
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud",
                            _cloud(HTTPException(status_code=401, detail="no")))
        assert self._post(uname, "BA-RCN-A1").status_code == 401
        assert _login(uname, OLD_PW) == 200 and _login(uname, NEW_PW) == 401

    def test_the_cloud_offline_changes_nothing(self, monkeypatch):
        uname = _owner_with_product("BA-RCN-B1")
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud",
                            _cloud(HTTPException(status_code=503, detail="offline")))
        assert self._post(uname, "BA-RCN-B1").status_code == 503
        assert _login(uname, OLD_PW) == 200

    def test_cloud_staff_cannot_set_the_local_owner_password(self, monkeypatch):
        uname = _owner_with_product("BA-RCN-STAFF")
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud", _cloud({"public_id": "BA-RCN-STAFF", "role": "cashier"}))
        assert self._post(uname, "BA-RCN-STAFF").status_code == 403
        assert _login(uname, OLD_PW) == 200

    def test_the_cloud_bizid_decides_not_the_request(self, monkeypatch):
        """The request claims the local BizID, but the cloud account is another."""
        uname = _owner_with_product("BA-RCN-C1")
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud", _cloud({"public_id": "BA-SOMEONE-ELSE"}))
        r = self._post(uname, "BA-RCN-C1")
        assert r.status_code == 409 and "Identity mismatch" in r.json()["detail"]
        assert _login(uname, OLD_PW) == 200

    def test_a_password_changed_online_is_taken_on(self, monkeypatch):
        uname = _owner_with_product("BA-RCN-D1")
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud", _cloud({"public_id": "BA-RCN-D1"}))
        assert self._post(uname, "BA-RCN-D1").status_code == 200
        assert _login(uname, NEW_PW) == 200 and _login(uname, OLD_PW) == 401
        assert _products_left(uname) == 1, "a password reconcile never touches data"


# ── reclaim_local ───────────────────────────────────────────────────────────

class TestReclaimLocal:

    def _post(self, uname, public_id):
        return client.post("/api/auth/reclaim_local",
                           json={"username": uname, "password": NEW_PW, "public_id": public_id})

    def _existing_business(self, public_id):
        """Seed all data formerly purged by the unsafe replacement path."""
        from database.db import SessionLocal
        from database.models import Customer, User
        uname = _owner_with_product(public_id)
        with SessionLocal() as db:
            owner = db.query(User).filter(User.username == uname).one()
            db.add(User(username=f"counter_{uuid.uuid4().hex[:8]}", password=owner.password,
                        role="cashier", parent_business_id=owner.id, business_name=owner.business_name))
            db.add(Customer(business_id=owner.id, uid=f"customer-{uuid.uuid4().hex}",
                            name="Original local customer", phone="12345"))
            db.commit()
        return uname

    def _state(self, uname):
        from database.db import SessionLocal
        from database.models import Customer, DeletedBusiness, Product, User
        with SessionLocal() as db:
            owner_id = db.query(User.id).filter(User.username == uname).scalar()
            def values(model, condition):
                return [{column.name: getattr(row, column.name) for column in model.__table__.columns}
                        for row in db.query(model).filter(condition).order_by(model.id)]
            return {
                "users": values(User, (User.id == owner_id) | (User.parent_business_id == owner_id)),
                "customers": values(Customer, Customer.business_id == owner_id),
                "products": values(Product, Product.business_id == owner_id),
                "tombstones": values(DeletedBusiness, DeletedBusiness.username == uname),
            }

    def test_without_the_cloud_password_nothing_is_wiped(self, monkeypatch):
        uname = self._existing_business("BA-RCL-A1")
        before = self._state(uname)
        confirm = Mock(side_effect=HTTPException(status_code=401, detail="no"))
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud", confirm)
        assert self._post(uname, "BA-ATTACKER").status_code == 409
        confirm.assert_not_called()
        assert self._state(uname) == before
        assert _login(uname, OLD_PW) == 200
        assert _products_left(uname) == 1, "the business's data must survive a refused reclaim"

    def test_a_bizid_the_cloud_does_not_name_is_refused(self, monkeypatch):
        uname = self._existing_business("BA-RCL-B1")
        before = self._state(uname)
        confirm = Mock(return_value={"public_id": "BA-RCL-B2"})
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud", confirm)
        assert self._post(uname, "BA-ATTACKER").status_code == 409
        confirm.assert_not_called()
        assert self._state(uname) == before
        assert _login(uname, OLD_PW) == 200
        assert _products_left(uname) == 1

    def test_valid_new_cloud_identity_still_cannot_replace_local_business(self, monkeypatch):
        uname = self._existing_business("BA-RCL-C1")
        before = self._state(uname)
        confirm = Mock(return_value={"public_id": "BA-RCL-C2", "business_name": "Sri Lakshmi Pharma"})
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud", confirm)
        r = self._post(uname, "BA-RCL-C2")
        assert r.status_code == 409, r.text
        confirm.assert_not_called()
        assert self._state(uname) == before
        assert _login(uname, OLD_PW) == 200 and _login(uname, NEW_PW) == 401
        assert _products_left(uname) == 1
