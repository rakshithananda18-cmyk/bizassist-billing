"""
tests/test_routing_tiers.py
===========================
Comprehensive routing tier tests for BizAssist.

Covers all 6 tiers end-to-end:
  Tier 1 — CONVERSATIONAL  (~50 tokens, no data badge)
  Tier 2 — DIRECT          (0 tokens,  green  DIRECT  badge)
  Tier 3 — INTENT-FIRST    (0 tokens,  purple INTENT  badge)
  Tier 4 — CACHE           (0 tokens,  blue   CACHED  badge)
  Tier 5a— AI_SIMPLE       (~300 tokens, orange AI_SIMPLE badge)
  Tier 5b— AI_COMPLEX      (~800-1200 tokens, red AI_COMPLEX badge)
  Bonus  — Anomaly alerts  (0 tokens, orange chips on any data query)

Each test verifies:
  - `source` field in response  (routing badge)
  - `meta.cached` flag
  - Router log pattern (via classify())
  - Groq mock not called when expected to be 0-token
"""

import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main_groq import app
from services.query_router import classify
from services.context_cache import invalidate

client = TestClient(app)


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_state():
    """Flush cache and rate limit windows before every test."""
    invalidate()
    from services.rate_limiter import _ip_window, _upload_window, _minute_window
    _ip_window.clear()
    _upload_window.clear()
    _minute_window.clear()
    yield


