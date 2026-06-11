"""
tests/test_entity_match.py  — H8
================================
Customer-name resolution must tolerate typos, casing, dropped letters and word
order — while never matching unrelated text. Tests the pure `_match_customer_name`
(the DB supplies the candidate names; this only chooses among them).
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from unittest.mock import patch
from services.direct_query_handler import (
    _match_customer_name, _is_general_about_query, handle, CUSTOMER_NOT_FOUND,
    _entity_guess, _match_customer_candidates,
)
from services.ai_router import _maybe_entity_first

NAMES = ["Nilgiris Fresh", "Star Bazaar", "Daily Needs Store", "Amazon"]


def test_exact_substring_match():
    assert _match_customer_name("do you know nilgiris fresh?", NAMES) == "Nilgiris Fresh"


def test_case_insensitive():
    assert _match_customer_name("info on NILGIRIS FRESH please", NAMES) == "Nilgiris Fresh"


@pytest.mark.parametrize("query, expected", [
    ("tell me about nilgris fresh",  "Nilgiris Fresh"),   # typo (missing i)
    ("what about nilgiri fresh",     "Nilgiris Fresh"),   # dropped trailing s
    ("how is star bazar doing",      "Star Bazaar"),      # typo (missing a)
    ("do you know amzon",            "Amazon"),           # single-token typo
])
def test_fuzzy_typos_and_dropped_letters(query, expected):
    assert _match_customer_name(query, NAMES) == expected


def test_word_order_independent():
    assert _match_customer_name("fresh nilgiris status", NAMES) == "Nilgiris Fresh"


@pytest.mark.parametrize("query", [
    "show me apples and oranges",       # nothing close
    "the star performers of the week",  # 'star' alone must NOT match 'Star Bazaar'
    "",                                 # empty
])
def test_no_false_positive(query):
    assert _match_customer_name(query, NAMES) is None


def test_empty_name_list():
    assert _match_customer_name("nilgiris fresh", []) is None


def test_substring_prefers_longest():
    names = ["Star", "Star Bazaar"]
    assert _match_customer_name("orders for star bazaar", names) == "Star Bazaar"


# ── entity-first routing (the bare "namdhari fresh" case) ──────────────────

@patch("services.ai_router._extract_customer_name")
def test_bare_customer_name_reroutes_to_client_summary(mock_extract):
    # the regex router dumps "namdhari fresh" into AI_SIMPLE; entity-first must
    # catch the named customer and reroute to client_summary (not 'fresh'→expiring).
    mock_extract.return_value = "Namdhari Fresh"
    assert _maybe_entity_first("AI_SIMPLE", None, "namdhari fresh", 1) == ("DIRECT", "client_summary")


@patch("services.ai_router._extract_customer_name")
def test_short_non_name_query_is_left_alone(mock_extract):
    mock_extract.return_value = None   # no customer matched
    assert _maybe_entity_first("AI_SIMPLE", None, "best payment terms", 1) == ("AI_SIMPLE", None)


@patch("services.ai_router._extract_customer_name")
def test_long_query_skips_entity_check(mock_extract):
    # too long to be a bare name → don't even hit the DB
    out = _maybe_entity_first("AI_SIMPLE", None, "tell me everything about namdhari fresh right now please", 1)
    assert out == ("AI_SIMPLE", None)
    mock_extract.assert_not_called()


@patch("services.ai_router._extract_customer_name")
def test_lookup_phrase_with_typo_still_reroutes(mock_extract):
    # 'do yo know Rahul traders' is 5 words (over the old 4 cap) with a typo — it
    # used to fall through to AI_SIMPLE and serve a cached generic business summary.
    mock_extract.return_value = "Rahul Traders"
    assert _maybe_entity_first("AI_SIMPLE", None, "do yo know Rahul traders", 1) == ("DIRECT", "client_summary")


@patch("services.ai_router._extract_customer_name")
def test_analytical_keyword_blocks_entity_first(mock_extract):
    # a name inside an analytical question must NOT be hijacked to client_summary
    out = _maybe_entity_first("AI_SIMPLE", None, "show overdue for star bazaar", 1)
    assert out == ("AI_SIMPLE", None)
    mock_extract.assert_not_called()


@patch("services.ai_router._extract_customer_name")
def test_non_ai_simple_routes_untouched(mock_extract):
    out = _maybe_entity_first("DIRECT", "overdue_list", "show overdue", 1)
    assert out == ("DIRECT", "overdue_list")
    mock_extract.assert_not_called()


# ── unknown-customer handling (the "Zxqwerty Fictional" hallucination) ─────

def test_general_about_query_is_recognised():
    assert _is_general_about_query("tell me about my business") is True
    assert _is_general_about_query("what's the status of my overdue invoices") is True


def test_named_unknown_customer_is_not_general():
    assert _is_general_about_query("tell me about Zxqwerty Fictional") is False
    assert _is_general_about_query("do you know Acme Traders") is False


@patch("services.direct_query_handler._extract_customer_name", return_value=None)
def test_unknown_customer_returns_not_found_not_none(_mock):
    # named customer that doesn't resolve -> honest message (so ai_router won't
    # fall through to the LLM and fabricate an empty client card).
    out = handle("client_summary", "tell me about Zxqwerty Fictional", 1)
    assert out == CUSTOMER_NOT_FOUND


@patch("services.direct_query_handler._extract_customer_name", return_value=None)
def test_general_about_query_falls_through_to_ai(_mock):
    # general business ask sharing the 'tell me about' phrasing -> None so the
    # AI tier answers with an overview.
    out = handle("client_summary", "tell me about my business performance", 1)
    assert out is None


# ── "did you mean" near-match candidates ──────────────────────────────────

_CAND_NAMES = ["Namdhari Fresh", "Nilgiris Fresh", "Star Bazaar", "Rahul Traders"]


def test_entity_guess_strips_lookup_filler():
    assert _entity_guess("do you know rahul traders") == "rahul traders"
    assert _entity_guess("tell me about Star Bazaar") == "star bazaar"


def test_near_miss_returns_candidate():
    # a typo'd name below the confident threshold should still surface as a
    # "did you mean" suggestion.
    cands = _match_customer_candidates("do you know namdari fresh", _CAND_NAMES)
    assert "Namdhari Fresh" in cands
    assert len(cands) <= 3


def test_no_close_name_returns_no_candidates():
    assert _match_customer_candidates("do you know zxqwerty", _CAND_NAMES) == []


def test_candidates_are_ranked_best_first():
    # 'star' is closest to 'Star Bazaar'
    cands = _match_customer_candidates("do you know star", _CAND_NAMES)
    assert cands and cands[0] == "Star Bazaar"
