"""
tests/test_writing_router.py
============================
The writing-task detector must catch drafting requests so they go to the AI
writing path — NOT get promoted to a data handler. Regression for "draft a
polite follow-up to this customer", which returned the raw overdue list because
'follow-up' wasn't a recognised noun.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from services.query_router import _WRITING_ACTIONS


@pytest.mark.parametrize("q", [
    "Draft a polite, professional follow-up to this customer about their outstanding invoices",
    "draft a payment reminder for my overdue customers",
    "write a follow up message",
    "compose an email to a client",
    "send a whatsapp reminder",
    "reply to this customer's message",
    "prepare a statement for this account",
])
def test_writing_tasks_are_detected(q):
    assert _WRITING_ACTIONS.search(q) is not None


@pytest.mark.parametrize("q", [
    "show overdue invoices",
    "total revenue",
    "who owes me the most",
    "how many invoices do I have",
    "tell me about Rahul Traders",
])
def test_data_and_lookup_queries_are_not_writing(q):
    assert _WRITING_ACTIONS.search(q) is None
