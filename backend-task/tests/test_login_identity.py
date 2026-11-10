"""Shared owner discovery and Google identity preserve staff tenant boundaries."""
import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth.transport.requests import Request as GoogleRequest

from app import config
from app.billing_models import BillingUser
from app.db import SessionLocal
from app.models import FieldStaff
from app.routers import auth as auth_router
from tests.conftest import PASSWORD, uniq


@pytest.fixture(autouse=True)
def clear_public_throttle():
    auth_router._PUBLIC_REQUESTS.clear()
    yield
    auth_router._PUBLIC_REQUESTS.clear()


def owner_details(biz, **changes):
    with SessionLocal() as db:
        owner = db.get(BillingUser, biz.business_id)
        for key, value in changes.items():
            setattr(owner, key, value)
        db.commit()


def login_staff(client, business, login, password=PASSWORD, device="test-device-1111"):
    return client.post("/api/auth/staff/login", json={
        "business": business, "login_name": login, "password": password, "device_id": device,
    })


@pytest.fixture(scope="module")
def google_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo).decode()


@pytest.fixture
def google_token(monkeypatch, google_key):
    key, public = google_key
    subject, email = uniq("google"), f"{uniq('merchant')}@gmail.com"
    # Exercise the real google-auth signature/claim verifier without networking.
    monkeypatch.setattr(GoogleRequest, "__call__", lambda *args, **kwargs:
                        SimpleNamespace(status=200, data=json.dumps({"test-key": public}).encode()))

    def make(**claims):
        now = int(time.time())
        data = {"iss": "https://accounts.google.com", "aud": config.GOOGLE_CLIENT_ID,
                "sub": subject, "iat": now - 10, "exp": now + 600,
                "email": email, "email_verified": True, **claims}
        return jwt.encode(data, key, algorithm="RS256", headers={"kid": "test-key"})
    make.subject, make.email = subject, email
    return make


def google_login(client, token):
    return client.post("/api/auth/google/verify", json={"credential": token})


