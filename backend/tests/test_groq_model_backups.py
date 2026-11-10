"""
tests/test_groq_model_backups.py — a retired Groq model moves calls to the next
================================================================================
Every GROQ_MODEL_* setting is a comma-separated list, first choice first
(services/groq_client.py). When Groq refuses a model as gone - 404 "does not
exist or you do not have access", or 400 "model_decommissioned" - the call is
repeated on the next model, one warning is logged, and the refused model is
skipped for an hour. Nothing else (429, timeouts, bad requests) switches
models. Uses Groq's own error types; no network.
"""
import logging
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import groq
import httpx
import pytest

import services.groq_client as gc

QWEN, OSS = "qwen/qwen3.8-27b", "openai/gpt-oss-120b"


def _groq_error(cls, status, message, code=None):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    body = {"error": {"message": message, "type": "invalid_request_error", "code": code}}
    return cls(message, response=httpx.Response(status, request=request), body=body)


def gone(model):
    return _groq_error(groq.NotFoundError, 404,
                       f"The model `{model}` does not exist or you do not have access to it.", "model_not_found")


class FakeGroq:
    """chat.completions.create that refuses the models in `refuse` (or raises
    `error`), recording every model it was asked for."""

    def __init__(self, refuse=(), error=None):
        self.refuse, self.error, self.asked = dict.fromkeys(refuse), error, []

    def create(self, **kwargs):
        self.asked.append(kwargs)
        model = kwargs["model"]
        if self.error is not None:
            raise self.error
        if model in self.refuse:
            raise self.refuse[model] or gone(model)
        return SimpleNamespace(model=model, choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))], usage=None)


@pytest.fixture(autouse=True)
def fresh():
    gc._gone.clear()
    yield
    gc._gone.clear()


def call(fake, model, **kw):
    return gc._wrap_create(fake.create)(model=model, messages=[], **kw)


def test_a_setting_is_a_list():
    assert gc.model_candidates(f" {QWEN} , {OSS} ,") == [QWEN, OSS]
    assert gc.model_candidates(QWEN) == [QWEN]
    assert gc.model_candidates("") == []


def test_a_gone_model_moves_the_call_to_the_backup(caplog):
    fake = FakeGroq(refuse=[QWEN])
    with caplog.at_level(logging.WARNING, logger="bizassist.groq_client"):
        reply = call(fake, f"{QWEN},{OSS}")
    assert reply.model == OSS
    assert [k["model"] for k in fake.asked] == [QWEN, OSS]
    assert f"Groq refused model '{QWEN}'" in caplog.text and f"Using backup '{OSS}'" in caplog.text


def test_later_calls_skip_it_and_warn_once(caplog):
    fake = FakeGroq(refuse=[QWEN])
    with caplog.at_level(logging.WARNING, logger="bizassist.groq_client"):
        for _ in range(3):
            call(fake, f"{QWEN},{OSS}")
    assert [k["model"] for k in fake.asked] == [QWEN, OSS, OSS, OSS], "no 404 round trip per call"
    assert caplog.text.count("Groq refused model") == 1


def test_it_is_tried_again_after_an_hour(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(gc.time, "monotonic", lambda: clock[0])
    fake = FakeGroq(refuse=[QWEN])
    call(fake, f"{QWEN},{OSS}")
    fake.refuse.clear()                       # access came back
    clock[0] += gc.GONE_RECHECK_SECS + 1
    assert call(fake, f"{QWEN},{OSS}").model == QWEN


def test_a_decommissioned_model_counts_as_gone():
    fake = FakeGroq(refuse=[QWEN])
    fake.refuse[QWEN] = _groq_error(groq.BadRequestError, 400, "The model `x` has been decommissioned",
                                    "model_decommissioned")
    assert call(fake, f"{QWEN},{OSS}").model == OSS


@pytest.mark.parametrize("err", [
    _groq_error(groq.RateLimitError, 429, "Rate limit reached for model"),
    _groq_error(groq.BadRequestError, 400, "Failed to generate JSON", "json_validate_failed"),
])
def test_other_errors_are_not_about_the_model(err):
    """A busy model or a bad request must not send every call to the backup."""
    fake = FakeGroq(error=err)
    with pytest.raises(type(err)):
        call(fake, f"{QWEN},{OSS}")
    assert [k["model"] for k in fake.asked] == [QWEN]
    assert not gc._gone


def test_when_every_model_is_gone_the_404_is_raised_unchanged(caplog):
    """purchase_ocr's vision latch reads this error, so it must stay a 404."""
    fake = FakeGroq(refuse=[QWEN, OSS])
    with caplog.at_level(logging.WARNING, logger="bizassist.groq_client"):
        with pytest.raises(groq.NotFoundError) as e:
            call(fake, f"{QWEN},{OSS}")
    assert OSS in str(e.value)
    assert "no backup model is left" in caplog.text


def test_a_single_model_behaves_as_before():
    fake = FakeGroq(refuse=[QWEN])
    with pytest.raises(groq.NotFoundError):
        call(fake, QWEN)
    assert [k["model"] for k in fake.asked] == [QWEN]


def test_each_attempt_gets_its_own_model_settings():
    """qwen must not be sent gpt-oss's thinking setting, and gpt-oss must get it."""
    fake = FakeGroq(refuse=[QWEN])
    call(fake, f"{QWEN},{OSS}", max_tokens=160)
    first, second = fake.asked
    assert "reasoning_effort" not in first and first["max_tokens"] == 160
    assert second["reasoning_effort"] == "low" and second["max_tokens"] == gc.MIN_REASONING_TOKENS


def test_reports_name_the_model_that_answers():
    assert gc.model_in_use(f"{QWEN},{OSS}") == QWEN
    call(FakeGroq(refuse=[QWEN]), f"{QWEN},{OSS}")
    assert gc.model_in_use(f"{QWEN},{OSS}") == OSS
    assert gc.model_in_use(OSS) == OSS


def test_usage_records_store_one_model_not_the_list():
    from database.db import SessionLocal
    from database.models import TokenUsage
    from services.ai_router_execution import _log_token_usage
    call(FakeGroq(refuse=[QWEN]), f"{QWEN},{OSS}")
    _log_token_usage(987654, f"{QWEN},{OSS}", "TEST_BACKUP", SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                     {"in": 0, "out": 0})
    with SessionLocal() as s:
        row = s.query(TokenUsage).filter(TokenUsage.business_id == 987654,
                                         TokenUsage.model_tier == "TEST_BACKUP").order_by(TokenUsage.id.desc()).first()
        assert row is not None and row.model == OSS


def test_the_router_falls_back_to_its_backup(monkeypatch):
    import services.llm_router as R
    monkeypatch.setattr(R, "MODEL", f"{QWEN},{OSS}")
    reply = '{"mode": "chat", "intent": null, "action": null, "entities": {}, "confidence": 0.9}'

    def create(**kw):
        if kw["model"] == QWEN:
            raise gone(QWEN)
        return SimpleNamespace(model=kw["model"], usage=None,
                               choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=gc._wrap_create(create))))
    decision = R.classify("hi", client=client)
    assert decision is not None and decision.mode == "chat"
