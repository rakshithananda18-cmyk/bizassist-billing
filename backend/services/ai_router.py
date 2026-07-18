"""
services/ai_router.py
=====================
Core business logic for the /ask endpoint.

Handles the full 4-tier routing pipeline:
  CONVERSATIONAL → short reply, no data
  DIRECT         → DB handler, 0 tokens
  CACHE          → cached AI response
  AI_SIMPLE      → Groq tool-calling, small model
  AI_COMPLEX     → LangGraph multi-agent, large model

Called by routes/ask.py -- keeps the FastAPI route thin.

ARCHITECTURE (Phase 0 unification)
----------------------------------
There is ONE pipeline: `process_query()`, a generator that yields semantic
events. The two public entry points are thin adapters over it:

  handle()         → drains the generator, returns a single JSON envelope (/ask)
  handle_stream()  → forwards the events as SSE strings           (/ask/stream)

`process_query(..., stream=False)` produces instant/non-streamed answers;
`stream=True` streams tokens. Everything else — session resolution, history,
classification, rate limiting, cache, DIRECT, intent-first, token accounting,
logging, response assembly — is written exactly once. No more drift between the
two paths.
"""
import json
import logging
import os
import re
import hashlib
import uuid
from datetime import date
from typing import Optional

from groq import Groq
from sqlalchemy import func

from services.query_router import classify, _WRITING_ACTIONS
from services.direct_query_handler import (
    handle as direct_handle, _extract_customer_name, _customer_candidates, CUSTOMER_NOT_FOUND,
)
from services.recommendations import recommend, get_business_snapshot, detect_anomalies
from services.feedback_service import get_override
from services.context_cache import get_focused_context, get_cached_query_response, set_cached_query_response
from services.tools import execute_tool, schemas as tool_schemas
from services.embeddings import search_chat_memories, save_chat_memory
from services.agent_graph import run_agent_graph, run_agent_graph_stream
from services.rate_limiter import check_rate_limit
from services.errors import AskError, ask_error
from services.dates import parse_date
from services.intent_router import classify as _semantic_classify
from services.charts import build_chart_data
from database.db import SessionLocal
from database.models import Invoice, ChatMessage

logger = logging.getLogger("bizassist.ai_router")
# ─────────────────────────────────────────────────────────────────────────────
# SPLIT MODULES (MASTER_REVIEW §2.5) — decision / cache / execution
# ─────────────────────────────────────────────────────────────────────────────
# The helpers below were extracted verbatim into three focused modules. They
# are re-imported here so (a) `process_query` keeps referencing them as module
# globals and (b) every existing import/patch target on `services.ai_router`
# (tests, routes) keeps working unchanged.
from services.ai_router_decision import (   # noqa: F401
    _INTENT_DIRECT, _detect_topic, _AGGREGATE_HANDLERS,
    _LLM_CONF_FLOOR, _CUSTOMER_SCOPED, _LLM_FASTPATH_HANDLERS,
    _resolve_llm_decision, _MULTI_SIGNAL, _INVOICE_ID_RE, _INVOICE_LIST_SIGNAL,
    _maybe_entity_first, _maybe_shadow_route,
)
from services.ai_router_cache import (      # noqa: F401
    _safe_int, _cache_salt, _cache_disc,
)
from services.ai_router_execution import (  # noqa: F401
    MODEL_SIMPLE, MODEL_COMPLEX, _MAX_TOOL_CHARS,
    _log_token_usage, _SESSION_PLACEHOLDER, _GREETING_RE,
    _is_titleable, _title_from, _UsageEstimate, _stream_deltas,
    _resolve_session, _fetch_history, _log_chat, _NO_POLISH, _polish,
    _AI_SIMPLE_SYSTEM_PROMPT, _CONVERSATIONAL_SYSTEM_PROMPT,
    _ADVISE_SYSTEM_PROMPT, _build_ai_simple_messages,
)


