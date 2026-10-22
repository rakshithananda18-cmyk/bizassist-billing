"""Owner identity is the billing account; field tokens can never act on billing."""
import jwt
import pytest

from app import config
from app.billing_models import BillingUser
from app.db import SessionLocal
from app.security import hash_password
from tests.conftest import PASSWORD, auth, uniq


def _billing_token(claims):
    """A token exactly as billing's services/auth.create_access_token mints it."""
    return jwt.encode(claims, config.JWT_SECRET, algorithm="HS256")


def test_owner_signup_then_login_with_same_credentials(client, biz):
    r = client.post("/api/auth/owner/login", json={"username": biz.username, "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "owner"
    assert body["public_id"].startswith("BA-") and len(body["public_id"]) == 9
    me = client.get("/api/auth/me", headers=auth(body["token"])).json()
    assert me["business_id"] == biz.business_id
    assert me["settings"]["device_policy"] == "single_session"


def test_owner_wrong_password(client, biz):
    r = client.post("/api/auth/owner/login", json={"username": biz.username, "password": "Wrong123x"})
    assert r.status_code == 401


def test_billing_cashier_cannot_sign_in_as_owner(client, biz):
    db = SessionLocal()
    name = uniq("cashier")
    db.add(BillingUser(username=name, password=hash_password(PASSWORD), business_name="x",
                       role="cashier", parent_business_id=biz.business_id))
    db.commit()
    db.close()
    r = client.post("/api/auth/owner/login", json={"username": name, "password": PASSWORD})
    assert r.status_code == 401


def test_task_token_is_rejected_by_billing_style_decode(biz):
    # billing: jwt.decode(token, JWT_SECRET, algorithms=["HS256"]) — no audience.
    with pytest.raises(jwt.InvalidTokenError):
        jwt.decode(biz.token, config.JWT_SECRET, algorithms=["HS256"])


def test_staff_token_is_rejected_by_billing_style_decode(biz):
    s = biz.staff()
    tok = biz.login_staff(s["login_name"])["token"]
    with pytest.raises(jwt.InvalidTokenError):
        jwt.decode(tok, config.JWT_SECRET, algorithms=["HS256"])
    # Even a billing that skipped audience checks still has the wrong key.
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(tok, config.JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False})


def test_billing_owner_token_exchanges_for_task_session(client, biz):
    bt = _billing_token({"id": biz.business_id, "user_id": biz.business_id, "username": biz.username,
                         "public_id": biz.public_id, "role": "enterprise", "tv": 0})
    r = client.post("/api/auth/exchange", json={"billing_token": bt})
    assert r.status_code == 200, r.text
    assert client.get("/api/staff", headers=auth(r.json()["token"])).status_code == 200


def test_billing_staff_token_cannot_exchange(client, biz):
    bt = _billing_token({"id": biz.business_id, "user_id": 999999, "username": "c1",
                         "public_id": biz.public_id, "role": "cashier", "tv": 0})
    assert client.post("/api/auth/exchange", json={"billing_token": bt}).status_code == 403


def test_billing_token_with_other_bizid_is_refused(client, biz):
    bt = _billing_token({"id": biz.business_id, "user_id": biz.business_id, "public_id": "BA-ZZZZZZ",
                         "role": "enterprise", "tv": 0})
    assert client.post("/api/auth/exchange", json={"billing_token": bt}).status_code == 403


def test_billing_force_logout_revokes_task_owner_session(client, biz):
    db = SessionLocal()
    u = db.query(BillingUser).filter(BillingUser.id == biz.business_id).first()
    u.token_version = (u.token_version or 0) + 1  # what billing's "force logout" does
    db.commit()
    db.close()
    assert client.get("/api/staff", headers=biz.h).status_code == 401


def test_signup_password_policy(client):
    r = client.post("/api/auth/owner/signup", json={"username": uniq(), "password": "short", "business_name": "X1"})
    assert r.status_code == 400


def test_signup_refuses_billing_test_prefixes_on_real_db(client, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://u:p@db.example/prod")
    r = client.post("/api/auth/owner/signup", json={"username": "test_" + uniq(), "password": PASSWORD,
                                                    "business_name": "Real Shop"})
    assert r.status_code == 400


def test_duplicate_username(client, biz):
    r = client.post("/api/auth/owner/signup", json={"username": biz.username, "password": PASSWORD,
                                                    "business_name": "Again"})
    assert r.status_code == 400


def test_garbage_token(client):
    assert client.get("/api/auth/me", headers=auth("not-a-jwt")).status_code == 401
    assert client.get("/api/auth/me").status_code == 401
