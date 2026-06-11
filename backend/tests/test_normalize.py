"""
tests/test_normalize.py
=======================
Phase 0 / H3 — ingest normalization. Dates are stored as ISO and the known
invoice statuses get canonical casing, so downstream exact-match checks and
date comparisons are reliable.
"""
import os
import sys

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from services.normalize import to_iso, normalize_status


@pytest.mark.parametrize("raw, expected", [
    ("2026-01-15", "2026-01-15"),   # already ISO
    ("15/01/2026", "2026-01-15"),   # day-first slashed
    ("15-01-2026", "2026-01-15"),   # day-first dashed
    ("01/15/2026", "2026-01-15"),   # US month-first
    ("2026-01-15 00:00:00", "2026-01-15"),  # time stripped
])
def test_to_iso_normalizes_dates(raw, expected):
    assert to_iso(raw) == expected


def test_to_iso_passes_through_unparseable():
    # don't lose data we can't parse
    assert to_iso("not-a-date") == "not-a-date"
    assert to_iso("") == ""
    assert to_iso(None) is None


@pytest.mark.parametrize("raw, expected", [
    ("paid", "Paid"),
    ("PAID", "Paid"),
    ("  overdue ", "Overdue"),
    ("Pending", "Pending"),
    ("disputed", "Disputed"),
])
def test_normalize_status_canonical_casing(raw, expected):
    assert normalize_status(raw) == expected


def test_normalize_status_passes_unknown_through():
    assert normalize_status("Shipped") == "Shipped"   # unknown, unchanged
    assert normalize_status(None) is None
    assert normalize_status("") == ""
