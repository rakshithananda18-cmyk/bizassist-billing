"""
tests/test_session_title.py
===========================
A conversation's title is the first SUBSTANTIVE message, not a greeting — so a
chat opened with "hi" isn't permanently titled "hi" (which made every session
indistinguishable in the sidebar).
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from services.ai_router import _is_titleable, _title_from


@pytest.mark.parametrize("greeting", [
    "hi", "Hi", "hii", "hiii", "hey", "heyy", "hello", "Hello!", "hiya", "yo",
    "hola", "sup", "thanks", "Thanks!", "thank you", "thankyou", "thx", "ty",
    "ok", "okay", "cool", "good morning", "Good Evening", "greetings", "  hi  ", "",
])
def test_greetings_are_not_titleable(greeting):
    assert _is_titleable(greeting) is False


@pytest.mark.parametrize("real", [
    "how many invoices do I have",
    "namdhari fresh",
    "show overdue invoices",
    "who owes me the most",
    "draft a payment reminder",
    "do you know srinivas kirana",
])
def test_substantive_messages_are_titleable(real):
    assert _is_titleable(real) is True


def test_title_is_truncated_at_40_chars():
    short = "how many invoices"
    assert _title_from(short) == short

    long = "give me a complete breakdown of every overdue invoice by customer and date"
    out = _title_from(long)
    assert out.endswith("...")
    assert len(out) == 43  # 40 chars + "..."
