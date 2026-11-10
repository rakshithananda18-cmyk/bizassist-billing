"""
tests/test_staff_lookup_and_mail.py
====================================
Tests for:
1. Business discovery & staff dropdown roster via POST /api/auth/lookup-business
2. Staff registration with phone numbers
3. Admin updating all business owner details (name, email, phone, address, gstin, pan, state_code, plan, hosting_mode)
4. Mail notifications for account detail changes and password updates
5. Mandatory email for account password updates
6. Collapsing Google verified email with account email
"""
import os
import sys
import uuid
import random
import pytest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from main_groq import app
from database.db import SessionLocal
from database.models import User
from services.auth import hash_password
from tests.signup_fixture import signup_payload

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_auth_services(monkeypatch):
    monkeypatch.setattr("routes.auth.check_ip_rate_limit", lambda *_: {"allowed": True})
    monkeypatch.setattr("services.brevo_service.is_brevo_configured", lambda: False)


def _signup_owner(username_prefix="own_lk", email_domain="example.com"):
    uname = f"{username_prefix}_{uuid.uuid4().hex[:6]}"
    phone = f"+9198765{random.randint(10000, 99999)}"
    email = f"{uname}@{email_domain}"
    r = client.post("/signup", json=signup_payload({
        "username": uname,
        "password": "Password123!",
        "business_name": f"{uname} Mart",
        "phone": phone,
        "email": email,
    }))
    assert r.status_code == 200, r.text
    data = r.json()
    headers = {"Authorization": f"Bearer {data['token']}"}
    return {
        "headers": headers,
        "id": data["id"],
        "username": uname,
        "phone": phone,
        "email": email,
        "public_id": data["public_id"],
        "business_name": f"{uname} Mart",
    }


def test_business_lookup_and_staff_roster():
    owner = _signup_owner("roster_owner")
    
    # 1. Lookup when no staff exist
    r_empty = client.post("/api/auth/lookup-business", json={"identifier": owner["username"]})
    assert r_empty.status_code == 200
    res = r_empty.json()
    assert res["found"] is True
    assert res["business_name"] == owner["business_name"]
    assert res["public_id"] == owner["public_id"]
    assert res["has_staff"] is False
    assert len(res["staff"]) == 0

    # 2. Create staff members with phone numbers
    r_staff1 = client.post("/staff", headers=owner["headers"], json={
        "username": "cashier_alice",
        "password": "Password123!",
        "phone": "9876543211",
        "role": "cashier",
        "counter_prefix": "A"
    })
    assert r_staff1.status_code == 201, r_staff1.text
    assert r_staff1.json()["phone"] == "+919876543211"

    r_staff2 = client.post("/staff", headers=owner["headers"], json={
        "username": "cashier_bob",
        "password": "Password123!",
        "phone": "9876543212",
        "role": "cashier",
        "counter_prefix": "B"
    })
    assert r_staff2.status_code == 201, r_staff2.text

    # 3. Lookup by owner's email
    r_by_email = client.post("/api/auth/lookup-business", json={"identifier": owner["email"]})
    assert r_by_email.status_code == 200
    data_email = r_by_email.json()
    assert data_email["found"] is True
    assert data_email["has_staff"] is True
    assert len(data_email["staff"]) == 2
    staff_names = [s["username"] for s in data_email["staff"]]
    assert "cashier_alice" in staff_names
    assert "cashier_bob" in staff_names

    # 4. Lookup by owner's BizID
    r_by_bizid = client.post("/api/auth/lookup-business", json={"identifier": owner["public_id"]})
    assert r_by_bizid.status_code == 200
    assert r_by_bizid.json()["found"] is True

    # 5. Lookup by owner's phone
    r_by_phone = client.post("/api/auth/lookup-business", json={"identifier": owner["phone"]})
    assert r_by_phone.status_code == 200
    assert r_by_phone.json()["found"] is True

    # 6. Lookup non-existent
    r_none = client.post("/api/auth/lookup-business", json={"identifier": "nonexistent_store_99999"})
    assert r_none.status_code == 200
    assert r_none.json()["found"] is False


