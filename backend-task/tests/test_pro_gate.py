"""Field Team is part of BizAssist Pro (app/plan.py).

The plan is read from the owner's billing `users.settings` → `subscription`,
exactly as billing's admin console writes it. The gate is off unless
SUBSCRIPTION_ENFORCED is on (config.REQUIRE_PRO), like billing's own.
"""
import json
from datetime import datetime, timedelta

import pytest

from app import config
from app.billing_models import BillingUser
from app.db import SessionLocal, utc_now
from app.plan import plan_out, plan_state
from tests.conftest import PASSWORD, auth
from tests.test_auth import _billing_ticket, _owner_claims


def _set_plan(business_id, plan=None, expires_at=None, status="active"):
    """What billing writes: an admin grant (plan="pro"), a revoke (None), or —
    on cloud sign-up — a free trial (status="trial")."""
    db = SessionLocal()
    try:
        user = db.query(BillingUser).filter(BillingUser.id == business_id).first()
        s = json.loads(user.settings or "{}")
        if plan is None:
            s.pop("subscription", None)
        else:
            s["subscription"] = {"plan": plan, "status": status, "expires_at": expires_at}
        user.settings = json.dumps(s)
        db.commit()
    finally:
        db.close()


def _days_ago(n):
    return (utc_now() - timedelta(days=n)).date().isoformat()


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_PRO", True)


def _owner(sub):
    return BillingUser(settings=json.dumps({"theme": "dark", **({"subscription": sub} if sub else {})}))


NOW = datetime(2026, 10, 23, 15, 0)  # naive UTC


@pytest.mark.parametrize("sub, plan, allowed, grace", [
    ({"plan": "pro"}, "pro", True, None),                                   # no end date
    ({"plan": "pro", "expires_at": "2026-10-23"}, "pro", True, None),       # a date runs to the END of that day
    ({"plan": "pro", "expires_at": "2026-10-23T20:00:00+05:30"}, "free", True, datetime(2026, 10, 30, 14, 30)),
    ({"plan": "pro", "expires_at": "2026-10-20"}, "free", True, datetime(2026, 10, 28)),   # expired: grace
    ({"plan": "pro", "expires_at": "2026-10-15"}, "free", False, datetime(2026, 10, 23)),  # grace over at midnight
    ({"plan": "free"}, "free", False, None),
    (None, "free", False, None),                                            # revoked: no grace
    # Billing's free trial (status "trial"): Pro until its last day, then no grace.
    ({"plan": "pro", "status": "trial", "expires_at": "2026-10-23"}, "pro", True, None),
    ({"plan": "pro", "status": "trial", "expires_at": "2026-10-22"}, "free", False, None),
    ({"plan": "pro", "status": "TRIAL", "expires_at": "2026-10-20"}, "free", False, None),
])
def test_plan_rule(sub, plan, allowed, grace):
    st = plan_state(_owner(sub), now=NOW)
    assert (st.plan, st.allowed, st.grace_until) == (plan, allowed, grace)


def test_a_trial_is_flagged_and_warned_like_a_plan(gate):
    ending = plan_out(plan_state(_owner({"plan": "pro", "status": "trial", "expires_at": "2026-10-27"}), now=NOW), now=NOW)
    assert ending["trial"] and ending["warn"] and not ending["in_grace"]
    paid = plan_out(plan_state(_owner({"plan": "pro", "status": "active", "expires_at": "2026-10-27"}), now=NOW), now=NOW)
    assert paid["trial"] is False


def test_unreadable_settings_count_as_free():
    assert plan_state(BillingUser(settings="{not json"), now=NOW).allowed is False
    assert plan_state(BillingUser(settings=None), now=NOW).allowed is False
    assert plan_state(None, now=NOW).allowed is False


def test_owner_is_warned_before_the_end_and_during_grace(monkeypatch, gate):
    soon = plan_out(plan_state(_owner({"plan": "pro", "expires_at": "2026-10-27"}), now=NOW), now=NOW)
    assert soon["warn"] and not soon["in_grace"] and soon["ends_at"] == "2026-10-28T00:00:00Z"
    later = plan_out(plan_state(_owner({"plan": "pro", "expires_at": "2026-12-31"}), now=NOW), now=NOW)
    assert not later["warn"]
    grace = plan_out(plan_state(_owner({"plan": "pro", "expires_at": "2026-10-20"}), now=NOW), now=NOW)
    assert grace["warn"] and grace["in_grace"] and grace["grace_until"] == "2026-10-28T00:00:00Z"
    monkeypatch.setattr(config, "REQUIRE_PRO", False)
    assert not plan_out(plan_state(_owner({"plan": "pro", "expires_at": "2026-10-20"}), now=NOW), now=NOW)["warn"]


