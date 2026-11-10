"""
tests/test_pro_trial.py
=======================
Every business registered on the cloud starts on a Pro trial, so a new owner
can work on the web at once and later bring the data down to the desktop app
while sync is still Pro.

The rules pinned here:
  • cloud signup → plan "pro", status "trial", ends 14 days from today;
  • a local signup and a local MIRROR of a cloud account never mint a trial
    (the cloud is the plan authority; the desktop copies the plan down);
  • one trial per phone number, however it is typed;
  • a lapsed trial is the free plan, still marked as a trial so the app can say
    "your trial ended" — and taking your data out stays open.

Other workflow suites explicitly mock trial grants off; this suite uses the policy.
"""
import json
import os
import sys
import uuid
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest                                   # noqa: E402
from fastapi.testclient import TestClient       # noqa: E402
from main_groq import app                       # noqa: E402
import routes.auth as auth_routes               # noqa: E402
from database.db import SessionLocal            # noqa: E402
from database.models import User                # noqa: E402
from services.dates import utc_now              # noqa: E402

client = TestClient(app)


@pytest.fixture
def cloud(monkeypatch):
    """Run signup as the cloud backend would, with the default 14-day trial."""
    monkeypatch.setattr(auth_routes, "_DB_MODE", "cloud")
    monkeypatch.setenv("PRO_TRIAL_DAYS", "14")


def _signup(phone=None, public_id=None):
    uname = f"own_{uuid.uuid4().hex[:8]}"
    body = {"username": uname, "password": "TestPass123!", "business_name": "Trial Co"}
    body["phone"] = phone if phone is not None else _unique_phone()
    if public_id is not None:
        body["public_id"] = public_id
    r = client.post("/signup", json=body)
    assert r.status_code == 200, r.text
    return uname, {"Authorization": f"Bearer {r.json()['token']}"}


def _sub(headers):
    r = client.get("/settings", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["subscription"]


def _set_expiry(uname, expires_at):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == uname).first()
        s = json.loads(u.settings)
        s["subscription"]["expires_at"] = expires_at
        u.settings = json.dumps(s)
        db.commit()
    finally:
        db.close()


def _unique_phone():
    return "9" + str(uuid.uuid4().int)[:9]


# ── the grant ────────────────────────────────────────────────────────────────

def test_cloud_signup_starts_a_14_day_pro_trial(cloud):
    _, headers = _signup()
    sub = _sub(headers)
    assert sub["plan"] == "pro"
    assert sub["status"] == "trial"
    assert sub["trial"] is True
    assert sub["expires_at"] == (utc_now().date() + timedelta(days=14)).isoformat()
    assert sub["days_remaining"] == 14
    assert sub["ends_at"].endswith("Z")


def test_trial_makes_the_profile_premium(cloud):
    _, headers = _signup()
    assert client.get("/profile", headers=headers).json()["is_premium"] is True


def test_first_time_trial_cannot_be_changed_by_legacy_env(cloud, monkeypatch):
    monkeypatch.setenv("PRO_TRIAL_DAYS", "30")
    _, headers = _signup()
    assert _sub(headers)["days_remaining"] == 14


def test_first_time_trial_cannot_be_disabled_by_legacy_env(cloud, monkeypatch):
    monkeypatch.setenv("PRO_TRIAL_DAYS", "0")
    _, headers = _signup()
    sub = _sub(headers)
    assert sub["plan"] == "pro"
    assert sub["days_remaining"] == 14


# ── who never gets one ───────────────────────────────────────────────────────

def test_local_signup_gets_no_trial(monkeypatch):
    monkeypatch.setattr(auth_routes, "_DB_MODE", "local")
    monkeypatch.setenv("PRO_TRIAL_DAYS", "14")
    _, headers = _signup()
    sub = _sub(headers)
    assert sub["plan"] == "free"
    assert sub["trial"] is False


def test_local_mirror_of_a_cloud_account_gets_no_trial(monkeypatch):
    """The desktop mirrors a cloud account by passing its BizID. The plan for
    that business already lives on the cloud; minting a second one here would
    give a business that never had a trial, or already used it, a fresh one."""
    monkeypatch.setattr(auth_routes, "_DB_MODE", "local")
    _, headers = _signup(public_id=f"BA-{uuid.uuid4().hex[:6].upper()}")
    assert _sub(headers)["trial"] is False


def test_one_trial_per_phone_however_it_is_typed(cloud):
    phone = _unique_phone()
    _, first = _signup(phone=phone)
    assert _sub(first)["trial"] is True

    spaced = f"+91 {phone[:5]} {phone[5:]}"
    _, second = _signup(phone=spaced)
    sub = _sub(second)
    assert sub["plan"] == "free"
    assert sub["trial"] is False


@pytest.mark.parametrize('phone', [None, '', '12345', '+91 123', 'not-a-number', '+91 999999999999999999'])
def test_phone_is_required_and_validated_before_cloud_account_creation(cloud, phone):
    username = f"own_{uuid.uuid4().hex[:8]}"
    response = client.post('/signup', json={
        'username': username, 'password': 'TestPass123!', 'business_name': 'Invalid phone fixture', 'phone': phone})
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.query(User).filter_by(username=username).first() is None


