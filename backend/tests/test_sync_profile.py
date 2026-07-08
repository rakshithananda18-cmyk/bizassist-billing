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

client = TestClient(app)

def _signup(business_name):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": business_name,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return {
        "headers": {"Authorization": f"Bearer {b['token']}"},
        "bid": b["id"],
        "username": uname,
        "token": b["token"]
    }


def test_sync_profile_push_success():
    # 1. Signup a test business owner
    user = _signup("Original Shop Name")

    payload = {
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
    # 1. Create a cashier token
    token = create_access_token({
        "id": 999,  # Non-existent owner id
        "user_id": 999,
        "username": "cashier_1",
        "public_id": "BA-UNKNOWN",
        "role": "cashier"  # Gated by restrict_cashier/get_active_user check
    })
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post("/api/sync/profile-push", json={"business_name": "Hack"}, headers=headers)
    # The route resolves the owner id 999 from cloud DB; since it's not found:
    assert resp.status_code == 403


@patch("httpx.post")
@patch("services.sync_worker._get_cloud_token")
def test_immediate_sync_helper_push(mock_get_token, mock_post):
    mock_get_token.return_value = "mocked-token-123"
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"status": "ok", "updated_fields": ["business_name"]})

    with patch("services.immediate_sync._IS_LOCAL", True):
        from services.immediate_sync import push_profile_to_cloud
        import time

        push_profile_to_cloud(10, {"business_name": "Test Push Shop"})
        time.sleep(0.1)
        
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "/api/sync/profile-push" in args[0]
        assert kwargs["json"] == {"business_name": "Test Push Shop"}
        assert kwargs["headers"]["Authorization"] == "Bearer mocked-token-123"
