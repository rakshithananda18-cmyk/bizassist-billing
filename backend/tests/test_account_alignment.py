"""Account discovery, tenant-scoped sign-in and security notification regressions."""
import time
import uuid
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from database.db import SessionLocal
from database.models import User
from main_groq import app
from services.auth import hash_password, verify_password


client = TestClient(app)
PASSWORD = "AccountPass123!"


@pytest.fixture(autouse=True)
def local_account_dependencies(monkeypatch, request):
    """Exercise account persistence without contacting mail or cloud services."""
    monkeypatch.setattr("routes.auth.check_ip_rate_limit", lambda *_: {"allowed": True})
    monkeypatch.setattr("services.immediate_sync.push_profile_to_cloud", lambda *a, **kw: None)
    monkeypatch.setattr("core.api.staff._push_staff_to_cloud", lambda *a, **kw: None)
    monkeypatch.setattr("services.control_outbox.trigger_control_flush", lambda *_: None)
    monkeypatch.setattr("services.brevo_service.is_brevo_configured", lambda: False)
    if request.node.name == "test_notification_html_escapes_profile_and_account_values":
        return
    account_mail, password_mail = Mock(return_value=True), Mock(return_value=True)
    monkeypatch.setattr("services.brevo_service.send_account_update_email", account_mail)
    monkeypatch.setattr("services.brevo_service.send_password_changed_email", password_mail)
    return account_mail, password_mail


@pytest.fixture
def make_user():
    def create(**overrides):
        suffix = uuid.uuid4().hex[:12]
        data = {
            "username": f"align_{suffix}", "password": hash_password(PASSWORD),
            "business_name": f"Alignment {suffix}", "role": "enterprise",
            "public_id": f"BA-{suffix.upper()}", "email": f"{suffix}@example.com",
            "phone": "+919" + str(int(suffix, 16) % 1_000_000_000).zfill(9),
        }
        data.update(overrides)
        with SessionLocal() as db:
            user = User(**data)
            db.add(user)
            db.commit()
            db.refresh(user)
            return {key: getattr(user, key) for key in
                    ("id", "username", "email", "phone", "public_id", "business_name", "role")}
    return create


