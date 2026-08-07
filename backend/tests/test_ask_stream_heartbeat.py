"""
tests/test_ask_stream_heartbeat.py
==================================
A working request must not be mistaken for a dead one.

An agent run is legitimately silent for long stretches — the LLM router call,
then up to AGENT_MAX_TOOL_ROUNDS model calls at GROQ_TIMEOUT_SECS each. Nothing
crossed the wire between them, so any intermediary with an idle timeout was free
to drop a connection that was still working. The browser's reader then finished
with no `done` event, and the placeholder bubble kept `source: null` — which
renders as a spinner, forever, with no error and nothing in the logs.

The fix is an SSE comment frame during silence. It cannot be a timer around the
pipeline generator: iterating a blocking generator parks the thread inside
next() for the whole quiet period, which is precisely when the beat is needed.
Hence a worker thread feeding a queue, polled with a timeout.
"""
import asyncio
import os
import sys
import time

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest                                       # noqa: E402
import routes.ask as ask                            # noqa: E402


def _drain(resp):
    """Consume a StreamingResponse.

    `body_iterator` is an ASYNC generator — Starlette wraps the sync one — so it
    cannot be list()ed. Driven directly rather than through TestClient, which
    buffers the whole response and would hide the interleaving under test.
    """
    async def _run():
        return [chunk async for chunk in resp.body_iterator]
    return asyncio.run(_run())


def test_silence_produces_keepalive_frames(monkeypatch):
    """The core case: the pipeline yields nothing for longer than the interval,
    so the connection must be kept warm rather than left to be reaped."""
    monkeypatch.setattr(ask, "_HEARTBEAT_SECS", 0.05)
    monkeypatch.setattr(ask, "_require_ai_client", lambda: None)

    def fake_stream(**kwargs):
        time.sleep(0.25)                      # the quiet stretch
        yield 'data: {"type":"done"}\n\n'

    import services.ai_router as ai_router
    monkeypatch.setattr(ai_router, "handle_stream", fake_stream)

    body = ask.ask_ai_stream(ask.Prompt(message="hi", session_id=None),
                             {"id": 1, "username": "u"}, {})
    out = _drain(body)

    beats = [c for c in out if str(c).startswith(": ")]
    assert beats, "a silent pipeline produced no keepalive — the stream can be reaped"
    assert any('"type":"done"' in str(c) for c in out), "the real event must still arrive"


def test_a_fast_answer_sends_no_keepalive(monkeypatch):
    """The beat is for silence only. A prompt reply must not be padded with
    frames the client has to parse and discard."""
    monkeypatch.setattr(ask, "_HEARTBEAT_SECS", 5)
    monkeypatch.setattr(ask, "_require_ai_client", lambda: None)

    def fake_stream(**kwargs):
        yield 'data: {"type":"token","content":"hi"}\n\n'
        yield 'data: {"type":"done"}\n\n'

    import services.ai_router as ai_router
    monkeypatch.setattr(ai_router, "handle_stream", fake_stream)

    out = _drain(ask.ask_ai_stream(ask.Prompt(message="hi", session_id=None),
                                 {"id": 1, "username": "u"}, {}))
    assert not [c for c in out if str(c).startswith(": ")]
    assert len(out) == 2


def test_events_survive_the_worker_thread_in_order(monkeypatch):
    """The queue hand-off must not reorder or drop anything — it sits in front of
    every AI answer the product gives."""
    monkeypatch.setattr(ask, "_HEARTBEAT_SECS", 5)
    monkeypatch.setattr(ask, "_require_ai_client", lambda: None)

    expected = [f'data: {{"type":"token","content":"{i}"}}\n\n' for i in range(50)]

    def fake_stream(**kwargs):
        yield from expected

    import services.ai_router as ai_router
    monkeypatch.setattr(ai_router, "handle_stream", fake_stream)

    out = _drain(ask.ask_ai_stream(ask.Prompt(message="hi", session_id=None),
                                 {"id": 1, "username": "u"}, {}))
    assert out == expected


def test_a_pipeline_error_is_not_swallowed_into_silence(monkeypatch):
    """If something escapes handle_stream, the connection must fail loudly. A
    silent close is indistinguishable from a dropped proxy connection, and the
    client would render it as the eternal spinner this work removes."""
    monkeypatch.setattr(ask, "_HEARTBEAT_SECS", 5)
    monkeypatch.setattr(ask, "_require_ai_client", lambda: None)

    def fake_stream(**kwargs):
        yield 'data: {"type":"token","content":"partial"}\n\n'
        raise RuntimeError("pipeline exploded")

    import services.ai_router as ai_router
    monkeypatch.setattr(ai_router, "handle_stream", fake_stream)

    body = ask.ask_ai_stream(ask.Prompt(message="hi", session_id=None),
                             {"id": 1, "username": "u"}, {})
    with pytest.raises(RuntimeError, match="pipeline exploded"):
        _drain(body)
