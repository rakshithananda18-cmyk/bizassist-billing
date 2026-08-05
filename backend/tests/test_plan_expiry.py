"""
tests/test_plan_expiry.py
=========================
`effective_plan` decides whether a paying business still has access, and its
expiry parse carried two defects — duplicated verbatim in the admin console's
"expiring within 14 days" metric, so the warning and the enforcement could
disagree by a day.

  1. A DATE cut access at the START of the stated day. `expires_at` is a string
     documented as "ISO date", so an admin types `2026-09-01`; that parsed to
     midnight, and a customer paid through 1 September was on the free plan for
     the whole of 1 September. Granting "expires today" gave zero access.

  2. `.replace(tzinfo=None)` DISCARDED an offset instead of converting it, so
     `2026-09-01T00:00:00+05:30` was compared as though it were 00:00 UTC — up
     to 14 hours of error either way.

Decision recorded here: a date-only value means access THROUGH the end of that
day. An explicit timestamp is honoured exactly as written.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

from services.admin_service import effective_plan, expiry_moment  # noqa: E402
from services.dates import utc_now                                 # noqa: E402


class _U:
    """Minimal stand-in — effective_plan only reads `.settings`."""
    def __init__(self, sub):
        self.settings = json.dumps({"subscription": sub} if sub else {})


def _pro(expires_at):
    return _U({"plan": "pro", "status": "active", "expires_at": expires_at})


# ── the date-only ruling ─────────────────────────────────────────────────────

def test_a_date_grants_access_through_the_end_of_that_day():
    today = utc_now().date().isoformat()
    assert effective_plan(_pro(today)) == "pro", (
        f"expires_at={today} left the customer with no access on the very day "
        "they paid through"
    )


def test_yesterday_has_lapsed():
    yesterday = (utc_now().date() - timedelta(days=1)).isoformat()
    assert effective_plan(_pro(yesterday)) == "free"


def test_a_future_date_is_still_pro():
    future = (utc_now().date() + timedelta(days=30)).isoformat()
    assert effective_plan(_pro(future)) == "pro"


# ── timezone handling ────────────────────────────────────────────────────────

def test_an_offset_is_converted_not_discarded():
    """00:30 at +05:30 is 19:00 UTC the PREVIOUS day. Discarding the offset
    would read it as 00:30 UTC — 5.5 hours late."""
    moment = expiry_moment("2026-09-01T00:30:00+05:30")
    assert moment == datetime(2026, 8, 31, 19, 0, 0), moment


def test_utc_and_offset_forms_of_the_same_instant_agree():
    a = expiry_moment("2026-09-01T00:30:00+05:30")
    b = expiry_moment("2026-08-31T19:00:00Z")
    assert a == b, f"same instant parsed differently: {a} vs {b}"


def test_an_explicit_timestamp_is_taken_literally():
    """Only a bare DATE gets extended to end-of-day; a timestamp means what it
    says, so no silent day is added."""
    assert expiry_moment("2026-09-01T00:00:00") == datetime(2026, 9, 1, 0, 0, 0)


# ── the shape that must not regress ──────────────────────────────────────────

def test_no_expiry_stays_pro_forever():
    """The live production grant: {'plan': 'pro', 'expires_at': None}."""
    assert effective_plan(_pro(None)) == "pro"


def test_unparseable_expiry_does_not_revoke_access():
    """Garbage in the field must not silently downgrade a paying customer —
    failing closed here bills someone for a plan they cannot use."""
    assert effective_plan(_pro("not-a-date")) == "pro"
    assert expiry_moment("not-a-date") is None


def test_free_is_free_regardless():
    assert effective_plan(_U({"plan": "free"})) == "free"
    assert effective_plan(_U(None)) == "free"
