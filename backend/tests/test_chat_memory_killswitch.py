"""
tests/test_chat_memory_killswitch.py
====================================
Chat memory must never be able to take the product down.

Observed 2026-08-07, twice: a request reached `[CHROMA] Initialized persistent
client` and the ENTIRE backend stopped. Not the request — the process. No
further log lines at all, including the sync worker that had been running every
15 s and the scheduled jobs. The port stayed open; nothing ever answered.

The block is in the persisted HNSW segment, in native code, holding the GIL:
`faulthandler.dump_traceback_later(45, exit=True)` armed on another thread never
fired. Nothing written in Python can rescue that — no timeout, no thread, no
`except` — because no bytecode runs anywhere in the process until the native
call returns. Evidence it is contention rather than corruption: a sibling
collection on the same client answered in 0.17 s throughout, and the moment
uvicorn's --reload respawned the frozen worker, an independent probe of the
*same* collection returned in 0.10 s.

What chat memory buys is semantic recall of past conversations, injected into
AI_SIMPLE prompts. That is a nice-to-have. It is not worth the whole backend, so
it gets a switch that works without a code change or a redeploy.
"""
import importlib
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest                                    # noqa: E402


@pytest.fixture
def embeddings_off(monkeypatch):
    monkeypatch.setenv("CHAT_MEMORY_ENABLED", "0")   # explicit, though it is the default
    import services.embeddings as E
    importlib.reload(E)
    yield E
    monkeypatch.delenv("CHAT_MEMORY_ENABLED", raising=False)
    importlib.reload(E)


def test_disabled_memory_writes_nothing_and_touches_no_index(embeddings_off, monkeypatch):
    """The write path is the one that froze. With the switch off it must return
    before reaching Chroma at all — not reach it and swallow an error, which
    would still hang."""
    called = []
    monkeypatch.setattr(embeddings_off, "get_chat_memory_collection",
                        lambda: called.append(1))
    embeddings_off.save_chat_memory(
        business_id=1, session_id="s", session_title="t",
        user_query="q", assistant_response="a")
    assert called == [], "the collection was opened despite the kill switch"


def test_disabled_memory_reads_return_empty_context(embeddings_off, monkeypatch):
    called = []
    monkeypatch.setattr(embeddings_off, "get_chat_memory_collection",
                        lambda: called.append(1))
    assert embeddings_off.search_chat_memories(1, "anything") == ""
    assert called == []


def test_memory_is_off_by_default():
    """This assertion is the reverse of the one it replaces.

    The switch first shipped defaulting ON, arguing that off-by-default would
    silently weaken AI answers. Then the freeze reproduced on demand — with the
    server worker holding the index, an independent process blocks on that
    collection every time, verified against the raw chromadb collection so it is
    not our wrapper.

    Weighed honestly: ON risks a total silent outage (port open, requests
    accepted, nothing ever answered, no error logged); OFF costs semantic recall
    of past chats in AI_SIMPLE prompts, and nothing else. A nice-to-have that can
    hang the application is not a default."""
    import services.embeddings as E
    importlib.reload(E)
    assert E.CHAT_MEMORY_ENABLED is False


def test_only_an_explicit_one_enables_it():
    """Opting in to a feature that can freeze the process must be deliberate —
    a typo or a leftover value must not switch it on."""
    import services.embeddings as E
    for value, expected in (("1", True), ("0", False), ("", False),
                            ("true", False), ("yes", False)):
        os.environ["CHAT_MEMORY_ENABLED"] = value
        importlib.reload(E)
        assert E.CHAT_MEMORY_ENABLED is expected, f"CHAT_MEMORY_ENABLED={value!r}"
    os.environ.pop("CHAT_MEMORY_ENABLED", None)
    importlib.reload(E)


def test_writes_are_serialised_within_the_process():
    """The lock cannot help across processes — that is what the kill switch is
    for — but request threads, the scheduler and the sync worker all reach this
    index, and that much this process does control."""
    import services.embeddings as E
    importlib.reload(E)
    assert hasattr(E, "_chroma_lock")
    assert E._chroma_lock.acquire(blocking=False)
    E._chroma_lock.release()
