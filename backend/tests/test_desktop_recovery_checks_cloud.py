"""
tests/test_desktop_recovery_checks_cloud.py — desktop recovery needs the cloud's word
======================================================================================
Two loopback-only routes act on the claim "the cloud just accepted these
credentials":

  * POST /api/auth/reconcile_password — sets the local owner's password,
  * POST /api/auth/reclaim_local      — re-keys the owner onto a new BizID and
                                        PURGES the business's local data.

They used to take that claim from the request. On a shared shop computer that
meant anyone who knew the owner's username — every cashier does, staff sign in
with it — and the BizID shown on screen could reset the owner's password, or
wipe the business, with a plain POST. Now the backend signs in to the cloud
itself (routes.auth._confirm_with_cloud) and nothing changes unless the cloud
accepts the password and names the same BizID.
"""
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

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
        return answer
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

    def test_without_the_cloud_password_nothing_is_wiped(self, monkeypatch):
        uname = _owner_with_product("BA-RCL-A1")
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud",
                            _cloud(HTTPException(status_code=401, detail="no")))
        assert self._post(uname, "BA-ATTACKER").status_code == 401
        assert _login(uname, OLD_PW) == 200
        assert _products_left(uname) == 1, "the business's data must survive a refused reclaim"

    def test_a_bizid_the_cloud_does_not_name_is_refused(self, monkeypatch):
        """Even with the real cloud password, the BizID adopted must be the
        cloud account's, so a reclaim can't point the business elsewhere."""
        uname = _owner_with_product("BA-RCL-B1")
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud", _cloud({"public_id": "BA-RCL-B2"}))
        assert self._post(uname, "BA-ATTACKER").status_code == 409
        assert _login(uname, OLD_PW) == 200
        assert _products_left(uname) == 1

    def test_a_real_re_registration_still_reclaims(self, monkeypatch):
        uname = _owner_with_product("BA-RCL-C1")
        monkeypatch.setattr(auth_routes, "_confirm_with_cloud",
                            _cloud({"public_id": "BA-RCL-C2", "business_name": "Sri Lakshmi Pharma"}))
        r = self._post(uname, "BA-RCL-C2")
        assert r.status_code == 200, r.text
        assert r.json()["public_id"] == "BA-RCL-C2"
        assert r.json()["business_name"] == "Sri Lakshmi Pharma", "the cloud's name, not the request's"
        assert _products_left(uname) == 0, "a re-keyed business starts clean"
