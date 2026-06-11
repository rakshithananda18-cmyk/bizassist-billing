"""
tests/test_entity_match.py  — H8
================================
Customer-name resolution must tolerate typos, casing, dropped letters and word
order — while never matching unrelated text. Tests the pure `_match_customer_name`
(the DB supplies the candidate names; this only chooses among them).
"""
import os
import sys

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from services.direct_query_handler import _match_customer_name

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