def test_mail_notification_on_profile_update():
    owner = _signup_owner("mail_owner")

    with patch("services.brevo_service.send_account_update_email") as mock_mail:
        r = client.put("/profile", headers=owner["headers"], json={
            "business_name": "Updated Super Mart",
            "gstin": "29ABCDE1234F1Z5",
            "phone": "9123456789",
            "address": "123 Market Street, Bangalore",
            "state_code": "29",
            "pan": "ABCDE1234F"
        })
        assert r.status_code == 200, r.text
        assert mock_mail.called
        args, _ = mock_mail.call_args
        assert args[0] == owner["email"]
        assert "Business name updated" in args[2]
        assert any("GSTIN" in str(c) for c in args[2])


def test_mandatory_email_for_password_change():
    uname = f"noemail_{uuid.uuid4().hex[:6]}"
    phone = f"+9198888{random.randint(10000, 99999)}"
    with SessionLocal() as db:
        u = User(
            username=uname,
            password="InitialPass123!",
            business_name=f"{uname} Shop",
            phone=phone,
            email=None,  # No email
            role="enterprise",
            public_id=f"BA-{uuid.uuid4().hex[:6].upper()}"
        )
        db.add(u)
        db.commit()

    # Requesting password reset OTP without email must fail
    r_otp = client.post("/api/auth/forgot-password/request-otp", json={"identifier": uname})
    assert r_otp.status_code == 400
    assert "email address is mandatory" in r_otp.text.lower()


def test_admin_update_all_merchant_details():
    owner = _signup_owner("admin_edit_owner")
    
    # Create admin user
    admin_uname = f"admin_{uuid.uuid4().hex[:6]}"
    with SessionLocal() as db:
        admin_user = User(
            username=admin_uname,
            password=hash_password("AdminPass123!"),
            role="admin",
            business_name="Platform Admin",
            public_id=f"BA-ADM{uuid.uuid4().hex[:4].upper()}"
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        admin_id = admin_user.id

    r_login = client.post("/login", json={"username": admin_uname, "password": "AdminPass123!"})
    assert r_login.status_code == 200
    admin_headers = {"Authorization": f"Bearer {r_login.json()['token']}"}

    # Admin updates all owner details
    with patch("services.brevo_service.send_account_update_email") as mock_mail:
        r_update = client.put(f"/admin/update-user/{owner['id']}", headers=admin_headers, json={
            "business_name": "Admin Renovated Store",
            "email": "renovated@business.com",
            "phone": "9999888877",
            "address": "77 Commercial Street",
            "gstin": "33AAAAA0000A1Z5",
            "state_code": "33",
            "pan": "AAAAA0000A",
            "upi_vpa": "renovated@okaxis",
            "plan": "pro",
            "hosting_mode": "cloud",
        })
        assert r_update.status_code == 200, r_update.text
        assert mock_mail.called

    # Verify DB has updated details
    with SessionLocal() as db:
        updated_owner = db.get(User, owner["id"])
        assert updated_owner.business_name == "Admin Renovated Store"
        assert updated_owner.email == "renovated@business.com"
        assert updated_owner.phone == "+919999888877"
        assert updated_owner.address == "77 Commercial Street"
        assert updated_owner.gstin == "33AAAAA0000A1Z5"
        assert updated_owner.pan == "AAAAA0000A"
        assert updated_owner.upi_vpa == "renovated@okaxis"


def test_google_verify_email_collapse():
    owner = _signup_owner("google_collapse", email_domain="gmail.com")
    
    # Mock verify google credential returning a google account with the same email
    fake_google_data = {
        "sub": "google_sub_123456",
        "email": owner["email"],
        "name": "Google Merchant",
        "picture": "https://example.com/pic.jpg",
    }
    with patch("routes.auth._verify_google_credential", return_value=fake_google_data):
        r = client.post("/api/auth/google/verify", json={"credential": "mock_id_token"})
        assert r.status_code == 200
        data = r.json()
        assert data["action"] == "login"
        assert data["username"] == owner["username"]

    # Verify google_id is linked to the existing user
    with SessionLocal() as db:
        refreshed = db.get(User, owner["id"])
        assert refreshed.google_id == "google_sub_123456"
        assert refreshed.email == owner["email"]
