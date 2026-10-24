"""
tests/test_groq_models.py — billing's Groq models after the 2026 retirements
=============================================================================
Groq switched off billing's defaults - llama-4-scout and qwen3-32b on
2026-07-17, llama-3.3-70b-versatile on 2026-08-16 - so routing, AI_SIMPLE,
CSV mapping, memory, bill-photo OCR and bill-text extraction failed with 404
wherever no override was set (every desktop, and the cloud until it got one).

Pinned here:
  * the defaults are the models checked on 2026-10-24 with the production key,
    defined once (services/groq_client.py) and used by every module;
  * gpt-oss (a reasoning model) gets low thinking and a token budget it can
    think in, whichever module calls it - at the routers' old 160 tokens it ran
    out before finishing its JSON on half the questions;
  * the router is told today's date on every call - without it "this month"
    became May 2024.
No network: Groq is replaced by fakes.
"""
import ast
import datetime as dt
import json
import os
import pathlib
import sys
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

import services.groq_client as gc

BACKEND = pathlib.Path(__file__).resolve().parents[1]
RETIRED = ("llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct", "qwen/qwen3-32b")


def _reply(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))],
                           usage=None)


class FakeCompletions:
    def __init__(self, content='{"ok": true}'):
        self.calls, self.content = [], content

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _reply(self.content)


# ── defaults ────────────────────────────────────────────────────────────────

class TestDefaults:

    def test_the_checked_models(self):
        assert gc.DEFAULT_TEXT_MODEL == "qwen/qwen3.8-27b"
        assert gc.DEFAULT_VISION_MODEL == "qwen/qwen3.8-27b"
        assert gc.DEFAULT_COMPLEX_MODEL == "openai/gpt-oss-120b"

    def test_no_module_names_a_model_of_its_own(self):
        """A model id in code, outside groq_client.py, is a default nobody will
        find when Groq retires it - the reason the last switch-off broke six
        modules at once. Comments and docstrings may mention them."""
        found = []
        for path in (BACKEND / "services").glob("*.py"):
            if path.name == "groq_client.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) == "getenv":
                    args = [a.value for a in node.args if isinstance(a, ast.Constant)]
                    if args and str(args[0]).startswith("GROQ_") and len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                        found.append(f"{path.name}: getenv({args[0]!r}, {node.args[1].value!r})")
                if isinstance(node, ast.Constant) and node.value in RETIRED:
                    found.append(f"{path.name}: {node.value!r}")
        assert not found, "model ids outside services/groq_client.py: " + "; ".join(found)

    def test_bill_text_extraction_uses_the_complex_model(self, monkeypatch):
        """It defaulted to qwen/qwen3-32b, retired on 2026-07-17."""
        import services.purchase_ocr as ocr
        fake = FakeCompletions('{"supplier_name": "Shree Ganesh Pharma", "items": []}')
        monkeypatch.delenv("GROQ_MODEL_COMPLEX", raising=False)
        monkeypatch.setattr(gc, "make_groq_client", lambda key=None: SimpleNamespace(chat=SimpleNamespace(completions=fake)))
        ocr.extract_structured_purchase_invoice("Invoice SGP-2026-0412 Grand Total Rs 1422.40")
        assert fake.calls[0]["model"] == "openai/gpt-oss-120b"

    def test_an_override_still_wins(self, monkeypatch):
        import services.purchase_ocr as ocr
        fake = FakeCompletions('{"items": []}')
        monkeypatch.setenv("GROQ_MODEL_COMPLEX", "some/other-model")
        monkeypatch.setattr(gc, "make_groq_client", lambda key=None: SimpleNamespace(chat=SimpleNamespace(completions=fake)))
        ocr.extract_structured_purchase_invoice("Invoice 1")
        assert fake.calls[0]["model"] == "some/other-model"


# ── gpt-oss: thinking level and token room ──────────────────────────────────

class TestReasoningModels:

    def _sent(self, **kwargs):
        fake = FakeCompletions()
        gc._tuned_for_reasoning(fake.create)(**kwargs)
        return fake.calls[0]

    def test_a_small_budget_is_raised_and_thinking_set_low(self):
        sent = self._sent(model="openai/gpt-oss-120b", max_tokens=160, messages=[])
        assert sent["max_tokens"] == gc.MIN_REASONING_TOKENS
        assert sent["reasoning_effort"] == "low"

    def test_max_completion_tokens_too(self):
        sent = self._sent(model="openai/gpt-oss-20b", max_completion_tokens=80, messages=[])
        assert sent["max_completion_tokens"] == gc.MIN_REASONING_TOKENS

    def test_a_large_budget_and_an_explicit_effort_are_left_alone(self):
        sent = self._sent(model="openai/gpt-oss-120b", max_tokens=1800, reasoning_effort="high", messages=[])
        assert sent["max_tokens"] == 1800 and sent["reasoning_effort"] == "high"

    def test_other_models_are_untouched(self):
        sent = self._sent(model="qwen/qwen3.8-27b", max_tokens=160, messages=[])
        assert sent == {"model": "qwen/qwen3.8-27b", "max_tokens": 160, "messages": []}

    def test_every_client_billing_makes_has_it(self):
        client = gc.make_groq_client("test-key-not-used")
        assert client.chat.completions.create.__wrapped__ is not None
        assert client.chat.completions is client.chat.completions, "one completions object per client"


# ── the router knows today's date ───────────────────────────────────────────

@pytest.fixture
def router(monkeypatch):
    import services.dates as dates
    import services.llm_router as R
    monkeypatch.setattr(dates, "biz_now", lambda: dt.datetime(2026, 10, 24, 21, 30))
    return R


def test_the_date_line_names_this_month_and_last(router):
    line = router._today_line()
    assert "Saturday 2026-10-24" in line
    assert "'this month' → '2026-10'" in line and "'last month' → '2026-09'" in line


def test_last_month_crosses_the_year(router, monkeypatch):
    import services.dates as dates
    monkeypatch.setattr(dates, "biz_now", lambda: dt.datetime(2026, 1, 5, 9, 0))
    assert "'last month' → '2025-12'" in router._today_line()


def test_classify_sends_the_date_after_the_fixed_prompt(router):
    fake = FakeCompletions(json.dumps({"mode": "answer", "intent": "revenue_month_detail", "action": None,
                                       "entities": {"month": "2026-10"}, "confidence": 0.95}))
    client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    decision = router.classify("How much did I sell this month?", client=client)
    system = fake.calls[0]["messages"][0]["content"]
    assert system.startswith(router._SYSTEM), "the fixed prompt stays first (cacheable prefix)"
    assert system.endswith(router._today_line())
    assert decision is not None and decision.entities.get("month") == "2026-10"
