"""
tests/test_dates.py
===================
Phase 0 / H3 — the single shared date parser. Pins the format coverage and the
null/garbage behaviour so the scattered strptime loops can all delegate to it.
"""
import os
import sys
from datetime import datetime, date

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from services.dates import parse_date, parse_date_only


@pytest.mark.parametrize("raw, expected", [
    ("2026-01-15", datetime(2026, 1, 15)),   # ISO
    ("15-01-2026", datetime(2026, 1, 15)),   # day-first dashed
    ("15/01/2026", datetime(2026, 1, 15)),   # day-first slashed
    ("01/15/2026", datetime(2026, 1, 15)),   # US month-first
    ("2026/01/15", datetime(2026, 1, 15)),   # slashed ISO
])
def test_parses_known_formats(raw, expected):
    assert parse_date(raw) == expected


def test_strips_time_component():
    assert parse_date("2026-01-15 13:45:00") == datetime(2026, 1, 15)
    assert parse_date("2026-01-15T13:45:00") == datetime(2026, 1, 15)


@pytest.mark.parametrize("bad", [None, "", "   ", "not-a-date", "2026-13-99", "garbage"])
def test_unparseable_returns_none(bad):
    assert parse_date(bad) is None


def test_parse_date_only_returns_date():
    assert parse_date_only("2026-01-15") == date(2026, 1, 15)
    assert parse_date_only(None) is None


def test_returns_datetime_for_arithmetic():
    d = parse_date("2026-01-15")
    assert isinstance(d, datetime)
    # callers rely on date arithmetic working
    assert (parse_date("2026-01-20") - d).days == 5
