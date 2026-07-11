"""
services/llm_provider.py — provider abstraction with ordered fallback (AI Phase 0).
==================================================================================
Why (REVIEW_2 §1 debt #2): every LLM call site uses a single provider (Groq).
One Groq outage/ratelimit kills the flagship AI features for every merchant.
Keys for 4 providers already sit in .env; nothing used them.

This adds a *transparent* resilience layer:

    primary (Groq)  ──fails──►  Gemini (OpenAI-compatible endpoint)  ──►  …

It is opt-in and OFF by default — with `LLM_FALLBACK_ENABLED` unset the app
behaves EXACTLY as before (make_groq_client returns a plain Groq client). Turn
it on and every one of the 8 call sites gains failover with zero call-site
changes, because `ResilientClient` mimics the OpenAI/Groq surface the code
already consumes: `client.chat.completions.create(...)` →
`resp.choices[0].message.content / .tool_calls`, `resp.usage`, and streaming
`chunk.choices[0].delta.content`.

Design notes
------------
* Failover is attempted per `create()` call. On a *retriable* error (timeout,
  connection, 429, or 5xx) we move to the next provider; on a 4xx client error
  (bad request) we do NOT — a different provider would fail the same way.
* Cross-provider tool loops work: messages produced by any provider (Groq
  pydantic objects OR our adapter objects) are normalized back to OpenAI dicts
  before the next request, so a loop that started on Groq can finish on Gemini.
* Streaming: only the primary streams natively. If it fails and a non-streaming
  fallback answers, we wrap the reply in a single-chunk generator that matches
  the streaming contract (one token chunk + a usage-bearing final chunk). The
  UX degrades from token-by-token to one chunk — but the feature still works.

Env
---
  LLM_FALLBACK_ENABLED     "1" to enable (default off)
  LLM_FALLBACK_PROVIDERS   comma list after groq (default "gemini")
  LLM_FALLBACK_TIMEOUT_SECS per-request timeout for fallbacks (default 60)
  GEMINI_API_KEY           key for the gemini fallback
  GEMINI_BASE_URL          default https://generativelanguage.googleapis.com/v1beta/openai
  GEMINI_FALLBACK_MODEL    default "gemini-2.0-flash"
  OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_FALLBACK_MODEL   optional "openai" provider
"""
import os
import json
import logging
from types import SimpleNamespace

logger = logging.getLogger("bizassist.llm_provider")

_FALLBACK_TIMEOUT = float(os.getenv("LLM_FALLBACK_TIMEOUT_SECS", "60"))


# ── Response adapter objects (mirror the Groq/OpenAI SDK surface) ─────────────

class _Fn:
    __slots__ = ("name", "arguments")

    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    __slots__ = ("id", "type", "function")

    def __init__(self, id, name, arguments):
        self.id = id
        self.type = "function"
        self.function = _Fn(name, arguments)

    def _dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name,
                             "arguments": self.function.arguments}}


class _Message:
    """Assistant message that round-trips back into a messages list."""
    __slots__ = ("role", "content", "tool_calls")

    def __init__(self, content, tool_calls=None):
        self.role = "assistant"
        self.content = content
        self.tool_calls = tool_calls or None

    # normalization hook used by _to_openai_message()
    def model_dump(self, *a, **k):
        d = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [tc._dump() for tc in self.tool_calls]
        return d


class _Choice:
    __slots__ = ("message", "delta", "index", "finish_reason")

    def __init__(self, message=None, delta=None):
        self.message = message
        self.delta = delta
        self.index = 0
        self.finish_reason = None


class _Response:
    __slots__ = ("choices", "usage")

    def __init__(self, choices, usage):
        self.choices = choices
        self.usage = usage


def _usage_obj(d):
    d = d or {}
    return SimpleNamespace(
        prompt_tokens=d.get("prompt_tokens", 0) or 0,
        completion_tokens=d.get("completion_tokens", 0) or 0,
        total_tokens=d.get("total_tokens", 0) or 0,
    )


# ── Message normalization (any provider's message → OpenAI dict) ─────────────

def _to_openai_message(m):
    if isinstance(m, dict):
        return m
    dump = getattr(m, "model_dump", None)
    if callable(dump):
        try:
            return {k: v for k, v in dump(exclude_none=True).items()} if _accepts_exclude_none(dump) \
                else dump()
        except TypeError:
            return dump()
    return {"role": getattr(m, "role", "assistant"),
            "content": getattr(m, "content", "") or ""}


def _accepts_exclude_none(fn):
    try:
        import inspect
        return "exclude_none" in inspect.signature(fn).parameters
    except (ValueError, TypeError):
        return False


def _normalize_messages(messages):
    return [_to_openai_message(m) for m in messages]


# ── Retriable-error classification ───────────────────────────────────────────

def _status_of(exc):
    return (getattr(exc, "status_code", None)
            or getattr(getattr(exc, "response", None), "status_code", None))


def _is_retriable(exc):
    """Retry on the *next* provider for transient failures; not for 4xx."""
    status = _status_of(exc)
    if status is not None:
        return status == 429 or status >= 500      # ratelimit / server error
    return True                                     # timeout / connection / unknown → try next


# ── Fallback provider: OpenAI-compatible HTTP (Gemini, OpenAI, …) ─────────────

