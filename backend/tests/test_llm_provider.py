"""
test_llm_provider.py — AI Phase 0 provider fallback.
====================================================
Pure-logic tests (no network): fake providers exercise the ResilientClient
failover, error classification, streaming degradation, and message
normalization. Also asserts the factory is a no-op when disabled.
"""
import os
import sys
from types import SimpleNamespace

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from services import llm_provider as LP


# ── fakes ────────────────────────────────────────────────────────────────────

class _Boom(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status_code = status


def _resp(content, ptoks=3, ctoks=5):
    msg = LP._Message(content=content)
    return LP._Response([LP._Choice(message=msg)],
                        LP._usage_obj({"prompt_tokens": ptoks, "completion_tokens": ctoks}))


class FakeProvider:
    def __init__(self, name, *, stream=False, answer=None, error=None, record=None):
        self.name = name
        self.supports_stream = stream
        self._answer = answer
        self._error = error
        self._record = record

    def create(self, **kwargs):
        if self._record is not None:
            self._record.append(self.name)
        if self._error is not None:
            raise self._error
        return self._answer


# ── failover ─────────────────────────────────────────────────────────────────

def test_failover_on_retriable_error():
    calls = []
    primary = FakeProvider("groq", stream=True, error=_Boom("timeout"), record=calls)   # no status → retriable
    backup = FakeProvider("gemini", answer=_resp("from gemini"), record=calls)
    rc = LP.ResilientClient([primary, backup])
    out = rc.chat.completions.create(model="x", messages=[{"role": "user", "content": "hi"}])
    assert out.choices[0].message.content == "from gemini"
    assert calls == ["groq", "gemini"]                 # both tried, in order


def test_no_failover_on_4xx():
    calls = []
    primary = FakeProvider("groq", stream=True, error=_Boom("bad request", status=400), record=calls)
    backup = FakeProvider("gemini", answer=_resp("should not be used"), record=calls)
    rc = LP.ResilientClient([primary, backup])
    with pytest.raises(_Boom):
        rc.chat.completions.create(model="x", messages=[])
    assert calls == ["groq"]                            # backup never tried on client error


def test_ratelimit_is_retriable():
    calls = []
    primary = FakeProvider("groq", stream=True, error=_Boom("rate", status=429), record=calls)
    backup = FakeProvider("gemini", answer=_resp("ok"), record=calls)
    rc = LP.ResilientClient([primary, backup])
    assert rc.chat.completions.create(model="x", messages=[]).choices[0].message.content == "ok"
    assert calls == ["groq", "gemini"]


def test_all_fail_raises_last():
    p1 = FakeProvider("groq", stream=True, error=_Boom("down1"))
    p2 = FakeProvider("gemini", error=_Boom("down2"))
    rc = LP.ResilientClient([p1, p2])
    with pytest.raises(_Boom, match="down2"):
        rc.chat.completions.create(model="x", messages=[])


def test_primary_success_short_circuits():
    calls = []
    primary = FakeProvider("groq", stream=True, answer=_resp("fast"), record=calls)
    backup = FakeProvider("gemini", answer=_resp("nope"), record=calls)
    rc = LP.ResilientClient([primary, backup])
    assert rc.chat.completions.create(model="x", messages=[]).choices[0].message.content == "fast"
    assert calls == ["groq"]


# ── streaming degradation ────────────────────────────────────────────────────

def test_stream_degrades_to_single_chunk():
    primary = FakeProvider("groq", stream=True, error=_Boom("stream down"))
    backup = FakeProvider("gemini", stream=False, answer=_resp("streamed answer", ptoks=7, ctoks=9))
    rc = LP.ResilientClient([primary, backup])
    chunks = list(rc.chat.completions.create(model="x", messages=[], stream=True,
                                             stream_options={"include_usage": True}))
    # first chunk carries the whole content as a delta
    assert chunks[0].choices[0].delta.content == "streamed answer"
    # final chunk carries usage, no choices
    assert chunks[-1].choices == []
    assert chunks[-1].usage.completion_tokens == 9


def test_native_stream_passes_through():
    # primary supports streaming → returned object is whatever the provider gives
    sentinel = ["a", "b", "c"]
    primary = FakeProvider("groq", stream=True, answer=sentinel)
    rc = LP.ResilientClient([primary])
    assert rc.chat.completions.create(model="x", messages=[], stream=True) is sentinel


# ── message normalization (cross-provider tool loops) ────────────────────────

def test_message_normalization():
    # dict passes through
    assert LP._to_openai_message({"role": "user", "content": "hi"}) == {"role": "user", "content": "hi"}
    # our assistant message with tool calls → OpenAI dict
    tc = LP._ToolCall("call_1", "get_stock", '{"sku":"A"}')
    m = LP._Message(content=None, tool_calls=[tc])
    d = LP._to_openai_message(m)
    assert d["role"] == "assistant"
    assert d["tool_calls"][0]["function"]["name"] == "get_stock"
    assert d["tool_calls"][0]["id"] == "call_1"
    # a Groq-like pydantic object (has model_dump)
    groqish = SimpleNamespace(model_dump=lambda **k: {"role": "assistant", "content": "x"})
    assert LP._to_openai_message(groqish) == {"role": "assistant", "content": "x"}


# ── factory is a no-op when disabled / no fallback keys ──────────────────────

def test_wrap_is_noop_without_fallbacks(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plain = object()
    assert LP.wrap_with_fallback(plain) is plain       # nothing to wrap → untouched


def test_wrap_builds_chain_with_gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDERS", "gemini")

    class FakePrimary:
        class chat:
            class completions:
                @staticmethod
                def create(**k): ...
    wrapped = LP.wrap_with_fallback(FakePrimary())
    assert isinstance(wrapped, LP.ResilientClient)
    names = [p.name for p in wrapped._providers]
    assert names == ["groq", "gemini"]
