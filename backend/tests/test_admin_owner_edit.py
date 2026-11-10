"""Admin profile edits preserve identity, trials, and truthful mail history."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database.models import Base, EmailLog, PasswordResetOTP, User
from routes.admin import AdminUpdateUserRequest, SubscriptionRequest
from services import admin_service, brevo_service
from services.auth import hash_password, verify_password
from services.dates import utc_now


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'admin_test.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def owner(db):
    user = User(username="owner", password=hash_password("OriginalPass1"),
                role="enterprise", business_name="Owner Store", public_id="BA-OWNER",
                email="owner@example.com", phone="+919876543210", pan="ABCDE1234F",
                state_code="29", counter_prefix="OW", logo="https://example.com/logo.png",
                settings=json.dumps({"subscription": {"plan": "pro", "status": "trial", "expires_at": "2030-01-01"}}))
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def mail(monkeypatch):
    account, password = Mock(), Mock()
    monkeypatch.setattr(brevo_service, "send_account_update_email", account)
    monkeypatch.setattr(brevo_service, "send_password_changed_email", password)
    return account, password


def edit(db, owner, **patch):
    return admin_service.update_merchant(owner.id, AdminUpdateUserRequest(**patch), db)


def test_noop_preserves_trial_and_sends_no_mail(db, owner, mail):
    before = owner.settings
    edit(db, owner, business_name=owner.business_name, hosting_mode="local", phone="9876543210")
    assert owner.settings == before
    assert json.loads(owner.settings)["subscription"]["status"] == "trial"
    mail[0].assert_not_called()
    mail[1].assert_not_called()


def test_plan_noop_preserves_trial_and_change_notifies_after_commit(db, owner, mail):
    admin = SimpleNamespace(username="operator")
    previous = owner.settings
    admin_service.set_subscription(owner.id, SubscriptionRequest(plan="pro", status="trial", expires_at="2030-01-01"), admin, db)
    assert owner.settings == previous
    mail[0].assert_not_called()
    admin_service.set_subscription(owner.id, SubscriptionRequest(plan="free"), admin, db)
    assert "subscription" not in json.loads(owner.settings)
    mail[0].assert_called_once()
    assert mail[0].call_args.kwargs == {"business_id": owner.id}
    mail[0].reset_mock()
    admin_service.set_subscription(owner.id, SubscriptionRequest(plan="free"), admin, db)
    mail[0].assert_not_called()


def test_list_and_details_hydrate_every_editable_profile_field(db, owner):
    for row in (admin_service.list_businesses(db, owner.id)[0], admin_service.business_details(owner.id, db)):
        for key in ("pan", "state_code", "logo", "counter_prefix"):
            assert row[key] == getattr(owner, key)
        assert row["hosting_mode"] == "local"


@pytest.mark.parametrize("dialect,default", [("sqlite", "local"), ("postgresql", "cloud")])
def test_storage_default_respects_deployment_and_explicit_local(dialect, default):
    bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
    session = SimpleNamespace(get_bind=lambda: bind)
    user = SimpleNamespace(settings=json.dumps({"subscription": {"plan": "pro", "status": "trial"}}), google_id="google")
    assert admin_service.business_hosting_mode(user, session) == default
    user.settings = json.dumps({"general": {"hosting_mode": "local"}})
    assert admin_service.business_hosting_mode(user, session) == "local"


def test_owner_details_and_storage_changes_preserve_trial(db, owner, mail):
    subscription = json.loads(owner.settings)["subscription"]
    edit(db, owner, pan="NEWPAN1234", state_code="33", logo="https://example.com/new.png",
         counter_prefix="C-1", upi_vpa="store@upi", hosting_mode="hybrid")
    db.refresh(owner)
    assert (owner.pan, owner.state_code, owner.counter_prefix, owner.upi_vpa) == ("NEWPAN1234", "33", "C1", "store@upi")
    assert json.loads(owner.settings)["subscription"] == subscription
    labels = " ".join(mail[0].call_args.args[2])
    assert all(label in labels for label in ("PAN", "State Code", "Business Logo", "Counter Prefix", "UPI VPA", "Storage"))


@pytest.mark.parametrize("role,parent", [("admin", None), ("cashier", 1), ("deleted", None)])
def test_edit_cannot_target_admin_staff_or_deleted_accounts(db, owner, role, parent):
    owner.role, owner.parent_business_id = role, parent
    db.commit()
    with pytest.raises(HTTPException) as error:
        edit(db, owner, business_name="Wrong target")
    assert error.value.status_code == 404
    assert owner.business_name == "Owner Store"


@pytest.mark.parametrize("patch", [
    {"email": "invalid"}, {"phone": "123"}, {"hosting_mode": "arbitrary"},
    {"password": "weak"}, {"email": "", "password": "StrongPass1"},
])
def test_invalid_patch_is_rejected_before_any_mutation(db, owner, mail, patch):
    with pytest.raises(HTTPException):
        edit(db, owner, business_name="Must not persist", **patch)
    assert owner.business_name == "Owner Store"
    assert verify_password("OriginalPass1", owner.password)
    mail[0].assert_not_called()
    mail[1].assert_not_called()


@pytest.mark.parametrize("patch", [{"email": " SECOND@EXAMPLE.COM "}, {"phone": "+919999888877"}])
def test_duplicate_owner_contacts_are_rejected(db, owner, patch):
    db.add(User(username="second", password="unused", role="enterprise", email="second@example.com", phone="9999888877"))
    db.commit()
    with pytest.raises(HTTPException) as error:
        edit(db, owner, **patch)
    assert error.value.status_code == 400


def test_password_whitespace_is_preserved_and_same_password_is_noop(db, owner, mail):
    password = " StrongPass1 "
    edit(db, owner, password=password)
    assert verify_password(password, owner.password)
    assert not verify_password(password.strip(), owner.password)
    assert owner.token_version == 1
    mail[1].assert_called_once()
    mail[0].assert_not_called()
    mail[1].reset_mock()
    edit(db, owner, password=password)
    assert owner.token_version == 1
    mail[1].assert_not_called()


def test_username_change_revokes_stale_account_claims(db, owner, mail):
    edit(db, owner, username="new-owner-name")
    assert owner.token_version == 1
    mail[0].assert_called_once()
    mail[1].assert_not_called()


def test_email_change_notifies_both_contacts_after_commit(db, owner, mail):
    owner_id = owner.id
    observed = []
    def assert_committed(*args, **kwargs):
        assert kwargs == {"business_id": owner_id}
        with Session(db.get_bind()) as reader:
            observed.append(reader.get(User, owner_id).email)
    mail[0].side_effect = assert_committed
    edit(db, owner, email=" NEW@EXAMPLE.COM ")
    assert {call.args[0] for call in mail[0].call_args_list} == {"owner@example.com", "new@example.com"}
    assert observed == ["new@example.com", "new@example.com"]


def test_failed_commit_sends_no_notification(db, owner, mail, monkeypatch):
    def fail():
        raise RuntimeError("write failed")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError, match="write failed"):
        edit(db, owner, password="StrongPass1", address="New street")
    mail[0].assert_not_called()
    mail[1].assert_not_called()
    db.rollback()


def test_mail_history_has_only_real_dispatches_and_counts_sent_once(db, owner):
    assert admin_service.get_business_email_history(db, owner) == []
    db.add(PasswordResetOTP(user_id=owner.id, identifier=owner.email, otp_hash="not-a-code", purpose="password_reset", expires_at=utc_now()))
    for status in ("sent", "dev_suppressed", "failed"):
        db.add(EmailLog(business_id=owner.id, recipient_email=owner.email, subject="OTP", template_type="otp", status=status))
    db.add(EmailLog(recipient_email=owner.email.upper(), subject="Legacy email", template_type="welcome", status="sent"))
    # A contact match must never expose a dispatch owned by another tenant.
    db.add(EmailLog(business_id=999, recipient_email=owner.email, subject="Other tenant", template_type="welcome", status="sent"))
    db.commit()
    history = admin_service.get_business_email_history(db, owner)
    assert len(history) == 4
    assert {row["status"] for row in history} == {"sent", "failed", "dev_suppressed"}
    assert admin_service.list_businesses(db, owner.id)[0]["mails_sent_count"] == 2
