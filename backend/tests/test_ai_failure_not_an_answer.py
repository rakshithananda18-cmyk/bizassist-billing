"""
tests/test_ai_failure_not_an_answer.py
======================================
A failure is not an answer, and must never be cached as one.

Measured on the live logs before this fix — `[DONE] source=ai` turns:

    fresh, real answer (tokens>0) .............. 154
    fresh, generated NOTHING (tokens=0) ........ 161   ← 51% of fresh turns
    cache re-serves (tokens=0, cached=True) ....  66

and the sequence that produced them, two seconds apart:

    [AGENT-LOOP] run failed: 401 Invalid API Key
    [DONE] router=legacy source=ai tier=AI_COMPLEX tokens=0 cached=False
    [CACHE] HIT source=ai disc='q:what should i focus on t…'
    [DONE] router=legacy source=ai tier=AI_COMPLEX tokens=0 cached=True

`agent_loop` turned every exception into the reply text, so `ai_router` saw a
successful turn, cached it for CACHE_TTL (600 s) and wrote it into the owner's
chat history. One rejected API key became ten minutes of confident wrong
answers, and the message it showed — "please try again" — described the one
action that could not work, because the retry was served from cache without
reaching the model.

The distinction being pinned: a QUOTA stop is a true statement about the
business's budget and stays an answer; anything else is an error and must
travel as one.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest                                          # noqa: E402
from services import agent_loop                        # noqa: E402


class _Boom(Exception):
    """Stand-in for groq.AuthenticationError — matched on message, as the
    production code does (it never imports the groq exception classes)."""


def test_a_rejected_key_is_not_classified_as_quota():
    e = _Boom("Error code: 401 - {'error': {'message': 'Invalid API Key', "
              "'code': 'invalid_api_key'}}")
    assert agent_loop._is_quota(e) is False


def test_a_spent_budget_is_classified_as_quota():
    # Both shapes seen in the live logs.
    assert agent_loop._is_quota(_Boom("429 tokens per day (TPD) rate_limit_exceeded"))
    assert agent_loop._is_quota(_Boom("rate_limit_exceeded"))


def test_a_rejected_key_propagates_instead_of_becoming_the_answer(monkeypatch):
    """The core regression. Before: this returned {'text': '*The advisor hit an
    error — please try again.*'} and the caller cached it."""
    def _explode(*a, **k):
        raise _Boom("Error code: 401 - Invalid API Key")

    # Fail at the first model call inside the loop.
    monkeypatch.setattr(agent_loop, "_client", type("C", (), {
        "chat": type("Ch", (), {
            "completions": type("Co", (), {"create": staticmethod(_explode)})()
        })()
    })())

    with pytest.raises(Exception) as excinfo:
        agent_loop.run_agent_loop("what should i focus on", 1, [])
    assert "401" in str(excinfo.value) or "Invalid API Key" in str(excinfo.value)


def test_a_spent_budget_still_answers(monkeypatch):
    """The guard must not swallow the case it was built to preserve. A quota
    stop is real information for the owner and stays a normal reply."""
    def _explode(*a, **k):
        raise _Boom("429 tokens per day (TPD) rate_limit_exceeded")

    monkeypatch.setattr(agent_loop, "_client", type("C", (), {
        "chat": type("Ch", (), {
            "completions": type("Co", (), {"create": staticmethod(_explode)})()
        })()
    })())

    out = agent_loop.run_agent_loop("what should i focus on", 1, [])
    assert "daily AI analysis limit" in out["text"]


def test_the_quota_message_never_tells_the_owner_to_retry():
    """'Please try again' was the old catch-all, and it was advice that could
    not work — the retry was served from cache. The quota text explains the
    state instead of prescribing a useless action."""
    text = agent_loop._friendly_error(_Boom("429 tokens per day"))
    assert "try again" not in text.lower()
    assert "limit" in text.lower()
