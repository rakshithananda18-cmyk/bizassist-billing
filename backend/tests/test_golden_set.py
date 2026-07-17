"""
tests/test_golden_set.py — Phase-0 eval golden-set (MASTER_REVIEW §3.2 #3).
===========================================================================
A curated set of real merchant questions with their EXPECTED routing decision
(tier + DIRECT handler), kept in tests/golden_set.jsonl. This is the
regression net that turns "the AI feels worse" into a diff: any change to
services/query_router.py that re-routes one of these questions fails CI with
the exact question and the before/after decision.

Deterministic by design — it exercises classify() only (regex/keyword tiers),
so it needs no API key, no model download, and no network. The semantic
intent tier has its own scored eval in test_intent_router.py; end-to-end tier
behaviour (badges, caching, token counts) lives in test_routing_tiers.py.

Add a case: append one JSON line {"q", "tier", "handler"} to golden_set.jsonl.
Every AI-routing bug that ships should come back as a new line here.
"""
import os
import sys
import json

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from services.query_router import classify

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden_set.jsonl")


def _load_cases():
    cases = []
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            assert {"q", "tier", "handler"} <= set(c), f"golden_set.jsonl line {n}: missing keys"
            cases.append(c)
    return cases


CASES = _load_cases()


def test_golden_set_is_big_enough():
    # The plan calls for 30–50 curated pairs; don't let the net shrink quietly.
    assert len(CASES) >= 30, f"golden set has only {len(CASES)} cases"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["q"][:60])
def test_golden_routing(case):
    tier, handler = classify(case["q"])
    assert (tier, handler) == (case["tier"], case["handler"]), (
        f"\nQuestion:  {case['q']!r}"
        f"\nExpected:  ({case['tier']}, {case['handler']})"
        f"\nGot:       ({tier}, {handler})"
    )
