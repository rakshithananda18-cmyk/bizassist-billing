"""backend/tests/test_auth_enhancements.py
======================================
Tests for:
1. Multi-identifier login (Username, Email, Phone)
2. Real-time username check endpoint (/api/auth/check-username)
3. Forgot Password OTP generation, Brevo dispatch, verification and session reset
4. Google OAuth verification and onboarding
"""
import os
import uuid
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

os.environ["JWT_SECRET"] = "test_secret_key_with_at_least_32_characters_long_12345"
os.environ["ALLOW_TEST_USERS"] = "1"

from main_groq import app
from database.db import get_db, SessionLocal
from database.models import User, PasswordResetOTP
from services.auth import hash_password, verify_password
from services.registration_policy import normalize_phone

client = TestClient(app)


@pytest.fixture(autouse=True)
def bypass_rate_limits():
    with patch("services.rate_limiter.check_ip_rate_limit", return_value={"allowed": True}), \
         patch("routes.auth.check_ip_rate_limit", return_value={"allowed": True}):
        yield


def create_sample_user(username=None, phone=None, email=None):
    db = SessionLocal()
    try:
        uid = uuid.uuid4().hex[:8]
        u_name = username or f"merchant_{uid}"
        u_phone = phone or ("9" + str(uuid.uuid4().int % 1000000000).zfill(9))
        u_email = email or f"merchant_{uid}@example.com"
        u = User(
            username=u_name,
            password=hash_password("ValidPassword123"),
            business_name=f"Test Store {uid}",
            role="enterprise",
            public_id=f"BA-{uid.upper()[:6]}",
            phone=normalize_phone(u_phone),
            email=u_email,
            token_version=0
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return {"id": u.id, "username": u_name, "phone": u_phone, "email": u_email}
    finally:
        db.close()


def test_login_by_username_email_and_phone():
    user = create_sample_user()

    # 1. Login by Username
    r1 = client.post("/login", json={"username": user["username"], "password": "ValidPassword123"})
    assert r1.status_code == 200
    assert r1.json()["username"] == user["username"]

    # 2. Login by Email
    r2 = client.post("/login", json={"username": user["email"], "password": "ValidPassword123"})
    assert r2.status_code == 200
    assert r2.json()["username"] == user["username"]

    # 3. Login by Phone number
    r3 = client.post("/login", json={"username": user["phone"], "password": "ValidPassword123"})
    assert r3.status_code == 200
    assert r3.json()["username"] == user["username"]


def test_check_username_availability():
    user = create_sample_user()

    # Existing username -> taken
    r1 = client.get(f"/api/auth/check-username?username={user['username']}")
    assert r1.status_code == 200
    assert r1.json()["available"] is False

    # New username -> available
    new_name = f"brand_new_{uuid.uuid4().hex[:8]}"
    r2 = client.get(f"/api/auth/check-username?username={new_name}")
    assert r2.status_code == 200
    assert r2.json()["available"] is True

    # Short username -> unavailable
    r3 = client.get("/api/auth/check-username?username=ab")
    assert r3.status_code == 200
    assert r3.json()["available"] is False


def test_forgot_password_otp_flow():
    user = create_sample_user()

    sent_emails = []
    def fake_send_otp(to_email, name, otp, username):
        sent_emails.append({"to": to_email, "otp": otp, "username": username})
        return True

    with patch("services.brevo_service.send_otp_email", side_effect=fake_send_otp):
        # 1. Request OTP using Phone Number
        req_res = client.post("/api/auth/forgot-password/request-otp", json={"identifier": user["phone"]})
        assert req_res.status_code == 200
        assert req_res.json()["status"] == "ok"
        assert len(sent_emails) == 1
        otp = sent_emails[0]["otp"]
        assert len(otp) == 6

        # 2. Verify with wrong OTP
        bad_res = client.post("/api/auth/forgot-password/verify-and-reset", json={
            "identifier": user["phone"],
            "otp": "000000",
            "new_password": "NewSecretPassword1"
        })
        assert bad_res.status_code == 400
        assert "attempt(s) remaining" in bad_res.json()["detail"]

        # 3. Verify with correct OTP and update password
        good_res = client.post("/api/auth/forgot-password/verify-and-reset", json={
            "identifier": user["phone"],
            "otp": otp,
            "new_password": "NewSecretPassword1"
        })
        assert good_res.status_code == 200
        assert good_res.json()["status"] == "ok"
        assert "token" in good_res.json()

        # 4. Old password fails, new password works
        old_login = client.post("/login", json={"username": user["username"], "password": "ValidPassword123"})
        assert old_login.status_code == 401

        new_login = client.post("/login", json={"username": user["username"], "password": "NewSecretPassword1"})
        assert new_login.status_code == 200


def test_google_verify_and_onboarding_flow(monkeypatch):
    import routes.auth as auth_routes
    monkeypatch.setattr(auth_routes, "_trial_days", lambda: 14)
    monkeypatch.setattr(auth_routes, "_DB_MODE", "cloud")

    uid = uuid.uuid4().hex[:8]
    g_email = f"google_{uid}@gmail.com"
    g_username = f"store_{uid}"
    g_phone = "9" + str(uuid.uuid4().int % 1000000000).zfill(9)

    fake_google_user = {
        "sub": f"google-uid-{uid}",
        "email": g_email,
        "name": "Arun Kumar",
        "picture": "https://example.com/avatar.jpg"
    }

    with patch("routes.auth._verify_google_credential", return_value=fake_google_user):
        # 1. First time Google verify -> needs onboarding
        v1 = client.post("/api/auth/google/verify", json={"credential": "fake_token"})
        assert v1.status_code == 200
        assert v1.json()["status"] == "needs_onboarding"
        assert v1.json()["email"] == g_email

        # 2. Register with chosen username & mandatory phone
        reg_res = client.post("/api/auth/google/register", json={
            "credential": "fake_token",
            "username": g_username,
            "business_name": "Arun Electronics",
            "category": "electronics",
            "phone": g_phone
        })
        assert reg_res.status_code == 200
        assert reg_res.json()["action"] == "registered"
        assert reg_res.json()["username"] == g_username
        assert "token" in reg_res.json()
        assert reg_res.json()["trial"] is not None
        assert reg_res.json()["trial"]["days"] == 14

        # Verify Google user gets 14-day Pro subscription in settings & profile
        tok = reg_res.json()["token"]
        headers = {"Authorization": f"Bearer {tok}"}
        s_res = client.get("/settings", headers=headers)
        assert s_res.status_code == 200
        sub = s_res.json()["subscription"]
        assert sub["plan"] == "pro"
        assert sub["status"] == "trial"
        assert sub["trial"] is True
        assert sub["days_remaining"] == 14

        p_res = client.get("/profile", headers=headers)
        assert p_res.status_code == 200
        assert p_res.json()["is_premium"] is True

        # 3. Second time Google verify -> existing user logs in immediately!
        v2 = client.post("/api/auth/google/verify", json={"credential": "fake_token"})
        assert v2.status_code == 200
        assert v2.json()["action"] == "login"
        assert v2.json()["username"] == g_username
        assert "token" in v2.json()