def _headers(owner):
    response = client.post("/login", json={"username": owner["username"], "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _google_data(email, **overrides):
    return {"sub": uuid.uuid4().hex, "email": email, "name": "Google Merchant", "picture": "", **overrides}


def test_owner_discovery_identifiers_and_public_roster_privacy(make_user):
    owner, other = make_user(), make_user()
    cashier = make_user(parent_business_id=owner["id"], role="cashier", staff_login_name="Counter One")
    supply = make_user(parent_business_id=owner["id"], role="supply adder", staff_login_name="Supply Counter")
    make_user(parent_business_id=owner["id"], role="admin", staff_login_name="Platform Admin")
    make_user(parent_business_id=owner["id"], role="deleted", staff_login_name="Retired Counter")
    make_user(parent_business_id=other["id"], role="cashier", staff_login_name="Other Counter")

    for identifier in (owner["username"].upper(), owner["email"].upper(),
                       owner["phone"][3:], owner["public_id"].lower()):
        response = client.post("/api/auth/lookup-business", json={"identifier": identifier})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["found"] is True
        assert body["public_id"] == owner["public_id"]
        assert body["staff"] == [
            {"id": cashier["id"], "username": "Counter One", "role": "cashier"},
            {"id": supply["id"], "username": "Supply Counter", "role": "supply adder"},
        ]
        assert "phone" not in body and "email" not in body and "username" not in body
        assert not any(key in item for item in body["staff"] for key in ("phone", "email", "password"))

    # Staff contact details must not reveal their owner's public business roster.
    assert client.post("/api/auth/lookup-business", json={"identifier": cashier["phone"]}).json()["found"] is False


def test_ambiguous_business_identity_never_selects_an_arbitrary_owner(make_user):
    first = make_user()
    make_user(email=first["email"].upper())
    response = client.post("/api/auth/lookup-business", json={"identifier": first["email"]})
    assert response.status_code == 200
    assert response.json()["found"] is False
    response = client.post("/login", json={"username": first["email"], "password": PASSWORD})
    assert response.status_code == 401


def test_staff_phone_required_even_under_pytest(make_user):
    owner = make_user()
    response = client.post("/staff", headers=_headers(owner), json={"username": "counter", "password": PASSWORD})
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.query(User).filter(User.parent_business_id == owner["id"]).count() == 0


def test_staff_username_and_phone_authenticate_only_in_selected_business(make_user):
    owner, other = make_user(), make_user()
    cashier = make_user(parent_business_id=owner["id"], role="cashier", staff_login_name="Counter")
    other_cashier = make_user(parent_business_id=other["id"], role="cashier", staff_login_name="Counter",
                             password=hash_password("OtherPassword123!"))
    for identifier in ("COUNTER", cashier["phone"][3:]):
        response = client.post("/login/staff", json={
            "owner_username": owner["email"].upper(), "staff_login_name": identifier, "password": PASSWORD,
        })
        assert response.status_code == 200, response.text
        assert response.json()["id"] == owner["id"]
        assert response.json()["user_id"] == cashier["id"]
        assert response.json()["public_id"] == owner["public_id"]
        wrong_business = client.post("/login/staff", json={
            "owner_username": other["public_id"], "staff_login_name": identifier, "password": PASSWORD,
        })
        assert wrong_business.status_code == 401, wrong_business.text
    assert other_cashier["id"] != cashier["id"]


def test_staff_password_reset_requires_valid_owner_email(make_user, local_account_dependencies):
    owner = make_user(email="legacy-invalid-address")
    staff = make_user(parent_business_id=owner["id"], role="cashier", staff_login_name="Counter")
    response = client.patch(f"/staff/{staff['id']}", headers=_headers(owner), json={"password": "ChangedStaffPass123!"})
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert verify_password(PASSWORD, db.get(User, staff["id"]).password)
    local_account_dependencies[1].assert_not_called()


def test_staff_password_notification_observes_committed_password(make_user, local_account_dependencies):
    owner = make_user()
    staff = make_user(parent_business_id=owner["id"], role="cashier", staff_login_name="Counter")
    password = "  ChangedStaffPass123!  "
    observations = []

    def observe_password(address, _name, account_name, **_kwargs):
        with SessionLocal() as db:
            saved = db.get(User, staff["id"])
            assert verify_password(password, saved.password)
            assert not verify_password(password.strip(), saved.password)
        observations.append((address, account_name))
        return True

    local_account_dependencies[1].side_effect = observe_password
    response = client.patch(f"/staff/{staff['id']}", headers=_headers(owner), json={"password": password})
    assert response.status_code == 200, response.text
    assert observations == [(owner["email"], "Counter")]


def test_failed_staff_password_commit_does_not_send_notification(make_user, local_account_dependencies):
    owner = make_user()
    staff = make_user(parent_business_id=owner["id"], role="cashier", staff_login_name="Counter")
    headers = _headers(owner)
    with patch.object(Session, "commit", side_effect=RuntimeError("simulated commit failure")):
        response = TestClient(app, raise_server_exceptions=False).patch(
            f"/staff/{staff['id']}", headers=headers, json={"password": "ChangedStaffPass123!"})
    assert response.status_code == 500
    local_account_dependencies[1].assert_not_called()
    with SessionLocal() as db:
        assert verify_password(PASSWORD, db.get(User, staff["id"]).password)


@pytest.mark.parametrize("email", [None, "not-an-email", "missing@domain", "bad name@example.com"])
def test_profile_password_update_requires_valid_registered_email(make_user, email, local_account_dependencies):
    owner = make_user(email=email)
    response = client.put("/profile", headers=_headers(owner), json={"password": "ChangedPass123!"})
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert verify_password(PASSWORD, db.get(User, owner["id"]).password)
    for mail in local_account_dependencies:
        mail.assert_not_called()


def test_profile_password_preserves_whitespace_and_notifies_after_commit(make_user, local_account_dependencies):
    owner = make_user()
    new_email = f"{uuid.uuid4().hex}@example.com"
    new_password = "  ChangedPass123!  "
    account_mail, password_mail = local_account_dependencies
    committed = []

    def observe_committed(address, *_args, **_kwargs):
        with SessionLocal() as db:
            saved = db.get(User, owner["id"])
            assert saved.email == new_email
            assert verify_password(new_password, saved.password)
            assert not verify_password(new_password.strip(), saved.password)
        committed.append(address)
        return True

    account_mail.side_effect = observe_committed
    password_mail.side_effect = observe_committed
    response = client.put("/profile", headers=_headers(owner), json={"email": new_email, "password": new_password})
    assert response.status_code == 200, response.text
    assert {call.args[0] for call in account_mail.call_args_list} == {owner["email"], new_email}
    assert {call.args[0] for call in password_mail.call_args_list} == {owner["email"], new_email}
    assert len(committed) == 4


def test_unchanged_profile_does_not_send_security_notification(make_user, local_account_dependencies):
    owner = make_user()
    response = client.put("/profile", headers=_headers(owner), json={"business_name": owner["business_name"], "email": owner["email"]})
    assert response.status_code == 200, response.text
    for mail in local_account_dependencies:
        mail.assert_not_called()


def test_failed_profile_commit_does_not_send_notification(make_user, local_account_dependencies):
    owner = make_user()
    headers = _headers(owner)
    with patch.object(Session, "commit", side_effect=RuntimeError("simulated commit failure")):
        response = TestClient(app, raise_server_exceptions=False).put(
            "/profile", headers=headers, json={"business_name": "Uncommitted business"})
    assert response.status_code == 500
    for mail in local_account_dependencies:
        mail.assert_not_called()
    with SessionLocal() as db:
        assert db.get(User, owner["id"]).business_name == owner["business_name"]


def test_manual_gmail_account_links_once_and_google_subject_preserves_contact_email(make_user):
    owner = make_user(email=f"{uuid.uuid4().hex}@gmail.com")
    data = _google_data(owner["email"], email_authoritative=True)
    with patch("routes.auth._verify_google_credential", return_value=data):
        response = client.post("/api/auth/google/verify", json={"credential": "verified-google-token"})
        assert response.status_code == 200, response.text
        assert response.json()["action"] == "login"
        assert response.json()["id"] == owner["id"]
        edited_email = f"{uuid.uuid4().hex}@example.com"
        headers = {"Authorization": f"Bearer {response.json()['token']}"}
        changed = client.put("/profile", headers=headers, json={"email": edited_email})
        assert changed.status_code == 200, changed.text
        again = client.post("/api/auth/google/verify", json={"credential": "verified-google-token"})
        assert again.status_code == 200, again.text
        assert again.json()["id"] == owner["id"]
    with SessionLocal() as db:
        assert db.get(User, owner["id"]).google_id == data["sub"]
        assert db.get(User, owner["id"]).email == edited_email
        assert db.query(User).filter(User.google_id == data["sub"]).count() == 1


def test_third_party_google_email_requires_existing_password_to_link(make_user):
    owner = make_user()
    data = _google_data(owner["email"], email_authoritative=False)
    with patch("routes.auth._verify_google_credential", return_value=data):
        response = client.post("/api/auth/google/verify", json={"credential": "verified-google-token"})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "needs_link"
        assert "token" not in response.json()
        rejected = client.post("/api/auth/google/verify", json={"credential": "verified-google-token", "password": "WrongPass123!"})
        assert rejected.status_code == 401
        with SessionLocal() as db:
            assert db.get(User, owner["id"]).google_id is None
        confirmed = client.post("/api/auth/google/verify", json={"credential": "verified-google-token", "password": PASSWORD})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["action"] == "login"
        assert confirmed.json()["id"] == owner["id"]


def test_google_does_not_auto_link_ambiguous_email_or_allow_duplicate_onboarding(make_user):
    email = f"{uuid.uuid4().hex}@gmail.com"
    owner = make_user(email=email)
    data = _google_data(email, email_authoritative=True)
    payload = {"credential": "verified-google-token", "username": f"new_{uuid.uuid4().hex[:8]}",
               "business_name": "Duplicate Store", "phone": "9198765432"}
    with patch("routes.auth._verify_google_credential", return_value=data):
        duplicate = client.post("/api/auth/google/register", json=payload)
        assert duplicate.status_code == 409, duplicate.text
        make_user(email=email.upper())
        ambiguous = client.post("/api/auth/google/verify", json={"credential": "verified-google-token"})
        assert ambiguous.status_code == 409, ambiguous.text
        assert "token" not in ambiguous.json()
        ambiguous_registration = client.post("/api/auth/google/register", json=payload)
        assert ambiguous_registration.status_code == 409, ambiguous_registration.text
    with SessionLocal() as db:
        assert db.get(User, owner["id"]).google_id is None
        assert db.query(User).filter(User.username == payload["username"]).count() == 0


def test_google_onboarding_rejects_already_linked_subject_after_contact_email_edit(make_user):
    subject = uuid.uuid4().hex
    owner = make_user(google_id=subject)
    data = _google_data(f"{uuid.uuid4().hex}@gmail.com", sub=subject, email_authoritative=True)
    username = f"duplicate_{uuid.uuid4().hex[:8]}"
    with patch("routes.auth._verify_google_credential", return_value=data):
        response = client.post("/api/auth/google/register", json={
            "credential": "verified-google-token", "username": username,
            "business_name": "Duplicate Business", "phone": "9876543211",
        })
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.get(User, owner["id"]).email == owner["email"]
        assert db.query(User).filter(User.username == username).count() == 0


@pytest.mark.parametrize("claims", [
    {"aud": "another-client"}, {"iss": "https://attacker.example"}, {"sub": ""},
    {"exp": 1}, {"email_verified": False}, {"email_verified": "true"}, {"email": "invalid-email"},
])
def test_google_invalid_claims_never_authenticate(monkeypatch, claims):
    audience = "test-client.apps.googleusercontent.com"
    monkeypatch.setenv("GOOGLE_CLIENT_ID", audience)
    token_claims = {"aud": audience, "iss": "https://accounts.google.com", "sub": "google-subject",
                    "exp": time.time() + 300, "email_verified": True, "email": "merchant@gmail.com", **claims}
    with patch("google.oauth2.id_token.verify_oauth2_token", return_value=token_claims) as verifier:
        response = client.post("/api/auth/google/verify", json={"credential": "signed-id-token"})
    assert response.status_code == 401, response.text
    assert "token" not in response.json()
    assert verifier.call_args.kwargs["audience"] == audience


def test_google_claim_verifier_requires_signature_verification(monkeypatch):
    from services.google_identity import verify_google_identity
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "configured-client")
    with patch("google.oauth2.id_token.verify_oauth2_token", side_effect=ValueError("invalid signature")):
        with pytest.raises(HTTPException) as error:
            verify_google_identity("forged-token")
    assert error.value.status_code == 401


def test_notification_html_escapes_profile_and_account_values(monkeypatch):
    from services import brevo_service
    monkeypatch.setattr(brevo_service, "is_brevo_configured", lambda: True)
    monkeypatch.setattr(brevo_service, "log_email_dispatch", lambda *a, **kw: None)
    with patch("services.brevo_service.httpx.Client") as provider:
        provider.return_value.__enter__.return_value.post.return_value.status_code = 201
        assert brevo_service.send_account_update_email("valid@example.com", "<img src=x>", ["<script>bad()</script>"])
        assert brevo_service.send_password_changed_email("valid@example.com", "<img src=x>", "<b>counter</b>")
    posted = provider.return_value.__enter__.return_value.post.call_args_list
    account_html, password_html = [call.kwargs["json"]["htmlContent"] for call in posted]
    assert "&lt;img src=x&gt;" in account_html and "<img src=x>" not in account_html
    assert "&lt;script&gt;bad()&lt;/script&gt;" in account_html and "<script>bad()" not in account_html
    assert "&lt;img src=x&gt;" in password_html and "<img src=x>" not in password_html
    assert "&lt;b&gt;counter&lt;/b&gt;" in password_html and "<b>counter</b>" not in password_html
