"""
services/action_rails.py — Phase-0 write-tool safety rails (MASTER_REVIEW §3.2 #4).
===================================================================================
Every gated, side-effecting action gets three rails, whether a human clicked
the confirm modal or (later) an agent scheduled the write:

  1. CONFIRM TOKEN — /action/preview mints a stateless HMAC token binding
     (business, action, EXACT params, expiry). /action/execute refuses any
     request whose token doesn't verify, so nothing can execute that wasn't
     previewed verbatim — a tampered/ stale/ cross-user confirm is dead on
     arrival. Stateless (keyed on JWT_SECRET) → survives restarts, needs no
     table, works on the single-worker HF tier and beyond.
  2. IDEMPOTENCY — /action/execute honours `X-Client-Request-Id` via the
     existing ReplayGuard wall (core/sync/idempotency.py) — the same wall
     sales/payments already use. A double-clicked confirm or a retried
     request replays the stored response instead of re-sending reminders.
  3. DAILY CAPS — a per-business, per-action daily cap enforced in the
     dispatcher (services/actions.py), counting today's ActionLog rows.
     A runaway agent (or a stuck client loop) cannot spam customers.
     Override per action:  ACTION_DAILY_CAP_<ACTION_KEY_UPPER>=N
     Global default:       ACTION_DAILY_CAP_DEFAULT (500)

Token format:  "<exp_unix>.<hmac_sha256_hex>"
Signed string: "<business_id>|<action>|<sha256(canonical_params)>|<exp_unix>"
TTL default:   ACTION_CONFIRM_TTL_SECS (600s — a confirm modal older than
               10 minutes must be re-previewed; the world may have changed).

Enforcement is ON by default; `ACTION_CONFIRM_REQUIRED=0` is an emergency
escape hatch for a mixed-version fleet during rollout.
"""
import os
import json
import hmac
import time
import hashlib
import logging
from services.dates import utc_now

logger = logging.getLogger("bizassist.action_rails")

CONFIRM_TTL_SECS = int(os.getenv("ACTION_CONFIRM_TTL_SECS", "600"))


def _secret() -> bytes:
    # Reuse the app's JWT secret — one secret to rotate, already required at boot.
    from services.auth import JWT_SECRET
    return JWT_SECRET.encode("utf-8") if isinstance(JWT_SECRET, str) else JWT_SECRET


def _canon_params(params: dict) -> str:
    """Canonical JSON for the params dict — key order and whitespace stable,
    so the same logical params always hash identically."""
    return json.dumps(params or {}, sort_keys=True, separators=(",", ":"), default=str)


def _signed_payload(business_id: int, action: str, params: dict, exp: int,
                    state_fp: str = None) -> bytes:
    # state_fp binds the token to the PREVIEW'S COMPUTED CONTENT (the exact items
    # the user saw), not just the request params. If the underlying data shifts
    # between preview and execute (an invoice gets paid, stock moves), the
    # recomputed fingerprint differs and the token no longer verifies — execute
    # refuses instead of acting on data the user never confirmed. Empty string
    # for legacy callers that don't bind state (unchanged behaviour).
    params_hash = hashlib.sha256(_canon_params(params).encode("utf-8")).hexdigest()
    return f"{business_id}|{action}|{params_hash}|{state_fp or ''}|{exp}".encode("utf-8")


def mint_confirm_token(business_id: int, action: str, params: dict = None,
                       ttl_secs: int = None, state_fp: str = None) -> str:
    """Called by /action/preview: bind this preview to (user, action, params)
    and — when given — the preview's content fingerprint `state_fp`."""
    exp = int(time.time()) + (ttl_secs if ttl_secs is not None else CONFIRM_TTL_SECS)
    sig = hmac.new(_secret(), _signed_payload(business_id, action, params, exp, state_fp),
                   hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_confirm_token(token: str, business_id: int, action: str,
                         params: dict = None, state_fp: str = None):
    """Returns (ok: bool, reason: str). Constant-time compare on the HMAC.
    `state_fp` must match the value bound at mint time; a differing fingerprint
    (state changed since preview) yields reason='stale'."""
    if not token or "." not in (token or ""):
        return False, "missing"
    exp_part, _, sig = token.partition(".")
    try:
        exp = int(exp_part)
    except ValueError:
        return False, "malformed"
    if exp < int(time.time()):
        return False, "expired"
    expected = hmac.new(_secret(), _signed_payload(business_id, action, params, exp, state_fp),
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        # Fails for a forged/expired-params token OR because state_fp differs
        # from mint time (the previewed data changed). Both resolve the same way:
        # re-preview and confirm. Kept indistinguishable on purpose — the token
        # carries only the HMAC, never the fingerprint, so it can't leak state.
        return False, "mismatch"
    return True, "ok"


def confirm_required() -> bool:
    return os.getenv("ACTION_CONFIRM_REQUIRED", "1") == "1"


# ── Daily caps ───────────────────────────────────────────────────────────────

# Per-action defaults: generous for human use, tight where an action fans out
# to third parties (emails to customers) or is meant to run once a day.
_DEFAULT_CAPS = {
    "send_payment_reminders": 300,   # ActionLog rows = customer touches/day
    "escalate_overdue":       200,
    "mark_invoice_paid":      500,
    "email_reminder_digest":  5,     # owner digest — a few sends a day is plenty
    "draft_reorder_po":       200,
}


def daily_cap(action_key: str) -> int:
    env_key = f"ACTION_DAILY_CAP_{action_key.upper()}"
    raw = os.getenv(env_key)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            logger.warning("[RAILS] bad %s=%r — using default", env_key, raw)
    if action_key in _DEFAULT_CAPS:
        return _DEFAULT_CAPS[action_key]
    try:
        return int(os.getenv("ACTION_DAILY_CAP_DEFAULT", "500"))
    except ValueError:
        return 500


def used_today(db, business_id: int, action_key: str) -> int:
    """Today's ActionLog rows for this business+action (UTC day, matching the
    once-a-day idempotency helper in services/actions.py)."""
    from datetime import datetime
    from database.models import ActionLog
    start = datetime.combine(utc_now().date(), datetime.min.time())
    return (db.query(ActionLog)
              .filter(ActionLog.business_id == business_id,
                      ActionLog.action == action_key,
                      ActionLog.created_at >= start)
              .count())


def check_daily_cap(db, business_id: int, action_key: str):
    """Returns (allowed: bool, used: int, cap: int)."""
    cap = daily_cap(action_key)
    used = used_today(db, business_id, action_key)
    return used < cap, used, cap
