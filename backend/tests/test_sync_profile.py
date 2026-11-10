"""
test_sync_profile.py
=====================
Unit tests for the immediate profile sync endpoint and helper:
  - POST /api/sync/profile-push
  - services.immediate_sync.push_profile_to_cloud
"""
import uuid
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from database.db import SessionLocal
from database.models import User
from routes.auth import create_access_token
from main_groq import app

from tests.signup_fixture import signup_payload

client = TestClient(app)

def _signup(business_name):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json=signup_payload({
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    }))
    assert r.status_code == 200, r.text
    b = r.json()
    return {
        "headers": {"Authorization": f"Bearer {b['token']}"},
        "bid": b["id"],
        "public_id": b["public_id"],
        "username": uname,
        "token": b["token"]
    }


def _envelope(user):
    return {"event_id": uuid.uuid4().hex, "source_id": "profile-test-" + uuid.uuid4().hex,
            "source_revision": 1, "business_public_id": user["public_id"]}


def test_sync_profile_push_success():
    # 1. Signup a test business owner
    user = _signup("Original Shop Name")

    payload = {
        **_envelope(user),
        "business_name": "Updated Shop Name",
        "gstin": "29AAAAA1111A1Z1",
        "phone": "9876543210",
        "email": "owner@shop.com",
        "address": "123 Main Street",
        "state_code": "29",
        "pan": "ABCDE1234F",
        "logo": "data:image/png;base64,...",
        "upi_vpa": "owner@upi"
    }

    # 2. Push profile updates to the sync endpoint
    resp = client.post("/api/sync/profile-push", json=payload, headers=user["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "business_name" in data["updated_fields"]
    assert "logo" in data["updated_fields"]

    # 3. Verify changes in local/test DB
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.id == user["bid"]).first()
        assert owner.business_name == "Updated Shop Name"
        assert owner.gstin == "29AAAAA1111A1Z1"
        assert owner.phone == "9876543210"
        assert owner.email == "owner@shop.com"
        assert owner.address == "123 Main Street"
        assert owner.state_code == "29"
        assert owner.pan == "ABCDE1234F"
        assert owner.logo == "data:image/png;base64,..."
        assert owner.upi_vpa == "owner@upi"
    finally:
        db.close()


def test_sync_profile_push_patch_semantics():
    user = _signup("Original Shop Name")

    payload = {
        **_envelope(user),
        "gstin": "29BBBBB2222B2Z2",
        "address": "456 Side Street"
    }

    resp = client.post("/api/sync/profile-push", json=payload, headers=user["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert set(data["updated_fields"]) == {"gstin", "address"}

    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.id == user["bid"]).first()
        assert owner.business_name == "Original Shop Name"  # Unchanged
        assert owner.gstin == "29BBBBB2222B2Z2"             # Updated
        assert owner.address == "456 Side Street"            # Updated
    finally:
        db.close()


def test_sync_profile_push_non_owner_forbidden():
    # A real cashier of a real business is signed in, but is not the owner.
    owner = _signup("Profile Guard Shop")
    cashier = f"own_{uuid.uuid4().hex[:8]}"
    phone = f"+919{str(uuid.uuid4().int % 1_000_000_000).zfill(9)}"
    r = client.post("/staff", headers=owner["headers"],
                    json={"username": cashier, "password": "Password123!", "role": "cashier", "phone": phone})
    assert r.status_code == 201, r.text
    login = client.post("/login", json={"username": cashier, "password": "Password123!"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}

    resp = client.post("/api/sync/profile-push", json={"business_name": "Hack"}, headers=headers)
    assert resp.status_code == 403


def test_sync_profile_push_unknown_user_is_not_signed_in():
    # A token for a user that does not exist is rejected before any owner
    # check: get_active_user fails closed on a missing subject.
    token = create_access_token({
        "id": 999, "user_id": 999, "username": "cashier_1",
        "public_id": "BA-UNKNOWN", "role": "cashier",
    })
    resp = client.post("/api/sync/profile-push", json={"business_name": "Hack"},
                       headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


@pytest.mark.parametrize("endpoint,payload", [
    ("profile-push", {"business_name": "Legacy must not apply"}),
    ("staff-push", {"staff": []}),
])
def test_legacy_owner_control_peer_requires_upgrade(endpoint, payload):
    user = _signup("Legacy control peer")
    response = client.post("/api/sync/" + endpoint, json=payload, headers=user["headers"])
    assert response.status_code == 426
    with SessionLocal() as db:
        assert db.get(User, user["bid"]).business_name == "Legacy control peer"


@patch("httpx.post")
@patch("services.sync_worker._get_cloud_token")
def test_immediate_sync_helper_push(mock_get_token, mock_post):
    user = _signup("Durable profile helper")
    mock_get_token.return_value = "mocked-token-123"
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"status": "ok", "updated_fields": ["business_name"]})

    with patch("services.immediate_sync._IS_LOCAL", True), \
         patch("services.immediate_sync.syncs_to_cloud", return_value=True), \
         patch("services.control_outbox.trigger_control_flush"):
        from services.immediate_sync import push_profile_to_cloud
        push_profile_to_cloud(user["bid"], {"business_name": "Test Push Shop"})
    # Drive the durable worker synchronously: no timing-sensitive daemon sleep.
    with patch("services.control_outbox._IS_LOCAL", True), \
         patch("services.control_outbox.is_hybrid_cloud", return_value=True), SessionLocal() as db:
        from services.control_outbox import flush_control_outbox
        assert flush_control_outbox(db, user["bid"])["completed"] == 1
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "/api/sync/profile-push" in args[0]
        sent = kwargs["json"]
        assert sent["business_name"] == "Test Push Shop"
        assert sent["business_public_id"] == user["public_id"]
        assert sent["event_id"] and sent["source_id"] and sent["source_revision"] == 1
        assert kwargs["headers"]["Authorization"] == "Bearer mocked-token-123"
