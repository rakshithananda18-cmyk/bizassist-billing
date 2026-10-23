"""
app/plan.py — Field Team is part of BizAssist Pro.

Same entitlement rule as billing (`services/admin_service.effective_plan` and
`expiry_moment`, checked against billing's own code in
tests/test_billing_contract.py):

  * the plan lives in the OWNER's `users.settings` JSON under `subscription`,
    written only by billing's admin console; staff inherit the owner's plan;
  * plan "pro" counts until `expires_at`; a bare date means through the END of
    that day; no `expires_at` = no end;
  * the gate only bites where SUBSCRIPTION_ENFORCED=1 (billing's cloud image
    sets it; config.REQUIRE_PRO here).

Field Team adds one thing: a grace period (config.PRO_GRACE_DAYS, default 7)
after a plan EXPIRES, so a delivery day is not cut off mid-route while the
renewal is processed; the owner is warned throughout. A plan the admin
REVOKES (no subscription left) has no grace.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from app import config
from app.billing_models import BillingUser
from app.db import utc_now
from app.timeutil import iso_utc

logger = logging.getLogger("bizassist.task.auth")

# Warn the owner this many days before the plan ends.
WARN_DAYS = 7


def expiry_moment(raw) -> Optional[datetime]:
    """The instant a subscription lapses, as naive UTC; None if absent or
    unparseable. Copy of billing's `services.admin_service.expiry_moment`."""
    if raw in (None, ""):
        return None
    s = str(raw).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    if "T" not in s and " " not in s:
        dt = dt + timedelta(days=1)
    return dt


def _subscription(owner: Optional[BillingUser]) -> dict:
    try:
        s = json.loads(owner.settings or "{}") if owner is not None else {}
    except (TypeError, ValueError):
        return {}
    sub = s.get("subscription") if isinstance(s, dict) else None
    return sub if isinstance(sub, dict) else {}


@dataclass
class PlanState:
    plan: str  # billing's effective plan: "pro" | "free"
    ends_at: Optional[datetime]  # when billing stops counting it as Pro
    grace_until: Optional[datetime]  # when Field Team stops (ends_at + grace)
    allowed: bool

    @property
    def in_grace(self) -> bool:
        return self.allowed and self.plan != "pro"


def plan_state(owner: Optional[BillingUser], now: Optional[datetime] = None) -> PlanState:
    now = now or utc_now()
    sub = _subscription(owner)
    if (sub.get("plan") or "free").lower() != "pro":
        return PlanState("free", None, None, allowed=False)
    ends = expiry_moment(sub.get("expires_at"))
    if ends is None or ends > now:
        return PlanState("pro", ends, None, allowed=True)
    grace = ends + timedelta(days=config.PRO_GRACE_DAYS)
    return PlanState("free", ends, grace, allowed=now < grace)


def plan_out(state: PlanState, now: Optional[datetime] = None) -> dict:
    """What the owner's screens show: the plan, and a warning when it ends soon
    or is running on the grace period."""
    now = now or utc_now()
    stop = state.grace_until or state.ends_at
    return {
        "enforced": config.REQUIRE_PRO,
        "plan": state.plan,
        "ends_at": iso_utc(state.ends_at),
        "grace_until": iso_utc(state.grace_until),
        "in_grace": state.in_grace,
        "warn": bool(config.REQUIRE_PRO and stop is not None and state.allowed
                     and (state.in_grace or stop - now <= timedelta(days=WARN_DAYS))),
    }


def ensure_pro(owner: Optional[BillingUser], kind: str) -> None:
    """402, like billing's `require_plan`, when the gate is on and the
    business is past its plan (and grace)."""
    if not config.REQUIRE_PRO or plan_state(owner).allowed:
        return
    logger.info("[AUTH] refused %s: biz=%s is not on Pro", kind, owner.id if owner is not None else "?")
    if kind == "staff":
        raise HTTPException(status_code=402, detail="Field Team is not active for this business. Ask your owner to renew BizAssist Pro.")
    raise HTTPException(status_code=402, detail="Field Team is part of BizAssist Pro. Upgrade or renew the plan in BizAssist Billing, then sign in again.")