def test_gate_is_off_unless_enforced(client, biz):
    assert config.REQUIRE_PRO is False  # the suite's default, like billing's local runs
    assert client.get("/api/shops", headers=biz.h).status_code == 200
    assert client.get("/api/auth/me", headers=biz.h).json()["plan"]["enforced"] is False


def test_free_business_is_refused_with_a_clear_reason(client, biz, gate):
    r = client.get("/api/shops", headers=biz.h)
    assert r.status_code == 402 and "BizAssist Pro" in r.json()["detail"]
    r = client.post("/api/auth/owner/login", json={"username": biz.username, "password": PASSWORD})
    assert r.status_code == 402
    r = client.post("/api/auth/exchange", json={"ticket": _billing_ticket(_owner_claims(biz))})
    assert r.status_code == 402
    assert client.post("/api/auth/owner/login", json={"username": biz.username, "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/logout", headers=biz.h).status_code == 200  # can always sign out
    assert client.post("/api/auth/owner/signup", json={
        "username": "newowner1", "password": PASSWORD, "business_name": "New"}).status_code == 403


def test_pro_business_works_and_staff_follow_the_owners_plan(client, biz, monkeypatch):
    s, h = biz.staff_session("Kiran")  # set up before the gate is on
    _set_plan(biz.business_id, "pro")
    monkeypatch.setattr(config, "REQUIRE_PRO", True)
    assert client.get("/api/shops", headers=biz.h).status_code == 200
    me = client.get("/api/auth/me", headers=biz.h).json()["plan"]
    assert me["plan"] == "pro" and me["enforced"] and not me["warn"]
    assert client.get("/api/my/tasks", headers=h).status_code == 200

    _set_plan(biz.business_id, None)  # the admin revokes Pro: no grace
    r = client.get("/api/my/tasks", headers=h)
    assert r.status_code == 402 and "Ask your owner" in r.json()["detail"]
    login = {"business": biz.public_id, "login_name": s["login_name"], "password": PASSWORD,
             "device_id": "device-aaaa-1111", "device_label": "Test phone"}
    assert client.post("/api/auth/staff/login", json=login).status_code == 402


def test_expired_plan_keeps_working_through_the_grace_period(client, biz, monkeypatch):
    _, h = biz.staff_session()
    monkeypatch.setattr(config, "REQUIRE_PRO", True)
    _set_plan(biz.business_id, "pro", _days_ago(3))
    me = client.get("/api/auth/me", headers=biz.h).json()["plan"]
    assert me["in_grace"] and me["warn"] and me["plan"] == "free"
    assert client.get("/api/my/tasks", headers=h).status_code == 200

    _set_plan(biz.business_id, "pro", _days_ago(config.PRO_GRACE_DAYS + 1))
    assert client.get("/api/shops", headers=biz.h).status_code == 402
    assert client.get("/api/my/tasks", headers=h).status_code == 402

    _set_plan(biz.business_id, "pro", _days_ago(-30))  # renewed: everything is back
    assert client.get("/api/shops", headers=biz.h).status_code == 200
    assert client.get("/api/my/tasks", headers=h).status_code == 200


def test_an_ended_trial_stops_at_once(client, biz, monkeypatch):
    _, h = biz.staff_session()
    monkeypatch.setattr(config, "REQUIRE_PRO", True)
    _set_plan(biz.business_id, "pro", _days_ago(-3), status="trial")  # trial still running
    me = client.get("/api/auth/me", headers=biz.h).json()["plan"]
    assert me["trial"] and me["plan"] == "pro" and me["warn"]
    assert client.get("/api/my/tasks", headers=h).status_code == 200

    _set_plan(biz.business_id, "pro", _days_ago(1), status="trial")  # ended yesterday: no grace
    r = client.get("/api/shops", headers=biz.h)
    assert r.status_code == 402 and "trial has ended" in r.json()["detail"]
    r = client.get("/api/my/tasks", headers=h)
    assert r.status_code == 402 and "Ask your owner" in r.json()["detail"]

    _set_plan(biz.business_id, "pro", _days_ago(1))  # the same date on a PAID plan is in grace
    assert client.get("/api/shops", headers=biz.h).status_code == 200
