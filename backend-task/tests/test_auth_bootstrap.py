"""Public authentication binds a resolved tenant before reading RLS tables."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.billing_models import BillingUser
from app.routers import auth
from app import security
from app.models import FieldStaff


def pg_session(monkeypatch, *, fail=False):
    events = []
    monkeypatch.setattr(auth.config, "CREATE_BILLING_MIRROR", False)
    db = MagicMock()
    db.bind.dialect.name = "postgresql"
    owner = BillingUser(id=41, username="owner", public_id="BA-TEST41", business_name="Business", role="enterprise")
    db.execute.return_value.scalar.return_value = 41
    if fail:
        db.execute.side_effect = SQLAlchemyError("bootstrap denied")
    query = MagicMock()
    query.filter.return_value.first.return_value = owner
    db.query.side_effect = lambda model: events.append("read") or query
    monkeypatch.setattr(auth, "set_rls_business", lambda session, bid: events.append(("bind", bid)))
    monkeypatch.setattr(auth, "owner_token", lambda user: "test-token")
    monkeypatch.setattr(auth, "ensure_pro", lambda user, kind: None)
    return db, owner, events


def test_owner_bootstrap_precedes_rls_table_read(monkeypatch):
    db, owner, events = pg_session(monkeypatch)
    assert auth._resolve_owner(db, "OWNER@example.com") is owner
    assert events == [("bind", 41), "read"]
    sql, params = db.execute.call_args.args
    assert "bizassist_owner_identifier" in str(sql) and params == {"login": "OWNER@example.com"}


def test_owner_bootstrap_failure_has_no_unscoped_fallback(monkeypatch):
    db, _, events = pg_session(monkeypatch, fail=True)
    with pytest.raises(HTTPException) as exc:
        auth._resolve_owner(db, "owner")
    assert exc.value.status_code == 503 and not events
    db.query.assert_not_called()


@pytest.mark.parametrize("email, hd, fallback", [
    ("owner@gmail.com", None, "owner@gmail.com"),
    ("owner@example.com", "example.com", "owner@example.com"),
    ("owner@example.com", None, None),
])
def test_google_bootstrap_uses_verified_subject_and_only_authoritative_email(monkeypatch, email, hd, fallback):
    db, _, events = pg_session(monkeypatch)
    monkeypatch.setattr(auth, "_public_throttle", lambda *args: None)
    monkeypatch.setattr(auth, "_verify_google_credential", lambda token: {"sub": "subject", "email": email, "hd": hd})
    response = auth.google_verify(auth.GoogleVerifyRequest(credential="valid"), SimpleNamespace(), db)
    assert response["token"] == "test-token" and response["public_id"] == "BA-TEST41"
    assert events == [("bind", 41), "read"]
    sql, params = db.execute.call_args.args
    assert "bizassist_google_owner" in str(sql) and params == {"subject": "subject", "email": fallback}


def test_google_bootstrap_failure_has_no_unscoped_fallback(monkeypatch):
    db, _, events = pg_session(monkeypatch, fail=True)
    monkeypatch.setattr(auth, "_public_throttle", lambda *args: None)
    monkeypatch.setattr(auth, "_verify_google_credential", lambda token: {"sub": "subject", "email": "owner@gmail.com"})
    with pytest.raises(HTTPException) as exc:
        auth.google_verify(auth.GoogleVerifyRequest(credential="valid"), SimpleNamespace(), db)
    assert exc.value.status_code == 503 and not events
    db.query.assert_not_called()


def test_google_bootstrap_conflict_is_refused_before_tenant_bind(monkeypatch):
    db, _, events = pg_session(monkeypatch)
    db.execute.return_value.scalar.return_value = -1
    monkeypatch.setattr(auth, "_public_throttle", lambda *args: None)
    monkeypatch.setattr(auth, "_verify_google_credential", lambda token: {"sub": "subject", "email": "owner@gmail.com"})
    with pytest.raises(HTTPException) as exc:
        auth.google_verify(auth.GoogleVerifyRequest(credential="valid"), SimpleNamespace(), db)
    assert exc.value.status_code == 409 and not events
    db.query.assert_not_called()


@pytest.mark.parametrize("kind", ["owner", "staff"])
def test_signed_session_binds_tenant_before_reading_billing_owner(monkeypatch, kind):
    events = []
    db = MagicMock()
    owner = BillingUser(id=41, username="owner", public_id="BA-TEST41", role="enterprise", token_version=0)
    staff = FieldStaff(id=7, business_id=41, name="Agent", is_active=True, token_version=0,
                       active_session_id="session", bound_device_id=None)
    rows = iter([owner] if kind == "owner" else [owner, staff])
    query = MagicMock()
    query.filter.return_value.first.side_effect = lambda: next(rows)
    db.query.side_effect = lambda model: events.append("read") or query
    monkeypatch.setattr(security, "decode_task_token", lambda token:
                        {"typ": kind, "bid": 41, "uid": 41, "sid": 7, "ses": "session", "tv": 0})
    monkeypatch.setattr(security, "set_rls_business", lambda session, bid: events.append(("bind", bid)))
    monkeypatch.setattr(security, "get_settings", lambda *args: SimpleNamespace(device_policy="single_session"))
    principal = security.signed_in_principal("Bearer signed-token", db)
    assert principal.kind == kind and principal.business_id == 41
    assert events == [("bind", 41)] + ["read"] * (1 if kind == "owner" else 2)


def test_billing_exchange_binds_signed_owner_claim_before_read(monkeypatch):
    db, _, events = pg_session(monkeypatch)
    monkeypatch.setattr(auth, "decode_billing_token", lambda token:
                        {"id": 41, "user_id": 41, "role": "enterprise", "tv": 0})
    response = auth.exchange_billing_token(auth.ExchangeRequest(billing_token="signed"), db)
    assert response["token"] == "test-token"
    assert events == [("bind", 41), "read"]
