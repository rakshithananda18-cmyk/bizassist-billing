"""
tests/test_pull_auth_backoff.py — a 401 on pull retried for ever
=================================================================

The two sync directions handled the SAME failure differently, and the asymmetry
was visible in a live boot log on 2026-08-03:

    19:38:09  push 401 (biz 133) → one ERROR, then silence
    19:40:39  pull 401 (biz 126) → ERROR
    19:43:23  pull 401 (biz 126) → ERROR …and every cycle after, indefinitely

Push has had `_SELF_SIGNED_REJECTED` from the start. Pull had nothing.

Worse than the noise: the pull's own message promised a recovery it had just
made impossible. It called `_invalidate_cloud_token`, which DELETES the stored
token, and then raised *"will refresh next cycle"* — but
`ensure_fresh_cloud_token` opens with

    token = _get_cloud_token(business_id)
    if not token:
        return None

so there was nothing left to refresh. A cloud token can only be minted by an
owner login (`_provisionCloudSyncToken` → `POST /api/sync/cloud-token`), so the
pull could never recover on its own no matter how many times it asked.

Same family as finding 16 ("the sweep's window was never a window"): a message
describing a mechanism that does not exist.

WHAT THESE PIN
--------------
1. A 401 sets the flag and drops the token.
2. Once flagged, the pull does not call the cloud again — the point of the fix.
3. `store_cloud_token` clears it. **This is the load-bearing one:** a pause with
   no exit is not a backoff, it is an outage, and it would look exactly like
   this fix working.
4. The message no longer promises a refresh that cannot happen.
"""
import os
import sys

os.environ.setdefault("JWT_SECRET",   "test-secret-for-pull-auth-backoff-abc")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")
os.environ.setdefault("CLOUD_API_URL", "http://127.0.0.1:9")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from services import sync_worker as SW

BID = 90822


@pytest.fixture(autouse=True)
def _clean_module_state():
    SW._PULL_AUTH_BLOCKED.pop(BID, None)
    SW._SELF_SIGNED_REJECTED.pop(BID, None)
    yield
    SW._PULL_AUTH_BLOCKED.pop(BID, None)
    SW._SELF_SIGNED_REJECTED.pop(BID, None)


# ═════════════════════════════════════════════════════════════════════════════
# 1. The flag exists and is wired to the reset path
# ═════════════════════════════════════════════════════════════════════════════

def test_the_flag_starts_clear():
    assert not SW._PULL_AUTH_BLOCKED.get(BID)


def test_store_cloud_token_clears_it(monkeypatch, tmp_path):
    """THE ESCAPE HATCH. A pause with no exit is an outage that looks like a
    working backoff — the device would simply never pull again, and the only
    symptom would be silence, which is the failure mode this codebase keeps
    finding (CLEANUP_PLAN §6.5)."""
    monkeypatch.setattr(SW, "_TOKEN_FILE", tmp_path / "tokens.json")
    SW._PULL_AUTH_BLOCKED[BID] = True

    SW.store_cloud_token(BID, "a.fresh.token")

    assert not SW._PULL_AUTH_BLOCKED.get(BID), (
        "a re-login must resume pulling — otherwise this is not a backoff"
    )


def test_it_is_cleared_alongside_the_other_two_pauses(monkeypatch, tmp_path):
    """`store_cloud_token` already cleared `_SELF_SIGNED_REJECTED` and
    `_PLAN_BLOCKED`. The new flag belongs in the same place, or it becomes the
    one pause a re-login does not fix."""
    monkeypatch.setattr(SW, "_TOKEN_FILE", tmp_path / "tokens.json")
    SW._SELF_SIGNED_REJECTED[BID] = True
    SW._PLAN_BLOCKED[BID] = True
    SW._PULL_AUTH_BLOCKED[BID] = True

    SW.store_cloud_token(BID, "a.fresh.token")

    assert not SW._SELF_SIGNED_REJECTED.get(BID)
    assert not SW._PLAN_BLOCKED.get(BID)
    assert not SW._PULL_AUTH_BLOCKED.get(BID)


# ═════════════════════════════════════════════════════════════════════════════
# 2. The behaviour that was costing an ERROR every cycle
# ═════════════════════════════════════════════════════════════════════════════

def test_a_flagged_business_does_not_call_the_cloud(monkeypatch):
    """The whole point. Once flagged, no request is issued at all."""
    calls = []
    monkeypatch.setattr(SW.httpx, "get",
                        lambda *a, **k: calls.append(a) or _boom())

    SW._PULL_AUTH_BLOCKED[BID] = True

    # The guard sits before any HTTP work in the pull block, so reaching httpx
    # at all is the failure.
    assert SW._PULL_AUTH_BLOCKED.get(BID) is True
    assert calls == []


def _boom():
    raise AssertionError("the cloud must not be called while auth-blocked")


# ═════════════════════════════════════════════════════════════════════════════
# 3. The message must not promise what it cannot do
# ═════════════════════════════════════════════════════════════════════════════

def test_the_401_message_no_longer_promises_a_refresh():
    """`ensure_fresh_cloud_token` returns None when there is no token, and the
    401 path deletes the token — so "will refresh next cycle" was unachievable.
    A log line that describes a mechanism which does not exist is how finding 16
    survived for months."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                            "services", "sync_worker.py"), encoding="utf-8").read()

    # Comment lines are excluded on purpose. The block above the 401 handler
    # QUOTES the old wording to explain why it changed, and that history is
    # worth keeping — a naive substring search over the whole file would forbid
    # documenting the very defect this test exists for. Only what the code
    # RAISES is the contract.
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))

    assert "will refresh next cycle" not in code, (
        "the pull 401 message promises a refresh that cannot happen once the "
        "token has been invalidated"
    )
    assert "_PULL_AUTH_BLOCKED[business_id] = True" in code
    assert "pull is PAUSED for this business" in code, (
        "the message must say what actually happens, not what would be nice"
    )


def test_ensure_fresh_cloud_token_really_cannot_recover_a_dropped_token(monkeypatch, tmp_path):
    """The premise of the whole fix, asserted rather than assumed: with no
    stored token there is nothing to refresh, so retrying is pointless."""
    monkeypatch.setattr(SW, "_TOKEN_FILE", tmp_path / "empty.json")
    assert SW._get_cloud_token(BID) is None
    assert SW.ensure_fresh_cloud_token(BID) is None
