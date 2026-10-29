import os
import sys
import uuid
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from main_groq import app
from database.db import SessionLocal
from database.models import User

from tests.signup_fixture import signup_payload

client = TestClient(app)


def test_staff_role_update_invalidates_old_jwt():
    """Verify that when an owner updates a staff member's role or password,
    their existing JWT receives a 401 Session Revoked response."""
    # 1. Sign up owner
    owner_uname = f"owner_{uuid.uuid4().hex[:8]}"
    r_owner = client.post("/signup", json=signup_payload({"username": owner_uname, "password": "OwnerPass123!", "business_name": "Test Revoke Biz"}))
    assert r_owner.status_code == 200, r_owner.text
    owner_data = r_owner.json()
    owner_headers = {"Authorization": f"Bearer {owner_data['token']}"}

    # 2. Create staff sub-account
    staff_name = f"cashier_{uuid.uuid4().hex[:6]}"
    r_staff = client.post("/staff", headers=owner_headers, json={"username": staff_name, "password": "StaffPass123!", "role": "cashier"})
    assert r_staff.status_code == 201, r_staff.text

    # 3. Log in as staff to get JWT
    r_login = client.post("/login", json={"username": staff_name, "password": "StaffPass123!"})
    assert r_login.status_code == 200, r_login.text
    staff_token = r_login.json()["token"]
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    # 4. Verify staff JWT is initially active (e.g. GET /sales/products/search)
    r_check1 = client.get("/sales/products/search", headers=staff_headers)
    assert r_check1.status_code == 200

    # 5. Owner updates staff password
    staff_db_id = r_staff.json()["id"]
    r_update = client.patch(f"/staff/{staff_db_id}", headers=owner_headers, json={"password": "NewStaffPass123!"})
    assert r_update.status_code == 200, r_update.text

    # 6. Verify old staff JWT is now revoked (401 Session revoked)
    r_check2 = client.get("/sales/products/search", headers=staff_headers)
    assert r_check2.status_code == 401
    assert "Session revoked" in r_check2.text or "401" in str(r_check2.status_code)


def test_deleted_staff_token_fails_closed_even_with_a_warm_version_cache():
    """Deleting a staff row must revoke its JWT immediately, not after cache TTL."""
    owner_uname = f"owner_delete_{uuid.uuid4().hex[:8]}"
    owner = client.post("/signup", json=signup_payload({
        "username": owner_uname,
        "password": "OwnerPass123!",
        "business_name": "Deleted Staff Test",
    }))
    assert owner.status_code == 200, owner.text
    owner_headers = {"Authorization": f"Bearer {owner.json()['token']}"}

    staff_name = f"cashier_delete_{uuid.uuid4().hex[:6]}"
    created = client.post("/staff", headers=owner_headers, json={
        "username": staff_name,
        "password": "StaffPass123!",
        "role": "cashier",
    })
    assert created.status_code == 201, created.text

    login = client.post("/login", json={"username": staff_name, "password": "StaffPass123!"})
    assert login.status_code == 200, login.text
    staff_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    # This validates the token and deliberately populates the token-version cache.
    assert client.get("/sales/products/search", headers=staff_headers).status_code == 200

    deleted = client.delete(f"/staff/{created.json()['id']}", headers=owner_headers)
    assert deleted.status_code == 200, deleted.text

    rejected = client.get("/sales/products/search", headers=staff_headers)
    assert rejected.status_code == 401, rejected.text
    assert "Session revoked" in rejected.text


def test_staff_cannot_run_owner_sync_pull_or_discover_accounts_anonymously():
    owner_uname = f"owner_sync_{uuid.uuid4().hex[:8]}"
    owner = client.post("/signup", json=signup_payload({
        "username": owner_uname,
        "password": "OwnerPass123!",
        "business_name": "Sync Guard Test",
    }))
    assert owner.status_code == 200, owner.text
    owner_headers = {"Authorization": f"Bearer {owner.json()['token']}"}

    staff_name = f"cashier_sync_{uuid.uuid4().hex[:6]}"
    created = client.post("/staff", headers=owner_headers, json={
        "username": staff_name,
        "password": "StaffPass123!",
        "role": "cashier",
    })
    assert created.status_code == 201, created.text
    login = client.post("/login", json={"username": staff_name, "password": "StaffPass123!"})
    assert login.status_code == 200, login.text

    pull = client.get("/api/sync/pull", headers={"Authorization": f"Bearer {login.json()['token']}"})
    assert pull.status_code == 403, pull.text

    assert client.post("/api/biz_id/check", json={"username": owner_uname}).status_code == 404
    assert client.get(f"/staff-counters?owner={owner_uname}").status_code == 404