# ─────────────────────────────────────────────────────────────────────────────
# THE ONE PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def process_query(prompt_message: str, session_id_in: Optional[str],
                  current_user: dict, client, *, stream: bool):
    """
    The single routing pipeline shared by /ask and /ask/stream.

    Yields event dicts:
      {"type": "status",  "content": str}            progress text (streamed UIs)
      {"type": "replace", "content": str}            full content for instant answers
      {"type": "token",   "content": str}            streamed delta (stream=True only)
      {"type": "raw_sse", "data": str}               pre-formatted SSE (agent graph)
      {"type": "final",   "envelope": dict}          the complete response envelope
      {"type": "error",   "message": str, "status_code": int, ...}

    `handle()` keeps only the final envelope; `handle_stream()` forwards each
    event as SSE. The envelope ALWAYS carries the full markdown + real token
    totals, so the non-stream path no longer reports tokens:0.
    """
    user_query     = prompt_message.strip()
    active_user_id = current_user["id"]
    acc            = {"in": 0, "out": 0}   # per-request token accumulator (real truth)

    session_id    = session_id_in or str(uuid.uuid4())
    session_title = _resolve_session(active_user_id, session_id, user_query)
    history       = _fetch_history(active_user_id, session_id)

    # ── Layer 1: classify ───────────────────────────────────────────
    route, handler_key = classify(user_query, has_history=len(history) > 0)
    # Entity-first: a short query that names a known customer → client lookup,
    # before a stray keyword ("fresh") can misroute it.
    route, handler_key = _maybe_entity_first(route, handler_key, user_query, active_user_id)

    # User correction override (feedback loop): if this user marked this exact
    # query wrong and told us the right intent, honour it above all routing.
    _override = get_override(active_user_id, user_query)
    if _override:
        route, handler_key = _override
        logger.info(f"[ROUTER] override → {route}/{handler_key} q='{user_query[:60]}'")

    # ── NEXT-GEN ROUTER SWITCH (LLM_ROUTER=on) ──────────────────────
    # When ON, the LLM router's decision REPLACES the legacy one (a user's
    # explicit override still wins). On ANY failure it returns None and the
    # legacy decision above stands — legacy is the permanent safety net.
    # New tiers it can produce: AI_ADVISE (data + grounded advice) and
    # ACTION (gated preview — never auto-executed), handled below.
    from services.router_mode import get_mode as _router_mode, pretty as _router_pretty
    _rmode = _router_mode()            # legacy(off) | shadow | new(on) — resolved ONCE
    _llm_decision = None
    _llm_entities = {}                 # extracted hints we actually honor (B2/B3/B4)
    # B6: legacy already matched an exact dashboard template → it's deterministic,
    # so skip the LLM router's extra 1-2s call (it only agrees with these).
    _llm_skip = (route == "DIRECT" and handler_key in _LLM_FASTPATH_HANDLERS)
    if _rmode == "on" and _llm_skip:
        logger.debug(f"[ROUTER] llm skipped (deterministic fastpath {handler_key}) q='{user_query[:60]}'")
    if _override is None and _rmode == "on" and not _llm_skip:
        logger.debug(f"[ROUTER] invoking llm router (mode=on, floor={_LLM_CONF_FLOOR}) q='{user_query[:60]}'")
        try:
            from services.llm_router import route as _llm_route
            _r = _llm_route(user_query, client=client, business_id=active_user_id)
            if _r is not None:
                _, _, _decision = _r
                _new_route, _new_handler, _ents, _accepted = _resolve_llm_decision(
                    _decision, route, handler_key)
                if not _accepted:
                    logger.info(f"[ROUTER] llm conf {_decision.confidence:.2f} < floor "
                                f"{_LLM_CONF_FLOOR} → keep legacy {route}/{handler_key} "
                                f"q='{user_query[:60]}'")
                else:
                    _llm_decision = _decision
                    _llm_entities = _ents
                    logger.info(f"[ROUTER] llm → {_new_route}/{_new_handler} "
                                f"(legacy was {route}/{handler_key}) q='{user_query[:60]}'")
                    route, handler_key = _new_route, _new_handler
        except Exception as _le:
            logger.warning(f"[ROUTER] llm route failed, legacy stands: {_le}")

    # ── Rate limit ──────────────────────────────────────────────────
    rl = check_rate_limit(active_user_id, route)
    if not rl["allowed"]:
        logger.warning(f"[RATELIMIT] Blocked user {active_user_id}: {rl['reason']}")
        yield {
            "type": "error", "message": rl["reason"], "status_code": 429,
            "limit": rl.get("limit"), "used": rl.get("used"),
            "retry_after": rl.get("retry_after"),
        }
        return

    # Cache salt: AI_COMPLEX keys on exact query (data-driven); everything else
    # keys on topic so "show overdue" and "who owes me" share one entry.
    _pre_topic   = _detect_topic(user_query)
    _is_writing  = bool(_WRITING_ACTIONS.search(user_query))   # "draft/write a reminder…"
    # AI_ADVISE keys on the exact query (advice for "loyalty offers" must not be
    # served to a different advice question that shares the topic). Compute the
    # effective flag ONCE so the salt and the debug log lines agree (B7 — the REQ
    # line used to print the topic-keyed disc for AI_ADVISE).
    _eff_writing = _is_writing or route == "AI_ADVISE"
    history_salt = _cache_salt(active_user_id, route, user_query, _pre_topic,
                               handler_key, is_writing=_eff_writing)

    # Full routing+cache context for root-cause debugging (LOG_LEVEL=DEBUG). This
    # is the line that makes cache-collision bugs obvious: if `handler` and
    # `cache_disc` disagree for a DIRECT query, two intents are sharing a key.
    # One INFO line per request, ALIGNED with the response: rid + router mode +
    # final route/handler. Grep "[REQ" to trace exactly which router (legacy /
    # shadow / new) produced any answer, even across live mode switches.
    rid = uuid.uuid4().hex[:8]
    logger.info(
        f"[REQ {rid}] router={_router_pretty(_rmode)} user={active_user_id} "
        f"route={route} handler={handler_key} topic={_pre_topic} writing={_is_writing} "
        f"cache_disc='{_cache_disc(route, user_query, _pre_topic, handler_key, _eff_writing)}' "
        f"q='{user_query[:100]}'"
    )

    # Phase 1 shadow routing (no-op unless INTENT_ROUTER=shadow|on) — gathers
    # semantic-vs-regex agreement data on real traffic without changing routing.
    _maybe_shadow_route(user_query, route, handler_key, _pre_topic)

    # Next-gen LLM router shadow (services/llm_router.py — NEW parallel system).
    # No-op unless LLM_ROUTER=shadow. Runs in a background thread (zero added
    # latency) AFTER the legacy decision and changes NOTHING — it only logs
    # '[ROUTER][llm-shadow] …' lines for analyze_llm_shadow.py.
    if _rmode == "shadow":
        try:
            from services.llm_router import shadow_compare as _llm_shadow
            _llm_shadow(user_query, route, handler_key, _pre_topic,
                        business_id=active_user_id)
        except Exception as _le:
            logger.debug(f"[ROUTER][llm-shadow] skipped: {_le}")

    # ── Layer 1.5: CONVERSATIONAL short-circuit ─────────────────────
    if route == "CONVERSATIONAL":
        logger.info(f"[CONVERSATIONAL] '{user_query}'")
        conv_messages = [
            {"role": "system", "content": _CONVERSATIONAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_query},
        ]
        if stream:
            full = ""
            for delta in _stream_deltas(client, conv_messages, MODEL_SIMPLE,
                                        active_user_id, "CONVERSATIONAL", acc,
                                        temperature=0.5, max_tokens=80):
                full += delta
                yield {"type": "token", "content": delta}
        else:
            resp = client.chat.completions.create(
                messages=conv_messages, model=MODEL_SIMPLE,
                temperature=0.5, max_tokens=80,
            )
            full = (resp.choices[0].message.content or "Got it!").strip()
            _log_token_usage(active_user_id, MODEL_SIMPLE, "CONVERSATIONAL", getattr(resp, "usage", None), acc)

        _log_chat(active_user_id, user_query, full, session_id, session_title,
                  source="conversational", remember=False)
        yield {"type": "final", "envelope": {
            "answer":        {"markdown": full, "title": ""},
            "response":      full,
            "source":        "conversational",
            "suggestions":   [],
            "session_id":    session_id,
            "session_title": session_title,
            "meta": {"tokens": acc["in"] + acc["out"], "model": MODEL_SIMPLE,
                     "model_tier": "CONVERSATIONAL", "cached": False},
        }}
        return

    # ── ACTION (LLM router only): gated preview, NEVER auto-executed ─
    # "Escalate 90+ days" must return a confirm chip, not a hallucinated "Done."
    if route == "ACTION":
        _action = getattr(_llm_decision, "action", None)
        _ents   = _llm_entities or (getattr(_llm_decision, "entities", {}) or {})
        markdown = "I can't run that automatically yet — here's what I found instead."
        suggestions = []
        try:
            from services.actions import is_action as _is_action, preview as _a_preview
            if _action and _is_action(_action):
                prev = _a_preview(_action, active_user_id, _ents)
                nice = _action.replace("_", " ")
                summary = (prev or {}).get("summary", "")
                markdown = (f"I can **{nice}** for you. Nothing is sent or changed "
                            f"until you confirm.\n\n{summary}".strip())
                suggestions = [{
                    "id": _action, "label": f"Preview & confirm: {nice}",
                    "type": "action", "action": _action, "confirm": True,
                    "params": _ents, "icon": "bell",
                }]
        except Exception as _ae:
            logger.warning(f"[ACTION] preview failed: {_ae}")
        _log_chat(active_user_id, user_query, markdown, session_id, session_title,
                  source="action", remember=False)
        yield {"type": "replace", "content": markdown}
        yield {"type": "final", "envelope": {
            "answer":        {"markdown": markdown, "title": ""},
            "response":      markdown,
            "source":        "action",
            "suggestions":   suggestions,
            "alerts":        [],
            "chart":         None,
            "session_id":    session_id,
            "session_title": session_title,
            "meta": {"tokens": acc["in"] + acc["out"], "model": MODEL_SIMPLE,
                     "model_tier": "ACTION", "cached": False},
        }}
        return

    # ── Layer 2: universal cache check ──────────────────────────────
    cached = get_cached_query_response(active_user_id, user_query, history_salt)
    if cached:
        logger.info(f"[CACHE] HIT [REQ {rid}] source={cached.get('source','?')} "
                    f"disc='{_cache_disc(route, user_query, _pre_topic, handler_key, _eff_writing)}' query='{user_query[:80]}'")
        markdown = cached.get("answer", {}).get("markdown") or cached.get("response", "")
        _log_chat(active_user_id, user_query, markdown, session_id, session_title,
                  source=cached.get("source", "ai"), model_tier=cached.get("model_tier"),
                  cached=True, remember=False)
        envelope = {
            "answer":        {"markdown": markdown, "title": ""},
            "response":      markdown,
            "source":        cached.get("source", "ai"),
            "suggestions":   cached.get("suggestions", []),
            "alerts":        cached.get("alerts", []),
            "chart":         cached.get("chart"),
            "session_id":    session_id,
            "session_title": session_title,
            "meta": {
                "tokens":     0,
                "cached":     True,
                "model":      cached.get("meta", {}).get("model") or cached.get("model_used"),
                "model_tier": cached.get("meta", {}).get("model_tier") or cached.get("model_tier"),
            },
        }
        yield {"type": "replace", "content": markdown}
        yield {"type": "final", "envelope": envelope}
        return

    # ── AI_ADVISE (LLM router only): real data + grounded advice ────
    # "Suggest loyalty offers for my top customers" → fetch the top-customers
    # data, then ask the 8B for advice grounded ON that data. Fixes the
    # advice-questions-get-raw-tables bug.
    if route == "AI_ADVISE":
        data_md = None
        if handler_key:
            try:
                data_md = direct_handle(handler_key, user_query, active_user_id, params=_llm_entities)
            except Exception as _de:
                logger.debug(f"[ADVISE] data fetch failed: {_de}")
        if data_md and data_md != CUSTOMER_NOT_FOUND:
            # B5: collection/DSO advice ("why is my collection rate low") needs
            # real names to be specific — enrich with the actual top-debtors so
            # the model cites them instead of inventing an example customer.
            if handler_key in ("dso_summary", "overdue_amount", "total_revenue"):
                try:
                    _debtors_md = direct_handle("top_debtors", user_query, active_user_id)
                    if _debtors_md:
                        data_md = f"{data_md}\n\n--- YOUR TOP DEBTORS (real) ---\n{_debtors_md}"
                except Exception:
                    pass
            logger.info(f"[ADVISE] grounding on handler={handler_key} | '{user_query[:60]}'")
            advise_messages = [
                {"role": "system", "content": _ADVISE_SYSTEM_PROMPT},
                {"role": "user", "content":
                    f"QUESTION: {user_query}\n\nTHEIR REAL BUSINESS DATA:\n{data_md[:3500]}"},
            ]
            if stream:
                yield {"type": "status", "content": "Reading your data…"}
                full_text = ""
                for delta in _stream_deltas(client, advise_messages, MODEL_SIMPLE,
                                            active_user_id, "AI_ADVISE", acc,
                                            temperature=0.3, max_tokens=700):
                    full_text += delta
                    yield {"type": "token", "content": delta}
            else:
                _ar = client.chat.completions.create(
                    messages=advise_messages, model=MODEL_SIMPLE,
                    temperature=0.3, max_tokens=700,
                )
                _log_token_usage(active_user_id, MODEL_SIMPLE, "AI_ADVISE",
                                 getattr(_ar, "usage", None), acc)
                full_text = (_ar.choices[0].message.content or "").strip()
            recs      = recommend(handler_key, active_user_id)
            anomalies = detect_anomalies(active_user_id)
            envelope = {
                "answer":        {"markdown": full_text, "title": ""},
                "response":      full_text,
                "source":        "advice",
                "suggestions":   recs,
                "alerts":        anomalies,
                "chart":         None,
                "session_id":    session_id,
                "session_title": session_title,
                "meta": {"tokens": acc["in"] + acc["out"], "model": MODEL_SIMPLE,
                         "model_tier": "AI_ADVISE", "cached": False},
            }
            set_cached_query_response(active_user_id, user_query, envelope, history_salt)
            _log_chat(active_user_id, user_query, full_text, session_id, session_title,
                      source="advice", model_tier="AI_ADVISE")
            yield {"type": "final", "envelope": envelope}
            return
        # No grounding data → plain AI_SIMPLE (tool-calling) handles it below.
        route, handler_key = "AI_SIMPLE", None

    # ── Layer 2.5: DIRECT DB answer → polish → cache ────────────────
    if route == "DIRECT":
        answer = direct_handle(handler_key, user_query, active_user_id, params=_llm_entities)
        if answer:
            logger.info(f"[DIRECT] handler={handler_key} | '{user_query}'")
            # Honest "customer not found" — return verbatim. Don't polish (the LLM
            # would re-invent a client card). Offer near-miss customers as "did you
            # mean" chips so the user can pick the one they meant.
            if answer == CUSTOMER_NOT_FOUND:
                cands = _customer_candidates(user_query, active_user_id)
                if cands:
                    chips = [{
                        "id":     f"didyoumean_{c}",
                        "label":  c,
                        "type":   "ai",
                        "prompt": f"tell me about {c}",
                        "icon":   "users",
                    } for c in cands]
                    answer = "I couldn't find an exact match. Did you mean one of these?"
                    logger.info(f"[DIRECT] client_summary not found → {len(cands)} suggestion(s) q='{user_query}'")
                else:
                    chips = []
                envelope = {
                    "answer":        {"markdown": answer, "title": ""},
                    "response":      answer,
                    "source":        "db",
                    "suggestions":   chips,
                    "alerts":        [],
                    "chart":         None,
                    "session_id":    session_id,
                    "session_title": session_title,
                    "meta": {"tokens": 0, "model": MODEL_SIMPLE,
                             "model_tier": "DIRECT", "cached": False},
                }
                _log_chat(active_user_id, user_query, answer, session_id, session_title,
                          source="db", remember=False)
                yield {"type": "replace", "content": answer}
                yield {"type": "final", "envelope": envelope}
                return
            # No per-answer "insight" bulb — it confabulated on factual data and
            # added little value. Real advice now lives in the dedicated Smart
            # Insights advisor (services/smart_insights.py, the chip-bar feature).
            # DIRECT answers return their clean DB data; deterministic alert chips
            # (cash-flow / expiry) still come from detect_anomalies below.
            polished   = answer
            recs       = recommend(handler_key, active_user_id)
            # On a single-invoice view, offer the "Mark as paid" action (gated:
            # preview → confirm → execute; it no-ops if already Paid).
            if handler_key == "invoice_detail":
                recs = [{"id": "mark_paid", "label": "Mark as paid", "type": "action",
                         "action": "mark_invoice_paid", "confirm": True,
                         "params": {"query": user_query}, "icon": "check"}] + (recs or [])
            anomalies  = detect_anomalies(active_user_id)
            # ONE grounded, query-scoped insight (deterministic snapshot math,
            # no LLM) — the trustworthy successor to the removed bulb. None when
            # there's nothing relevant to add.
            ctx_insight = None
            try:
                from services.smart_insights import contextual_insight
                ctx_insight = contextual_insight(active_user_id, handler_key)
            except Exception as _ci_e:
                logger.debug(f"[DIRECT] contextual_insight skipped: {_ci_e}")
            envelope = {
                "answer":        {"markdown": polished, "title": ""},
                "response":      polished,
                "source":        "db",
                "suggestions":   recs,
                "alerts":        anomalies,
                "chart":         None,
                "insight":       ctx_insight,
                "session_id":    session_id,
                "session_title": session_title,
                "meta": {"tokens": acc["in"] + acc["out"], "model": MODEL_SIMPLE,
                         "model_tier": "DIRECT", "cached": False},
            }
            set_cached_query_response(active_user_id, user_query, envelope, history_salt)
            _log_chat(active_user_id, user_query, polished, session_id, session_title, source="db")
            yield {"type": "replace", "content": polished}
            yield {"type": "final", "envelope": envelope}
            return
        # handler returned None (DB error) → fall through to AI

    # ── Layer 2.7: intent-first promotion (AI_SIMPLE + known topic) ─
    if route == "AI_SIMPLE" and not _is_writing and _pre_topic in _INTENT_DIRECT:
        try:
            from services.intents import resolve_intent
            _ir = resolve_intent(_pre_topic, active_user_id)
            if _ir and _ir.get("answer", {}).get("markdown"):
                logger.info(f"[INTENT] Promoted AI_SIMPLE → DIRECT via topic={_pre_topic}")
                raw_md    = _ir["answer"]["markdown"]
                polished  = raw_md   # no insight bulb — see Smart Insights advisor
                anomalies = detect_anomalies(active_user_id)
                chart     = build_chart_data(user_query, active_user_id)
                recs      = _ir.get("suggestions", recommend(_pre_topic, active_user_id))
                envelope = {
                    "answer":        {"markdown": polished, "title": ""},
                    "response":      polished,
                    "source":        "intent",
                    "suggestions":   recs,
                    "alerts":        anomalies,
                    "chart":         chart,
                    "session_id":    session_id,
                    "session_title": session_title,
                    "meta": {"tokens": acc["in"] + acc["out"], "model": MODEL_SIMPLE,
                             "model_tier": "INTENT", "cached": False},
                }
                set_cached_query_response(active_user_id, user_query, envelope, history_salt)
                _log_chat(active_user_id, user_query, polished, session_id, session_title, source="db")
                yield {"type": "replace", "content": polished}
                yield {"type": "final", "envelope": envelope}
                return
        except Exception as _ie:
            logger.debug(f"[INTENT] Fallback to AI: {_ie}")

    # ── Layer 3a: AI_COMPLEX → LangGraph multi-agent ────────────────
    tool_calls_made = None
    if route == "AI_COMPLEX":
        _agent_mode = os.getenv("AGENT_MODE", "pipeline").lower()
        logger.info(f"[AI_COMPLEX] {'agent-loop' if _agent_mode == 'loop' else 'LangGraph agents'} "
                    f"| '{user_query}'")
        if stream:
            full_text = ""
            for event_str in run_agent_graph_stream(user_query, active_user_id, history, detected_topic=_pre_topic):
                try:
                    evt = json.loads(event_str[6:])  # strip "data: "
                    if evt.get("type") == "ag_done":
                        full_text = evt.get("full_text", "")
                        _toks = evt.get("tokens") or {}
                        acc["in"]  += _safe_int(_toks.get("input"))
                        acc["out"] += _safe_int(_toks.get("output"))
                        continue  # don't forward ag_done to the client
                except Exception:
                    pass
                yield {"type": "raw_sse", "data": event_str}
        else:
            _ag = run_agent_graph(
                user_query=user_query, business_id=active_user_id, history=history,
                detected_topic=_pre_topic
            )
            # run_agent_graph returns {text, tokens_in, tokens_out}; tolerate a bare
            # string too (older callers / test mocks).
            if isinstance(_ag, dict):
                full_text  = _ag.get("text", "")
                acc["in"]  += _safe_int(_ag.get("tokens_in"))
                acc["out"] += _safe_int(_ag.get("tokens_out"))
            else:
                full_text = _ag or ""
        selected_model = MODEL_COMPLEX

    # ── Layer 3b: AI_SIMPLE → tool-calling agent ────────────────────
    else:
        selected_model = MODEL_SIMPLE
        logger.info(f"[AI_SIMPLE] model={selected_model} | '{user_query}'")
        if stream:
            yield {"type": "status", "content": "Fetching your business data…"}

        messages   = _build_ai_simple_messages(user_query, history, active_user_id)
        completion = client.chat.completions.create(
            messages=messages, model=selected_model,
            temperature=0.1, max_tokens=800,
            tools=tool_schemas, tool_choice="auto",
        )
        _log_token_usage(active_user_id, selected_model, "AI_SIMPLE", completion.usage, acc)
        resp_msg        = completion.choices[0].message
        tool_calls      = resp_msg.tool_calls
        tool_calls_made = tool_calls

        if tool_calls:
            messages.append(resp_msg)
            for tc in tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments or "{}")
                tr      = execute_tool(fn_name, fn_args, active_user_id)
                if isinstance(tr, str) and len(tr) > _MAX_TOOL_CHARS:
                    logger.info(f"[AI_SIMPLE] tool '{fn_name}' result {len(tr)} chars → "
                                f"truncated to {_MAX_TOOL_CHARS} (token budget)")
                    tr = tr[:_MAX_TOOL_CHARS] + "\n…[truncated to fit the model's token budget]"
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "name": fn_name, "content": tr})
            if stream:
                full_text = ""
                for delta in _stream_deltas(client, messages, selected_model,
                                            active_user_id, "AI_SIMPLE", acc,
                                            temperature=0.1, max_tokens=800):
                    full_text += delta
                    yield {"type": "token", "content": delta}
            else:
                second = client.chat.completions.create(
                    messages=messages, model=selected_model,
                    temperature=0.1, max_tokens=800,
                )
                _log_token_usage(active_user_id, selected_model, "AI_SIMPLE", second.usage, acc)
                full_text = second.choices[0].message.content or ""
        else:
            if stream:
                full_text = ""
                for delta in _stream_deltas(client, messages, selected_model,
                                            active_user_id, "AI_SIMPLE", acc,
                                            temperature=0.1, max_tokens=800):
                    full_text += delta
                    yield {"type": "token", "content": delta}
            else:
                full_text = resp_msg.content or ""

    # ── Shared: assemble + cache + log the AI envelope ──────────────
    chart       = build_chart_data(user_query, active_user_id)
    topic       = _detect_topic(user_query, tool_calls_made if route != "AI_COMPLEX" else None)
    suggestions = recommend(topic, active_user_id)
    anomalies   = detect_anomalies(active_user_id)

    envelope = {
        "answer":        {"markdown": full_text, "title": ""},
        "response":      full_text,
        "source":        "ai",
        "suggestions":   suggestions,
        "alerts":        anomalies,
        "chart":         chart,
        "session_id":    session_id,
        "session_title": session_title,
        "meta": {"tokens": acc["in"] + acc["out"], "model": selected_model,
                 "model_tier": route, "cached": False},
    }
    set_cached_query_response(active_user_id, user_query, envelope, history_salt)
    _log_chat(active_user_id, user_query, full_text, session_id, session_title,
              source="ai", model_tier=route)
    yield {"type": "final", "envelope": envelope}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC ENTRY POINTS  (thin adapters over process_query)
