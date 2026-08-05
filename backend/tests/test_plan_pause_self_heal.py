"""
tests/test_plan_pause_self_heal.py
==================================
A cloud 402 sets `_PLAN_BLOCKED[business_id]`, and the sync worker then returns
early every cycle so it stops pushing data the cloud will reject. Correct.

The flag was cleared ONLY by `store_cloud_token`, i.e. by an owner re-login. But
a plan becomes Pro without any new token — `_sync_subscription_from_cloud` pulls
the subscription down on an ordinary `/settings` read — so an upgraded business
stayed paused indefinitely: the app displayed "Current plan: Pro", the outbox
climbed, and the panel showed a stale "Cloud sync requires the Pro plan" from
the refusal that set the flag hours earlier.

The pause must therefore be re-evaluated against the plan actually held, not
left waiting for a login that may never come.
"""
import json
import os
import sys
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient      # noqa: E402
from main_groq import app                       # noqa: E402
from database.db import SessionLocal            # noqa: E402
from database.models import User                # noqa: E402
import services.sync_worker as sw               # noqa: E402

client = TestClient(app)


def _owner(plan: str):
    uname = f"pp_{uuid.uuid4().hex[:8]}"
    r = client.post("/signup", json={
        "username": uname, "password": "TestPass123!", "business_name": "Plan Pause Co",
    })
    assert r.status_code == 200, r.text
    acct = r.json()
    bid = acct["user"]["id"] if isinstance(acct.get("user"), dict) else acct["id"]

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == bid).first()
        settings = {"general": {"hosting_mode": "hybrid"}}
        if plan == "pro":
            settings["subscription"] = {"plan": "pro", "status": "active", "expires_at": None}
        u.settings = json.dumps(settings)
        db.commit()
        db.refresh(u)
        return db, u, bid
    except Exception:
        db.close()
        raise


def test_pause_lifts_once_the_plan_is_pro():
    db, user, bid = _owner("pro")
    try:
        sw._PLAN_BLOCKED[bid] = True          # as a cloud 402 would have left it
        sw._sync_business_impl(db, user, force=True)
        assert not sw._PLAN_BLOCKED.get(bid), (
            "the business is on Pro but sync stayed paused — it would sit here "
            "until an owner re-login that nothing prompts them to do"
        )
    finally:
        sw._PLAN_BLOCKED.pop(bid, None)
        db.close()


def test_pause_holds_while_the_plan_is_still_free():
    """The pause exists for a reason: without it every cycle pushes data the
    cloud will refuse. A free business must stay parked."""
    db, user, bid = _owner("free")
    try:
        sw._PLAN_BLOCKED[bid] = True
        sw._sync_business_impl(db, user, force=True)
        assert sw._PLAN_BLOCKED.get(bid) is True, (
            "cleared the pause for a business that is still on the free plan"
        )
    finally:
        sw._PLAN_BLOCKED.pop(bid, None)
        db.close()