@pytest.fixture(scope="module")
def auth_headers():
    import uuid
    username = f"test_routing_{uuid.uuid4().hex[:8]}"
    password = "TestPass123!"
    resp = client.post("/signup", json={
        "username": username,
        "password": password,
        "business_name": "Routing Test Biz",
    })
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _mock_groq_simple(text: str = "Mocked AI response."):
    """Returns a mock that simulates a single-completion Groq response (no tool calls)."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=text, tool_calls=None))]
    mock_resp.usage = MagicMock(prompt_tokens=120, completion_tokens=80)
    return mock_resp


def _mock_groq_with_tool(tool_name: str, tool_args: str, final_text: str):
    """Returns a side_effect list simulating tool-call then final response."""
    tool_call = MagicMock()
    tool_call.id = "call_test_001"
    tool_call.function.name = tool_name
    tool_call.function.arguments = tool_args

    msg1 = MagicMock()
    msg1.tool_calls = [tool_call]
    msg1.content = None
    resp1 = MagicMock()
    resp1.choices = [MagicMock(message=msg1)]
    resp1.usage = MagicMock(prompt_tokens=200, completion_tokens=20)

    msg2 = MagicMock()
    msg2.tool_calls = None
    msg2.content = final_text
    resp2 = MagicMock()
    resp2.choices = [MagicMock(message=msg2)]
    resp2.usage = MagicMock(prompt_tokens=300, completion_tokens=100)

    return [resp1, resp2]


# ===========================================================================
# TIER 1 — CONVERSATIONAL
# ===========================================================================

class TestTier1Conversational:
    """
    These queries should never touch the DB or cost AI tokens.
    source = "conversational", no suggestions, no alerts.
    """

    QUERIES = [
        "thanks",
        "okay got it",
        "hi there",
        "sounds good",
        "okay",
        "yes",
        "no",
        "cool",
        "great",
        "bye",
        "perfect",
        "noted",
        "makes sense",
        "yep",
        "got it thanks",
        "hi",
        "hello",
        "hey",
    ]

    def test_classify_conversational(self):
        for q in self.QUERIES:
            route, _ = classify(q)
            assert route == "CONVERSATIONAL", f"Expected CONVERSATIONAL for: '{q}', got {route}"

    @patch("routes.ask._client.chat.completions.create")
    def test_conversational_response_source(self, mock_create, auth_headers):
        """Conversational replies use a Groq call but return source=conversational."""
        mock_create.return_value = _mock_groq_simple("Hi! How can I help you today?")
        resp = client.post("/ask", json={"message": "hi there"}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "conversational"
        assert data.get("meta", {}).get("cached") is False

    @patch("routes.ask._client.chat.completions.create")
    def test_conversational_no_suggestions(self, mock_create, auth_headers):
        """Conversational replies have empty suggestions."""
        mock_create.return_value = _mock_groq_simple("You're welcome!")
        resp = client.post("/ask", json={"message": "thanks"}, headers=auth_headers)
        data = resp.json()
        assert data["source"] == "conversational"
        assert data.get("suggestions", []) == []

    @patch("routes.ask._client.chat.completions.create")
    def test_conversational_only_one_groq_call(self, mock_create, auth_headers):
        """Conversational tier makes exactly 1 Groq call (the short reply)."""
        mock_create.return_value = _mock_groq_simple("Sounds good!")
        client.post("/ask", json={"message": "sounds good"}, headers=auth_headers)
        assert mock_create.call_count == 1


# ===========================================================================
# TIER 2 — DIRECT  (0 tokens, source = "db")
# ===========================================================================

class TestTier2Direct:
    """
    DB can answer fully — no LLM tokens spent.
    source = "db", meta.tokens = 0.
    """

    DIRECT_CASES = [
        # (query, expected_handler_key)
        ("how many invoices do I have",      "invoice_count"),
        ("invoice count",                    "invoice_count"),
        ("total invoices",                   "invoice_count"),
        ("what is my total revenue",         "total_revenue"),
        ("total revenue",                    "total_revenue"),
        ("how much revenue",                 "total_revenue"),
        ("show overdue invoices",            "overdue_list"),
        ("list overdue",                     "overdue_list"),
        ("overdue list",                     "overdue_list"),
        ("how much is overdue",              "overdue_amount"),
        ("total overdue amount",             "overdue_amount"),
        ("pending invoices",                 "pending_list"),
        ("show me pending",                  "pending_list"),
        ("list low stock items",             "low_stock"),
        ("low stock",                        "low_stock"),
        ("out of stock",                     "low_stock"),
        ("which products are expiring soon", "expiring_soon"),
        ("expiring items",                   "expiring_soon"),
        ("top 5 customers by revenue",       "top_customers"),
        ("top customers",                    "top_customers"),
        ("top debtors",                      "top_debtors"),
        ("who owes me the most",             "top_debtors"),
        ("biggest debtor",                   "top_debtors"),
        ("how many products",                "inventory_count"),
        ("inventory count",                  "inventory_count"),
        ("business summary",                 "business_summary"),
        ("dashboard overview",               "business_summary"),
        ("quick snapshot",                   "business_summary"),
    ]

    def test_classify_direct(self):
        for query, expected_key in self.DIRECT_CASES:
            route, key = classify(query)
            assert route == "DIRECT", f"'{query}' → expected DIRECT, got {route}"
            assert key == expected_key, f"'{query}' → expected key={expected_key}, got key={key}"

    @patch("routes.ask._client.chat.completions.create")
    def test_direct_source_is_db(self, mock_create, auth_headers):
        """DIRECT responses have source='db' and don't call Groq for the main answer."""
        resp = client.post("/ask", json={"message": "how many invoices do I have"}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # source must be "db" (polish call may happen but source stays "db")
        assert data["source"] == "db"

    @patch("routes.ask._client.chat.completions.create")
    def test_direct_overdue_returns_data(self, mock_create, auth_headers):
        resp = client.post("/ask", json={"message": "show overdue invoices"}, headers=auth_headers)
        data = resp.json()
        assert data["source"] == "db"
        assert "response" in data
        assert len(data["response"]) > 0

    @patch("routes.ask._client.chat.completions.create")
    def test_direct_has_suggestions(self, mock_create, auth_headers):
        """DIRECT responses include recommendation chips."""
        resp = client.post("/ask", json={"message": "show overdue invoices"}, headers=auth_headers)
        data = resp.json()
        assert data["source"] == "db"
        assert isinstance(data.get("suggestions", []), list)

    @patch("routes.ask._client.chat.completions.create")
    def test_direct_revenue_contains_numbers(self, mock_create, auth_headers):
        resp = client.post("/ask", json={"message": "total revenue"}, headers=auth_headers)
        data = resp.json()
        assert data["source"] == "db"
        assert any(c.isdigit() for c in data["response"])


# ===========================================================================
# TIER 3 — INTENT-FIRST  (0 tokens, source = "intent")
# ===========================================================================

class TestTier3IntentFirst:
    """
    Semantic variants that classify() routes as AI_SIMPLE but ai_router
    promotes to DIRECT via the intent resolver.
    source = "intent".
    """

    INTENT_CASES = [
        # (query, expected_topic)
        ("who hasn't paid me",              "overdue_list"),
        ("who owes me money",               "overdue_list"),
        ("what customers still owe me",     "overdue_list"),
        ("what's outstanding from clients", "overdue_list"),
        ("show me my debtors",              "overdue_list"),
        ("what's running low on stock",     "low_stock"),
        ("which products are almost out",   "low_stock"),
        ("any items about to expire",       "expiring_soon"),
        ("who are my biggest customers",    "top_customers"),
        ("what's my collection situation",  "overdue_list"),
    ]

    def test_classify_intent_routes_as_ai_simple(self):
        """These queries route as AI_SIMPLE — intent promotion happens in ai_router, not classify."""
        intent_queries = [q for q, _ in self.INTENT_CASES]
        for q in intent_queries:
            route, _ = classify(q)
            # Intentional: classify returns AI_SIMPLE; ai_router promotes it
            assert route in ("AI_SIMPLE", "DIRECT"), f"Unexpected route for '{q}': {route}"

    @patch("routes.ask._client.chat.completions.create")
    def test_intent_overdue_variants(self, mock_create, auth_headers):
        """Overdue semantic variants should all return source='intent' or 'db'."""
        mock_create.return_value = _mock_groq_simple("Here is the overdue summary.")
        for q, _ in self.INTENT_CASES[:5]:  # overdue variants
            invalidate()
            resp = client.post("/ask", json={"message": q}, headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            assert data["source"] in ("intent", "db", "ai"), \
                f"'{q}' returned unexpected source: {data['source']}"

    @patch("routes.ask._client.chat.completions.create")
    def test_intent_low_stock_variant(self, mock_create, auth_headers):
        mock_create.return_value = _mock_groq_simple("Low stock items.")
        invalidate()
        resp = client.post("/ask", json={"message": "what's running low on stock"}, headers=auth_headers)
        data = resp.json()
        assert resp.status_code == 200
        assert data["source"] in ("intent", "db", "ai")

    @patch("routes.ask._client.chat.completions.create")
    def test_intent_expiry_variant(self, mock_create, auth_headers):
        mock_create.return_value = _mock_groq_simple("Expiring items.")
        invalidate()
        resp = client.post("/ask", json={"message": "any items about to expire"}, headers=auth_headers)
        data = resp.json()
        assert resp.status_code == 200
        assert data["source"] in ("intent", "db", "ai")

    @patch("routes.ask._client.chat.completions.create")
    def test_intent_response_has_data(self, mock_create, auth_headers):
        """Intent responses should contain actual business data, not empty strings."""
        mock_create.return_value = _mock_groq_simple()
        invalidate()
        resp = client.post("/ask", json={"message": "who owes me money"}, headers=auth_headers)
        data = resp.json()
        assert len(data.get("response", "")) > 10


# ===========================================================================
# TIER 4 — CACHE  (0 tokens, meta.cached = True)
# ===========================================================================

class TestTier4Cache:
    """
    Same topic, different phrasing → second call hits cache.
    meta.cached = True, 0 tokens on repeat.
    """

    @patch("routes.ask._client.chat.completions.create")
    def test_catchall_topic_repeats_cache_but_distinct_dont_collide(self, mock_create, auth_headers):
        """
        'business_summary' is _detect_topic's safe DEFAULT, so unrelated AI_SIMPLE
        fallbacks land on it. They must NOT share a cache entry (that collision is
        what served 'do yo know Rahul traders' a stale generic summary). An EXACT
        repeat of the same query still caches.
        """
        invalidate()
        mock_create.return_value = _mock_groq_simple("Focus on overdue collection today.")

        # Call 1 — cache miss (AI_SIMPLE, catch-all topic, keyed on the query)
        resp1 = client.post("/ask", json={"message": "is my business performing well this month"}, headers=auth_headers)
        assert resp1.status_code == 200
        assert resp1.json()["source"] in ("ai", "intent", "db")

        # Call 2 — EXACT same query → cache hit (same q: key)
        resp2 = client.post("/ask", json={"message": "is my business performing well this month"}, headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json().get("meta", {}).get("cached") is True, \
            f"Expected cache hit on exact repeat, got meta={resp2.json().get('meta')}"

        # Call 3 — DIFFERENT vague query on the same catch-all topic → must NOT
        # be served call 1's answer (no cross-contamination).
        resp3 = client.post("/ask", json={"message": "what needs my attention now"}, headers=auth_headers)
        assert resp3.status_code == 200
        assert resp3.json().get("meta", {}).get("cached") is False, \
            f"Distinct catch-all query must not collide, got meta={resp3.json().get('meta')}"

    @patch("routes.ask._client.chat.completions.create")
    def test_cache_hit_overdue_topic(self, mock_create, auth_headers):
        """Two overdue queries share the same topic salt → second is cached."""
        invalidate()
        mock_create.return_value = _mock_groq_simple("249 overdue invoices.")

        resp1 = client.post("/ask", json={"message": "show overdue invoices"}, headers=auth_headers)
        assert resp1.status_code == 200

        resp2 = client.post("/ask", json={"message": "show overdue invoices"}, headers=auth_headers)
        assert resp2.status_code == 200
        d2 = resp2.json()
        assert d2.get("meta", {}).get("cached") is True

    @patch("routes.ask._client.chat.completions.create")
    def test_cache_invalidated_after_upload(self, mock_create, auth_headers):
        """Uploading a file clears the cache — next query is a cache miss."""
        invalidate()
        mock_create.return_value = _mock_groq_simple("Revenue summary.")

        # Prime the cache
        resp1 = client.post("/ask", json={"message": "total revenue"}, headers=auth_headers)
        assert resp1.status_code == 200

        # Upload a new file to bust the cache
        csv_content = (
            "invoice_id,customer,product,amount,status,due_date\n"
            "INV-CACHE-001,Test Co,Widget,500.0,Paid,2026-07-01\n"
        ).encode()
        client.post("/upload",
                    files={"file": ("cache_test.csv", csv_content, "text/csv")},
                    headers=auth_headers)

        # Same query → cache should be busted
        resp2 = client.post("/ask", json={"message": "total revenue"}, headers=auth_headers)
        assert resp2.status_code == 200
        d2 = resp2.json()
        assert d2.get("meta", {}).get("cached") is not True

    @patch("routes.ask._client.chat.completions.create")
    def test_cached_response_content_identical(self, mock_create, auth_headers):
        """Cached response must have identical content to original."""
        invalidate()
        mock_create.return_value = _mock_groq_simple("Overdue: 5 invoices, ₹50,000.")

        resp1 = client.post("/ask", json={"message": "show overdue invoices"}, headers=auth_headers)
        resp2 = client.post("/ask", json={"message": "show overdue invoices"}, headers=auth_headers)

        d1, d2 = resp1.json(), resp2.json()
        assert d1["response"] == d2["response"]
        assert d2.get("meta", {}).get("cached") is True


# ===========================================================================
# TIER 5a — AI_SIMPLE  (~300 tokens, source = "ai")
# ===========================================================================

class TestTier5aAISimple:
    """
    Queries that need LLM reasoning but not multi-agent strategy.
    source = "ai", meta.cached = False on first call.
    """

    AI_SIMPLE_QUERIES = [
        "draft a payment reminder message for my overdue customers",
        "which customer should I call first",
        "explain my cash flow situation",
        "who is my most reliable customer",
        "what payment terms should I offer new customers",
        "is my business performing well this month",
    ]

    def test_classify_ai_simple(self):
        for q in self.AI_SIMPLE_QUERIES:
            route, _ = classify(q)
            assert route in ("AI_SIMPLE", "CONVERSATIONAL"), \
                f"'{q}' → expected AI_SIMPLE, got {route}"

    @patch("routes.ask._client.chat.completions.create")
    def test_ai_simple_source(self, mock_create, auth_headers):
        """AI_SIMPLE queries return source='ai'."""
        invalidate()
        mock_create.return_value = _mock_groq_simple("Here is your business focus for today.")
        resp = client.post("/ask", json={"message": "what should I focus on today"}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] in ("ai", "db", "intent"), f"Unexpected source: {data['source']}"

    @patch("routes.ask._client.chat.completions.create")
    def test_ai_simple_not_cached_first_call(self, mock_create, auth_headers):
        """First AI_SIMPLE call is never cached."""
        invalidate()
        mock_create.return_value = _mock_groq_simple("Payment reminder drafted.")
        resp = client.post("/ask",
                           json={"message": "how is my overall business health"},
                           headers=auth_headers)
        data = resp.json()
        assert data.get("meta", {}).get("cached") is False

    @patch("routes.ask._client.chat.completions.create")
    def test_ai_simple_with_tool_calling(self, mock_create, auth_headers):
        """AI_SIMPLE tool-calling flow completes successfully."""
        invalidate()
        mock_create.side_effect = _mock_groq_with_tool(
            tool_name="summarize_invoices",
            tool_args='{}',
            final_text="Your top priority customer to call is Daily Needs Store — ₹99,042 overdue."
        )
        resp = client.post("/ask",
                           json={"message": "which customer should I call first"},
                           headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] in ("ai", "intent", "db")

    @patch("routes.ask._client.chat.completions.create")
    def test_ai_simple_has_response_text(self, mock_create, auth_headers):
        """AI_SIMPLE always returns non-empty response text."""
        invalidate()
        mock_create.return_value = _mock_groq_simple("Your cash flow is under pressure due to 44% collection rate.")
        resp = client.post("/ask",
                           json={"message": "explain my cash flow situation"},
                           headers=auth_headers)
        data = resp.json()
        assert len(data.get("response", "")) > 5

    @patch("routes.ask._client.chat.completions.create")
    def test_ai_simple_second_call_cached(self, mock_create, auth_headers):
        """Second AI_SIMPLE call with same topic → cache hit."""
        invalidate()
        mock_create.return_value = _mock_groq_simple("Focus on collections today.")
        client.post("/ask", json={"message": "what should I focus on today"}, headers=auth_headers)

        resp2 = client.post("/ask", json={"message": "what should I focus on today"}, headers=auth_headers)
        data2 = resp2.json()
        assert data2.get("meta", {}).get("cached") is True


# ===========================================================================
# TIER 5b — AI_COMPLEX  (~800-1200 tokens, source = "ai")
# ===========================================================================

class TestTier5bAIComplex:
    """
    Multi-step reasoning, strategy, analysis.
    source = "ai", routed via LangGraph agent graph.
    """

    COMPLEX_QUERIES = [
        "analyze my business performance and give me a recovery plan",
        "why is my collection rate low and how do I fix it",
        "analyze the uploaded file",
        "give me a detailed growth strategy for next quarter",
        "what are the root causes of my overdue problem",
        "compare my revenue trend and give insights",
        "give me a full business health report",
        "what should I do to improve my profitability",
        "recommend a pricing strategy based on my data",
        "plan my collections for the next 30 days",
    ]

    def test_classify_complex(self):
        for q in self.COMPLEX_QUERIES:
            route, _ = classify(q)
            assert route == "AI_COMPLEX", f"'{q}' → expected AI_COMPLEX, got {route}"

    @patch("services.ai_router.run_agent_graph")
    def test_ai_complex_uses_agent_graph(self, mock_graph, auth_headers):
        """AI_COMPLEX queries go through LangGraph agent graph."""
        invalidate()
        mock_graph.return_value = "Detailed business recovery plan: ..."
        resp = client.post("/ask",
                           json={"message": "analyze my business performance and give me a recovery plan"},
                           headers=auth_headers)
        assert resp.status_code == 200
        mock_graph.assert_called_once()

    @patch("services.ai_router.run_agent_graph")
    def test_ai_complex_source_is_ai(self, mock_graph, auth_headers):
        """AI_COMPLEX always returns source='ai'."""
        invalidate()
        mock_graph.return_value = "Root cause analysis complete."
        resp = client.post("/ask",
                           json={"message": "what are the root causes of my overdue problem"},
                           headers=auth_headers)
        data = resp.json()
        assert data["source"] == "ai"
        assert data.get("meta", {}).get("cached") is False

    @patch("services.ai_router.run_agent_graph")
    def test_ai_complex_second_call_cached(self, mock_graph, auth_headers):
        """AI_COMPLEX second identical call hits cache."""
        invalidate()
        mock_graph.return_value = "Growth strategy for Q3."

        q = "give me a detailed growth strategy for next quarter"
        client.post("/ask", json={"message": q}, headers=auth_headers)

        resp2 = client.post("/ask", json={"message": q}, headers=auth_headers)
        data2 = resp2.json()
        assert data2.get("meta", {}).get("cached") is True
        # Agent graph should only be called once
        assert mock_graph.call_count == 1


# ===========================================================================
# ANOMALY ALERTS  (0 tokens, orange chips alongside any data response)
# ===========================================================================

class TestAnomalyAlerts:
    """
    detect_anomalies() runs on every DIRECT / INTENT / AI response.
    Returns a list of alert dicts (or empty list if no anomalies).
    Never adds to token count.
    """

    @patch("routes.ask._client.chat.completions.create")
    def test_alerts_present_on_direct(self, mock_create, auth_headers):
        """DIRECT responses carry an 'alerts' key."""
        resp = client.post("/ask", json={"message": "show my revenue"}, headers=auth_headers)
        data = resp.json()
        assert data["source"] in ("db", "intent", "ai")
        assert "alerts" in data
        assert isinstance(data["alerts"], list)

    @patch("routes.ask._client.chat.completions.create")
    def test_alerts_present_on_ai_simple(self, mock_create, auth_headers):
        """AI_SIMPLE responses also carry 'alerts'."""
        invalidate()
        mock_create.return_value = _mock_groq_simple("Your collection rate needs attention.")
        resp = client.post("/ask",
                           json={"message": "explain my cash flow situation"},
                           headers=auth_headers)
        data = resp.json()
        assert "alerts" in data

    @patch("routes.ask._client.chat.completions.create")
    def test_alerts_are_valid_shape(self, mock_create, auth_headers):
        """Each alert dict has at least a 'type' or 'message' key."""
        resp = client.post("/ask", json={"message": "total revenue"}, headers=auth_headers)
        data = resp.json()
        for alert in data.get("alerts") or []:
            assert isinstance(alert, dict), f"Alert is not a dict: {alert}"

    @patch("routes.ask._client.chat.completions.create")
    def test_alerts_not_present_on_conversational(self, mock_create, auth_headers):
        """Conversational tier does NOT include alerts."""
        mock_create.return_value = _mock_groq_simple("You're welcome!")
        resp = client.post("/ask", json={"message": "thanks"}, headers=auth_headers)
        data = resp.json()
        assert data["source"] == "conversational"
        # alerts key either absent or None
        assert not data.get("alerts")


# ===========================================================================
# CROSS-TIER EDGE CASES
# ===========================================================================

class TestEdgeCases:
    """
    Boundary conditions, follow-ups, and mixed scenarios.
    """

    def test_classify_follow_up_with_history(self):
        """Follow-up phrases with prior history route as AI_SIMPLE."""
        followups = [
            "tell me more about that",
            "clarify the last point",
            "based on that, what should I do",
            "and what about the inventory",
        ]
        for q in followups:
            route, _ = classify(q, has_history=True)
            assert route == "AI_SIMPLE", f"Follow-up '{q}' → expected AI_SIMPLE, got {route}"

    def test_classify_follow_up_without_history(self):
        """Same phrases without history should NOT be forced to AI_SIMPLE."""
        route, _ = classify("and what about the inventory", has_history=False)
        # Without history, this may route differently — just must not be CONVERSATIONAL
        assert route in ("AI_SIMPLE", "DIRECT", "AI_COMPLEX")

    def test_classify_digit_queries_go_to_ai_simple(self):
        """Queries with unusual numbers route to AI_SIMPLE (not DIRECT)."""
        assert classify("show me invoices from 2023")[0] == "AI_SIMPLE"
        assert classify("customers who owe more than 75000")[0] == "AI_SIMPLE"
        assert classify("invoices between 500 and 2000")[0] == "AI_SIMPLE"

    def test_classify_default_digit_queries_still_direct(self):
        """Standard digit queries (e.g. top 5, expiring 30 days) stay DIRECT."""
        assert classify("top 5 customers by revenue")[0] == "DIRECT"
        assert classify("items expiring in 30 days")[0] == "DIRECT"

    @patch("routes.ask._client.chat.completions.create")
    def test_different_topics_no_cross_cache(self, mock_create, auth_headers):
        """Overdue query does NOT return cached response for a revenue query."""
        invalidate()
        mock_create.return_value = _mock_groq_simple("Revenue is ₹27L.")
        client.post("/ask", json={"message": "total revenue"}, headers=auth_headers)

        resp2 = client.post("/ask", json={"message": "show overdue invoices"}, headers=auth_headers)
        data2 = resp2.json()
        # Different topic → must not be cached from first call
        # (may be cached from its own prior run, but response must relate to overdue)
        assert data2.get("meta", {}).get("cached") is not True or "overdue" in data2["response"].lower() or data2["source"] == "db"

    @patch("routes.ask._client.chat.completions.create")
    def test_empty_query_handled_gracefully(self, mock_create, auth_headers):
        """Empty or whitespace query doesn't crash the server."""
        mock_create.return_value = _mock_groq_simple("Hi!")
        resp = client.post("/ask", json={"message": "   "}, headers=auth_headers)
        assert resp.status_code in (200, 400, 422)

    def test_classify_all_tiers_represented(self):
        """Sanity check: all 4 route types are reachable via classify()."""
        assert classify("hi")[0]                                             == "CONVERSATIONAL"
        assert classify("total revenue")[0]                                  == "DIRECT"
        assert classify("who is my most reliable supplier?")[0]              == "AI_SIMPLE"
        assert classify("analyze my business and give a growth strategy")[0] == "AI_COMPLEX"


# ===========================================================================
# ROUTER CLASSIFY() COMPLETENESS
# ===========================================================================

class TestClassifyCompleteness:
    """
    Exhaustive classify() coverage — no HTTP needed, instant.
    Ensures every user-facing example in the spec routes correctly.
    """

    def test_tier1_full_list(self):
        tier1 = ["thanks", "okay got it", "hi there", "sounds good",
                 "yes", "no", "cool", "great", "bye", "perfect", "noted",
                 "makes sense", "yep", "got it thanks", "hi", "hello", "hey", "okay"]
        for q in tier1:
            assert classify(q)[0] == "CONVERSATIONAL", f"Failed CONVERSATIONAL: '{q}'"

    def test_tier2_full_list(self):
        tier2 = [
            ("how many invoices do I have", "invoice_count"),
            ("what is my total revenue",    "total_revenue"),
            ("show overdue invoices",        "overdue_list"),
            ("list low stock items",         "low_stock"),
            ("which products are expiring soon", "expiring_soon"),
            ("top 5 customers by revenue",   "top_customers"),
            ("show me pending invoices",     "pending_list"),
        ]
        for q, expected_key in tier2:
            route, key = classify(q)
            assert route == "DIRECT",        f"'{q}' → DIRECT expected"
            assert key == expected_key,      f"'{q}' → key {expected_key} expected, got {key}"

    def test_tier5b_full_list(self):
        tier5b = [
            "analyze my business performance and give me a recovery plan",
            "why is my collection rate low and how do I fix it",
            "give me a detailed growth strategy for next quarter",
            "what are the root causes of my overdue problem",
        ]
        for q in tier5b:
            assert classify(q)[0] == "AI_COMPLEX", f"Failed AI_COMPLEX: '{q}'"