class _OpenAICompatProvider:
    """Non-streaming OpenAI-compatible chat client over httpx (no new dep)."""

    supports_stream = False

    def __init__(self, name, base_url, api_key, model, timeout=_FALLBACK_TIMEOUT):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def create(self, **kwargs):
        import httpx
        body = {
            "model": self.model,                       # ignore the Groq model name
            "messages": _normalize_messages(kwargs.get("messages", [])),
        }
        for k in ("tools", "tool_choice", "temperature", "max_tokens", "response_format"):
            if kwargs.get(k) is not None:
                body[k] = kwargs[k]
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        with httpx.Client(timeout=self.timeout) as hc:
            r = hc.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        tcs = None
        if msg.get("tool_calls"):
            tcs = [_ToolCall(tc.get("id"),
                             (tc.get("function") or {}).get("name"),
                             (tc.get("function") or {}).get("arguments") or "{}")
                   for tc in msg["tool_calls"]]
        message = _Message(content=msg.get("content"), tool_calls=tcs)
        return _Response([_Choice(message=message)], _usage_obj(data.get("usage")))


# ── Single-chunk stream wrapper (streaming failover degradation) ─────────────

def _single_chunk_stream(response):
    """Yield a non-streamed reply as stream-shaped chunks so callers that
    expect `chunk.choices[0].delta.content` keep working."""
    text = ""
    try:
        text = response.choices[0].message.content or ""
    except Exception:
        text = ""
    yield _Response([_Choice(delta=SimpleNamespace(content=text))], None)
    yield _Response([], response.usage)               # usage-only final chunk


# ── The resilient client ─────────────────────────────────────────────────────

class _Completions:
    def __init__(self, client):
        self._client = client

    def create(self, **kwargs):
        return self._client._create(**kwargs)


class _Chat:
    def __init__(self, client):
        self.completions = _Completions(client)


class ResilientClient:
    """Ordered failover across providers. Mimics the Groq/OpenAI client surface."""

    def __init__(self, providers):
        # providers: list of objects with .name, .create(**kwargs), .supports_stream
        self._providers = [p for p in providers if p is not None]
        self.chat = _Chat(self)

    def _create(self, **kwargs):
        stream = bool(kwargs.get("stream"))
        last_exc = None
        tried = []
        for i, prov in enumerate(self._providers):
            is_primary = (i == 0)
            try:
                if stream and getattr(prov, "supports_stream", False):
                    return prov.create(**kwargs)
                if stream:
                    # non-streaming provider answering a stream request → degrade
                    ns = dict(kwargs)
                    ns.pop("stream", None)
                    ns.pop("stream_options", None)
                    resp = prov.create(**ns)
                    if not is_primary:
                        logger.warning("[LLM] streamed via non-stream fallback '%s'", prov.name)
                    return _single_chunk_stream(resp)
                resp = prov.create(**kwargs)
                if not is_primary:
                    logger.warning("[LLM] answered via fallback '%s' after %s failed",
                                   prov.name, ", ".join(tried))
                return resp
            except Exception as e:      # noqa: BLE001 — deliberate: classify then decide
                tried.append(getattr(prov, "name", f"p{i}"))
                last_exc = e
                if not _is_retriable(e):
                    logger.error("[LLM] non-retriable error on '%s': %s", prov.name, e)
                    raise
                logger.warning("[LLM] provider '%s' failed (%s) — trying next", prov.name, e)
                continue
        # exhausted
        if last_exc:
            raise last_exc
        raise RuntimeError("No LLM providers configured")


# ── Factory ──────────────────────────────────────────────────────────────────

def _build_fallback_providers():
    out = []
    wanted = [p.strip().lower() for p in
              os.getenv("LLM_FALLBACK_PROVIDERS", "gemini").split(",") if p.strip()]
    for name in wanted:
        if name == "gemini":
            key = os.getenv("GEMINI_API_KEY")
            if not key:
                logger.info("[LLM] gemini fallback skipped — no GEMINI_API_KEY")
                continue
            out.append(_OpenAICompatProvider(
                "gemini",
                os.getenv("GEMINI_BASE_URL",
                          "https://generativelanguage.googleapis.com/v1beta/openai"),
                key,
                os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.0-flash"),
            ))
        elif name == "openai":
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                logger.info("[LLM] openai fallback skipped — no OPENAI_API_KEY")
                continue
            out.append(_OpenAICompatProvider(
                "openai",
                os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                key,
                os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4o-mini"),
            ))
        else:
            logger.warning("[LLM] unknown fallback provider '%s' — ignored", name)
    return out


def fallback_enabled() -> bool:
    return os.getenv("LLM_FALLBACK_ENABLED", "0") == "1"


def wrap_with_fallback(primary_client):
    """Wrap an existing (Groq) client with ordered fallbacks. If no fallbacks
    are available, returns the primary untouched (zero overhead)."""
    class _PrimaryAdapter:
        name = "groq"
        supports_stream = True

        def __init__(self, c):
            self._c = c

        def create(self, **kwargs):
            return self._c.chat.completions.create(**kwargs)

    fallbacks = _build_fallback_providers()
    if not fallbacks:
        return primary_client
    logger.info("[LLM] fallback chain: groq → %s",
                " → ".join(p.name for p in fallbacks))
    return ResilientClient([_PrimaryAdapter(primary_client), *fallbacks])