@pytest.mark.parametrize("identifier", ["username", "email", "phone", "public_id"])
def test_owner_identifiers_share_same_business_and_password(client, biz, identifier):
    email = f"{biz.username}@example.com"
    phone = str(8000000000 + biz.business_id)
    owner_details(biz, email=email, phone="+91" + phone)
    values = {"username": biz.username.upper(), "email": email.upper(),
              "phone": f"+91 ({phone[:5]}) {phone[5:]}", "public_id": biz.public_id.lower()}
    response = client.post("/api/auth/owner/login", json={"username": values[identifier], "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["public_id"] == biz.public_id
    assert client.post("/api/auth/owner/login", json={"username": values[identifier], "password": "wrong"}).status_code == 401


def test_public_lookup_is_minimal_active_and_scoped(client, biz, other_biz):
    own = biz.staff(name="Own agent", login="own-agent", phone="9876543211")
    disabled = biz.staff(name="Disabled agent", phone="9876543212")
    other_biz.staff(name="Other agent", phone="9876543213")
    client.patch(f"/api/staff/{disabled['id']}", headers=biz.h, json={"is_active": False})
    owner_details(biz, email="private-owner@example.com", phone="+919876543210")
    response = client.post("/api/auth/lookup-business", json={"identifier": "PRIVATE-OWNER@EXAMPLE.COM"})
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"found", "business_name", "public_id", "has_staff", "staff"}
    assert data["public_id"] == biz.public_id
    assert data["staff"] == [{"id": own["id"], "name": "Own agent", "username": "own-agent"}]
    assert "private-owner" not in response.text and "987654" not in response.text


def test_ambiguous_contacts_and_cross_identifier_matches_do_not_choose_business(client, biz, other_biz):
    owner_details(biz, phone="+919876543210", email=f"{other_biz.username}@example.com")
    owner_details(other_biz, phone="9876543210", email=f"{other_biz.username}@example.com")
    for identifier in ("9876543210", f"{other_biz.username}@example.com"):
        assert client.post("/api/auth/lookup-business", json={"identifier": identifier}).json()["found"] is False
        assert client.post("/api/auth/owner/login", json={"username": identifier, "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/lookup-business", json={"identifier": biz.public_id}).json()["public_id"] == biz.public_id


def test_owner_lookup_does_not_extract_phone_digits_from_username(client, biz):
    owner_details(biz, phone="9876543210")
    assert client.post("/api/auth/lookup-business", json={"identifier": "someone9876543210"}).json()["found"] is False


def test_public_lookup_rate_limit_applies_to_successful_discovery(client, biz):
    for _ in range(30):
        assert client.post("/api/auth/lookup-business", json={"identifier": biz.public_id}).status_code == 200
    response = client.post("/api/auth/lookup-business", json={"identifier": uniq()})
    assert response.status_code == 429 and response.headers["Retry-After"] == "60"


@pytest.mark.parametrize("phone", [None, "", "not a number", "1111111111", "+9198", "+01987654321"])
def test_new_staff_phone_is_required_and_validated(client, biz, phone):
    body = {"name": "Agent", "login_name": uniq("staff"), "password": PASSWORD}
    if phone is not None:
        body["phone"] = phone
    assert client.post("/api/staff", headers=biz.h, json=body).status_code == 422


def test_phone_login_stays_in_business_and_preserves_password_and_device_policy(client, biz, other_biz):
    own = biz.staff(phone="9876543211")
    foreign = other_biz.staff(phone="9876543212")
    assert own["phone"] == "+919876543211"
    assert login_staff(client, biz.public_id, own["phone"]).status_code == 200
    assert login_staff(client, biz.public_id, own["phone"], password="wrong").status_code == 401
    assert login_staff(client, other_biz.public_id, own["phone"]).status_code == 401
    assert login_staff(client, biz.public_id, foreign["phone"]).status_code == 401
    biz.settings(device_policy="bound")
    assert login_staff(client, biz.public_id, "98765 43211", device="bound-phone-111").status_code == 200
    assert login_staff(client, biz.public_id, own["phone"], device="bound-phone-222").status_code == 403


def test_new_staff_duplicate_phone_and_ambiguous_legacy_phone_fail_closed(client, biz):
    first = biz.staff(phone="9876543211")
    second = biz.staff(phone="9876543212")
    body = {"name": "Duplicate", "login_name": uniq("staff"), "phone": "+91 98765 43211", "password": PASSWORD}
    assert client.post("/api/staff", headers=biz.h, json=body).status_code == 400
    assert client.patch(f"/api/staff/{second['id']}", headers=biz.h, json={"phone": first["phone"]}).status_code == 400
    with SessionLocal() as db:
        db.get(FieldStaff, second["id"]).phone = first["phone"]
        db.commit()
    assert login_staff(client, biz.public_id, first["phone"]).status_code == 401
    assert login_staff(client, biz.public_id, first["login_name"]).status_code == 200


def test_legacy_staff_without_phone_can_still_update_and_sign_in(client, biz):
    staff = biz.staff()
    with SessionLocal() as db:
        db.get(FieldStaff, staff["id"]).phone = None
        db.commit()
    assert client.patch(f"/api/staff/{staff['id']}", headers=biz.h, json={"name": "Updated name"}).status_code == 200
    assert login_staff(client, biz.public_id, staff["login_name"]).status_code == 200


@pytest.mark.parametrize("changes", [
    {"aud": "other-app.apps.googleusercontent.com"}, {"iss": "https://evil.example"},
    {"exp": 1}, {"email_verified": False}, {"email_verified": "false"}, {"sub": ""},
    {"sub": None}, {"email": ""}, {"exp": "invalid"},
])
def test_invalid_google_claims_never_issue_session(client, biz, google_token, changes):
    owner_details(biz, email=google_token.email, google_id=google_token.subject)
    assert google_login(client, google_token(**changes)).status_code == 401


def test_forged_google_signature_is_rejected(client, biz, google_token):
    owner_details(biz, google_id=google_token.subject)
    token = google_token()
    header, payload, _ = token.split(".")
    assert google_login(client, f"{header}.{payload}.{'A' * 342}").status_code == 401


def test_google_subject_takes_priority_and_never_changes_billing_identity(client, biz, other_biz, google_token):
    owner_details(biz, email="old-address@example.com", google_id=google_token.subject)
    owner_details(other_biz, email=google_token.email)
    response = google_login(client, google_token())
    assert response.status_code == 200 and response.json()["public_id"] == biz.public_id
    with SessionLocal() as db:
        assert db.get(BillingUser, biz.business_id).email == "old-address@example.com"
        assert db.get(BillingUser, other_biz.business_id).google_id is None


def test_google_unique_authoritative_email_can_sign_in_without_writing_billing(client, biz, google_token):
    owner_details(biz, email=google_token.email.upper())
    response = google_login(client, google_token())
    assert response.status_code == 200 and response.json()["public_id"] == biz.public_id
    with SessionLocal() as db:
        assert db.get(BillingUser, biz.business_id).google_id is None
        assert db.get(BillingUser, biz.business_id).email == google_token.email.upper()


def test_google_email_does_not_override_another_subject_or_ambiguous_owner(client, biz, other_biz, google_token):
    owner_details(biz, email=google_token.email, google_id="different-subject")
    assert google_login(client, google_token()).status_code == 401
    owner_details(biz, google_id=None)
    owner_details(other_biz, email=google_token.email)
    assert google_login(client, google_token()).status_code == 401


def test_unlinked_third_party_google_email_requires_billing_link(client, biz, google_token):
    owner_details(biz, email="merchant@example.com")
    assert google_login(client, google_token(email="merchant@example.com")).status_code == 401
    assert google_login(client, google_token(email="merchant@example.com", hd="example.com")).status_code == 200


def test_google_login_cannot_be_staff_and_obeys_owner_plan(client, biz, google_token, monkeypatch):
    owner_details(biz, google_id=google_token.subject, role="cashier")
    assert google_login(client, google_token()).status_code == 401
    owner_details(biz, role="enterprise")
    monkeypatch.setattr(config, "REQUIRE_PRO", True)
    assert google_login(client, google_token()).status_code == 402