# ─────────────────────────────────────────────────────────────────────────────

_ERROR_CODES = {429: "rate_limited", 500: "internal_error"}


def _raise_pipeline_error(ev: dict):
    """Turn a pipeline 'error' event into a real HTTP error (H1)."""
    sc = ev.get("status_code", 500)
    raise ask_error(
        sc,
        _ERROR_CODES.get(sc, "error"),
        ev.get("message", "Request failed."),
        limit=ev.get("limit"),
        used=ev.get("used"),
        retry_after=ev.get("retry_after"),
    )


def handle(prompt_message: str, session_id_in: Optional[str], current_user: dict, client: Groq):
    """
    Non-streaming /ask endpoint. Drains the shared pipeline and returns one JSON
    envelope on success. On failure it raises AskError, which the app's exception
    handler renders with a real HTTP status code (no more 200-OK error bodies).
    Token totals in meta.tokens are real (no more tokens:0).
    """
    try:
        final_env = None
        error_ev  = None
        for ev in process_query(prompt_message, session_id_in, current_user, client, stream=False):
            t = ev["type"]
            if t == "error":
                error_ev = ev
                break
            if t == "final":
                final_env = ev["envelope"]
            # status / replace / token / raw_sse are irrelevant to the JSON path
    except Exception as e:
        error_str = str(e)
        logger.error(f"[ASK] Error handling request: {error_str}", exc_info=True)
        if "429" in error_str or "rate_limit" in error_str.lower() or "quota" in error_str.lower():
            raise ask_error(429, "quota_exceeded",
                            "API quota exceeded. Please wait a moment and try again.")
        raise ask_error(500, "internal_error",
                        "An internal error occurred while processing your request.")

    if error_ev is not None:
        _raise_pipeline_error(error_ev)
    if final_env is None:
        raise ask_error(500, "internal_error", "No response produced.")
    # Traceability: stamp WHICH router produced this answer into meta, and log a
    # [DONE] line that pairs with the request's [REQ] line (match on q=…).
    try:
        from services.router_mode import get_mode as _gm, pretty as _pp
        final_env.setdefault("meta", {})["router"] = _pp(_gm())
    except Exception:
        pass
    _m = final_env.get("meta", {})
    logger.info(
        f"[DONE] router={_m.get('router')} source={final_env.get('source')} "
        f"tier={_m.get('model_tier')} tokens={_m.get('tokens')} cached={_m.get('cached')} "
        f"q='{prompt_message.strip()[:80]}'"
    )
    return final_env