def test_phone_country_codes_are_not_collapsed_to_last_ten_digits(cloud):
    number = _unique_phone()
    _, first = _signup('+91' + number)
    _, second = _signup('+44' + number)
    assert _sub(first)['trial'] is True
    assert _sub(second)['trial'] is True


def test_trial_failure_rolls_back_account_and_phone_claim(cloud, monkeypatch):
    username = f"own_{uuid.uuid4().hex[:8]}"
    def fail(*args, **kwargs):
        raise RuntimeError('fixture grant failure')
    monkeypatch.setattr(auth_routes, '_start_trial', fail)
    response = client.post('/signup', json={'username': username, 'password': 'TestPass123!',
                                           'business_name': 'Atomic trial fixture', 'phone': _unique_phone()})
    assert response.status_code == 500
    with SessionLocal() as db:
        assert db.query(User).filter_by(username=username).first() is None


def test_deleting_account_does_not_restart_trial_for_same_phone(cloud):
    from services.admin_service import wipe_user_data
    phone = _unique_phone()
    username, _ = _signup(phone)
    with SessionLocal() as db:
        owner = db.query(User).filter_by(username=username).one()
        wipe_user_data(owner.id, db)
    _, second = _signup('+91 ' + phone)
    assert _sub(second)['trial'] is False


def test_concurrent_first_time_signup_grants_one_trial_per_phone(cloud):
    from concurrent.futures import ThreadPoolExecutor
    from database.db import engine
    from database.models import TrialPhoneClaim
    if engine.dialect.name != 'postgresql':
        pytest.skip('Unique-key concurrency requires the real cloud database engine')
    phone = _unique_phone()
    def register(_):
        return client.post('/signup', json={'username': f'own_{uuid.uuid4().hex[:8]}',
            'password': 'TestPass123!', 'business_name': 'Concurrent trial fixture', 'phone': phone})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(register, range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert sum(response.json()['trial'] is not None for response in responses) == 1
    with SessionLocal() as db:
        assert db.query(TrialPhoneClaim).filter_by(phone_hash=auth_routes._phone_key(phone)).count() == 1


# ── the end of the trial ─────────────────────────────────────────────────────

def test_last_day_still_pro_with_zero_days_left(cloud):
    uname, headers = _signup()
    _set_expiry(uname, utc_now().date().isoformat())
    sub = _sub(headers)
    assert sub["plan"] == "pro"
    assert sub["days_remaining"] == 0


def test_lapsed_trial_is_free_but_still_marked_as_a_trial(cloud):
    uname, headers = _signup()
    _set_expiry(uname, (utc_now().date() - timedelta(days=1)).isoformat())
    sub = _sub(headers)
    assert sub["plan"] == "free"
    assert sub["status"] == "trial"
    assert sub["trial"] is True
    assert sub["days_remaining"] == 0
    assert client.get("/profile", headers=headers).json()["is_premium"] is False


def test_lapsed_trial_blocks_sync_but_never_the_way_out(cloud, monkeypatch):
    """After the trial, cloud sync is Pro again — but the owner's data must
    still come out, because that is how a web-only trial user moves to the
    free desktop app."""
    monkeypatch.setenv("SUBSCRIPTION_ENFORCED", "1")
    uname, headers = _signup()
    _set_expiry(uname, (utc_now().date() - timedelta(days=1)).isoformat())

    assert client.post("/api/sync/push", headers=headers, json={"changes": []}).status_code == 402
    assert client.get("/api/data-transfer/export", headers=headers).status_code == 200


# ── what the desktop Register screen is told (Local + Cloud during the trial) ──

def _signup_response(phone=None):
    body = {"username": f"own_{uuid.uuid4().hex[:8]}", "password": "TestPass123!", "business_name": "Trial Co"}
    body["phone"] = phone if phone is not None else _unique_phone()
    r = client.post("/signup", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_signup_reports_the_trial_it_started(cloud):
    trial = _signup_response()["trial"]
    assert trial == {"days": 14, "expires_at": (utc_now().date() + timedelta(days=14)).isoformat()}


def test_signup_reports_no_trial_when_none_was_given(cloud, monkeypatch):
    phone = _unique_phone()
    assert _signup_response(phone)["trial"] is not None
    assert _signup_response(phone)["trial"] is None  # same phone: no second trial
    monkeypatch.setenv("PRO_TRIAL_DAYS", "0")
    assert _signup_response()["trial"]["days"] == 14


def test_local_signup_reports_no_trial(monkeypatch):
    monkeypatch.setattr(auth_routes, "_DB_MODE", "local")
    monkeypatch.setenv("PRO_TRIAL_DAYS", "14")
    assert _signup_response()["trial"] is None


def test_trial_offer_is_public_and_fixed_at_fourteen_days(cloud, monkeypatch):
    assert client.get("/trial-offer").json() == {"days": 14}  # no sign-in needed
    monkeypatch.setenv("PRO_TRIAL_DAYS", "0")
    assert client.get("/trial-offer").json() == {"days": 14}
    monkeypatch.setenv("PRO_TRIAL_DAYS", "14")
    monkeypatch.setattr(auth_routes, "_DB_MODE", "local")  # only the cloud grants trials
    assert client.get("/trial-offer").json() == {"days": 0}

