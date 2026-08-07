"""
tests/planhelpers.py — provision a plan for a test account.

WHY THIS EXISTS
---------------
`/ask` and `/ask/stream` are Pro-only and, since `force_enforcement=True`
(routes/ask.py), actually refuse. Before that the dependency was declared but
inert — it only bit when SUBSCRIPTION_ENFORCED=1, which is unset in production
and in the suite — so every AI test passed on a freshly signed-up FREE account
without anyone noticing the endpoints were open to all plans.

A suite that exercises the ROUTER now has to provision a plan first. That is
ordinary setup, not a workaround: the tests were relying on a paywall that did
not work, and making the dependency explicit is the point of enforcing it.

Kept as a plain module rather than a fixture because the callers are
module-scoped fixtures, and a function-scoped fixture cannot be consumed by one.
"""
import json


def grant_pro(username: str) -> None:
    """Give `username`'s account an active Pro plan.

    Writes the same shape `services.admin_service.effective_plan` reads
    (`settings.subscription.plan`), with no `expires_at` — an expired Pro is
    downgraded to free by that function, which is its own test elsewhere.
    """
    from database.db import SessionLocal
    from database.models import User

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username).first()
        if u is None:
            raise AssertionError(f"grant_pro: no account named {username!r}")
        s = json.loads(u.settings) if u.settings else {}
        s["subscription"] = {"plan": "pro", "status": "active"}
        u.settings = json.dumps(s)
        db.commit()
    finally:
        db.close()