def handle_stream(prompt_message: str, session_id_in, current_user: dict, client):
    """
    SSE streaming /ask/stream endpoint. Forwards the shared pipeline's events.

    Event types emitted to the client:
      status  — progress text (dimmed, not part of the answer)
      token   — streamed token, append to the current message
      replace — full content for instant answers (DIRECT / CACHE / INTENT)
      done    — final metadata: source, meta, suggestions, alerts, chart, session
      error   — error payload
    """
    def _sse(event_type: str, **kwargs) -> str:
        return "data: " + json.dumps({"type": event_type, **kwargs}, ensure_ascii=False) + "\n\n"

    try:
        for ev in process_query(prompt_message, session_id_in, current_user, client, stream=True):
            t = ev["type"]
            if t == "error":
                yield _sse("error", message=ev.get("message"), status_code=ev.get("status_code", 500))
                return
            elif t == "status":
                yield _sse("status", content=ev["content"])
            elif t == "token":
                yield _sse("token", content=ev["content"])
            elif t == "replace":
                yield _sse("replace", content=ev["content"])
            elif t == "raw_sse":
                yield ev["data"]
            elif t == "final":
                env = ev["envelope"]
                # Traceability: stamp the router mode into meta (flows into the
                # 'done' SSE event) and pair this answer with its [REQ] line.
                try:
                    from services.router_mode import get_mode as _gm, pretty as _pp
                    env.setdefault("meta", {})["router"] = _pp(_gm())
                except Exception:
                    pass
                _m = env.get("meta", {})
                logger.info(
                    f"[DONE] router={_m.get('router')} source={env.get('source')} "
                    f"tier={_m.get('model_tier')} tokens={_m.get('tokens')} cached={_m.get('cached')} "
                    f"q='{prompt_message.strip()[:80]}'"
                )
                yield _sse("done",
                    source=env.get("source"),
                    suggestions=env.get("suggestions", []),
                    alerts=env.get("alerts", []),
                    chart=env.get("chart"),
                    session_id=env.get("session_id"),
                    session_title=env.get("session_title"),
                    meta=env.get("meta", {}),
                )

    except Exception as e:
        msg = str(e)
        logger.error(f"[STREAM] Unhandled error: {msg}", exc_info=True)
        low = msg.lower()
        if "tokens per minute" in low or "request too large" in low or "rate_limit" in low or "429" in low or "413" in low:
            user_msg = ("That request was too large or too frequent for the AI model's "
                        "current limit. Try a more specific question, or wait a minute and retry.")
        elif "invalid api key" in low or "401" in low:
            user_msg = "The AI service rejected the API key. Check GROQ_API_KEY on the server."
        else:
            user_msg = "An error occurred. Please try again."
        yield _sse("error", message=user_msg)
