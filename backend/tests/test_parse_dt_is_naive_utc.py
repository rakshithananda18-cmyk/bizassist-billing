"""
tests/test_parse_dt_is_naive_utc.py — the timestamp boundary
============================================================

`core.sync.apply_hooks.parse_dt` is where foreign timestamps enter the app. On
2026-08-01 it returned AWARE datetimes for cloud values carrying an offset and
NAIVE ones for local ORM values, and the two met in the pull path's
last-write-wins comparison:

    [SYNC_INBOX] biz=7 invoices uid='49f60411-4e7b-4e3b-b91b-786e486d9c08'
    still not appliable (attempt 1/7):
    can't compare offset-naive and offset-aware datetimes

That was LCL-OW-0037's own invoice row — stuck in the inbox behind the repair it
was waiting for, and roughly six hours from exhausting MAX_AUTO_ATTEMPTS and
being abandoned.

The app-wide convention (documented on `services/dates.utc_now`) is naive UTC,
so the aware value is the intruder and the boundary is where it gets normalised.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.sync.apply_hooks import parse_dt  # noqa: E402


@pytest.mark.parametrize("value", [
    "2026-07-30T11:43:09.747771+00:00",
    "2026-07-30T11:43:09.747771Z",
    "2026-07-30T17:13:09.747771+05:30",     # same instant, IST
    datetime(2026, 7, 30, 11, 43, 9, 747771, tzinfo=timezone.utc),
])
def test_every_aware_form_comes_back_naive(value):
    got = parse_dt(value)
    assert got is not None
    assert got.tzinfo is None, f"{value!r} still carries tzinfo"


def test_the_instant_is_preserved_not_just_the_tzinfo_dropped():
    """The dangerous wrong fix is `.replace(tzinfo=None)` with no conversion,
    which keeps the wall-clock reading and moves the instant. In IST that is
    5½ hours of drift applied to money records."""
    utc = parse_dt("2026-07-30T11:43:09+00:00")
    ist = parse_dt("2026-07-30T17:13:09+05:30")     # the same moment
    assert utc == ist


def test_naive_input_is_untouched():
    naive = datetime(2026, 7, 30, 11, 43, 9)
    assert parse_dt(naive) == naive
    assert parse_dt(naive).tzinfo is None


def test_the_comparison_that_was_failing_now_works():
    """The exact shape of the pull path's LWW check: a cloud timestamp from the
    wire against a local one from SQLite."""
    cloud = parse_dt("2026-08-01T07:38:07.123456Z")          # from the wire
    local = parse_dt(datetime(2026, 7, 31, 18, 58, 56))      # from SQLite
    assert local < cloud            # would raise TypeError before the fix


def test_it_also_compares_against_the_epoch_sentinel():
    """`routes/sync.py:855` does `_parse_dt(last_sync_at) or datetime(1970,1,1)`
    and then compares — a naive sentinel, so an aware parse breaks the cloud's
    pull endpoint the same way it broke the desktop's apply."""
    assert parse_dt("2026-08-01T07:38:07Z") > datetime(1970, 1, 1)


def test_unparseable_and_empty_are_unchanged():
    assert parse_dt("") is None
    assert parse_dt(None) is None
    assert parse_dt("not a timestamp") is None


def test_a_dst_free_offset_still_round_trips():
    """India has no DST, but the guard must not depend on that."""
    v = parse_dt("2026-01-15T09:00:00-05:00")
    assert v == datetime(2026, 1, 15, 14, 0, 0)


def test_the_regression_is_actually_reachable_through_the_worker_helper():
    """Asserted through `sync_worker._parse_dt` too, since that is the call site
    the incident came from and it is a separate thin wrapper."""
    from services.sync_worker import _parse_dt as worker_parse
    assert worker_parse("2026-08-01T07:38:07Z").tzinfo is None
    assert worker_parse(datetime(2026, 7, 31, 18, 58, 56)) < worker_parse(
        "2026-08-01T07:38:07Z")


def test_clock_skew_guard_still_fires_on_a_future_cloud_row():
    """The skew guard compares against an AWARE `datetime.now(timezone.utc)` and
    re-adds tzinfo itself. Normalising at the boundary must not disarm it."""
    from services.sync_worker import _parse_dt as worker_parse
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    got = worker_parse(future.isoformat())
    assert got.tzinfo is None
    assert got.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) + \
        timedelta(minutes=5)
