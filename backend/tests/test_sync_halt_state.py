"""
tests/test_sync_halt_state.py
=============================
`GET /api/sync/queue-depth` must say WHY sync is not running.

The worker has four halt states and the endpoint exposed none of them. Callers
had `last_error` — the newest SyncLog row — but every halt short-circuits BEFORE
writing a log, so once one is set no newer row ever appears and the client
replays the error that preceded it forever. That is exactly how a panel showed
"Cloud sync requires the Pro plan" for hours after the plan was already Pro.

`last_error` answers "what went wrong last time we tried".
`halt` answers "are we even trying" — a different question, and the one an owner
is actually asking.
"""
import os
import sys
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient          # noqa: E402
from main_groq import app                           # noqa: E402
import services.sync_worker as sw                   # noqa: E402

client = TestClient(app)

FLAGS = ("_SELF_SIGNED_REJECTED", "_PULL_AUTH_BLOCKED", "_PLAN_BLOCKED", "_OFFLINE_STATE")


@pytest.fixture
def biz():
    """A fresh business, with every halt flag cleared before AND after.

    These are module-level process state; a leaked flag would silently change
    another test's answer.
    """
    uname = f"hs_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Halt Co",
    })
    assert r.status_code == 200, r.text
    acct = r.json()
    bid = acct["user"]["id"] if isinstance(acct.get("user"), dict) else acct["id"]
    auth = {"Authorization": f"Bearer {acct['token']}"}
    for f in FLAGS:
        getattr(sw, f).pop(bid, None)
    try:
        yield bid, auth
    finally:
        for f in FLAGS:
            getattr(sw, f).pop(bid, None)


def _halt(auth):
    r = client.get("/api/sync/queue-depth", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "halt" in body, "queue-depth must always carry a halt object"
    return body["halt"]


def test_a_healthy_business_reports_no_halt(biz):
    _bid, auth = biz
    assert _halt(auth) == {"reason": None, "recoverable_by": None}


@pytest.mark.parametrize("flag,reason,fix", [
    ("_SELF_SIGNED_REJECTED", "secret_mismatch", "relogin"),
    ("_PULL_AUTH_BLOCKED",    "auth_expired",    "relogin"),
    ("_PLAN_BLOCKED",         "plan_required",   "upgrade"),
    ("_OFFLINE_STATE",        "offline",         "wait"),
])
def test_each_halt_state_is_reported_with_its_recovery(biz, flag, reason, fix):
    bid, auth = biz
    getattr(sw, flag)[bid] = True
    assert _halt(auth) == {"reason": reason, "recoverable_by": fix}


def test_a_recovered_outage_is_not_reported(biz):
    """`_OFFLINE_STATE` is set to False when the cloud comes back — it is not
    popped. Testing key PRESENCE instead of truthiness would report an outage
    forever after the first one."""
    bid, auth = biz
    sw._OFFLINE_STATE[bid] = False
    assert _halt(auth)["reason"] is None


def test_the_most_actionable_halt_wins(biz):
    """With several set at once the owner needs the one that will not clear on
    its own. Offline resolves itself; a dead token never does."""
    bid, auth = biz
    sw._OFFLINE_STATE[bid] = True
    sw._PLAN_BLOCKED[bid] = True
    assert _halt(auth)["reason"] == "plan_required"

    sw._PULL_AUTH_BLOCKED[bid] = True
    assert _halt(auth)["reason"] == "auth_expired"

    sw._SELF_SIGNED_REJECTED[bid] = True
    assert _halt(auth)["reason"] == "secret_mismatch"


def test_a_halt_on_one_business_does_not_leak_to_another(biz):
    """The flags are keyed by business id. A blocked business must not make
    every other business on the device look blocked."""
    bid, auth = biz
    sw._PLAN_BLOCKED[bid] = True

    other = client.post("/signup", json={
        "username": f"hs2_{uuid.uuid4().hex[:8]}", "password": "TestPass123!",
        "business_name": "Other Co",
    }).json()
    other_auth = {"Authorization": f"Bearer {other['token']}"}
    try:
        assert _halt(other_auth)["reason"] is None
        assert _halt(auth)["reason"] == "plan_required"
    finally:
        obid = other["user"]["id"] if isinstance(other.get("user"), dict) else other["id"]
        for f in FLAGS:
            getattr(sw, f).pop(obid, None)


def test_halt_is_independent_of_last_error(biz):
    """The whole point: a stale SyncLog must not be mistaken for current state,
    and a current halt must be visible even with no log at all."""
    bid, auth = biz
    r = client.get("/api/sync/queue-depth", headers=auth).json()
    assert r["halt"]["reason"] is None

    sw._PLAN_BLOCKED[bid] = True
    r = client.get("/api/sync/queue-depth", headers=auth).json()
    assert r["halt"]["reason"] == "plan_required"
    # last_error is whatever it was; halt does not read it and is not read from it.
    assert "last_error" in r
