"""
services/agent_loop.py — Phase 2: adaptive tool-calling agent (flag-gated).
==========================================================================
`AGENT_MODE=loop` switches AI_COMPLEX from the fixed fan-out pipeline
(agent_graph.py) to this adaptive loop: the 70B model is given every registered
tool and decides which to call, inspects the results, and keeps calling until it
has what it needs — then writes the answer. No blanket fan-out, so cost tracks
the question's actual needs.

Safety / trust:
  - Bounded: at most AGENT_MAX_TOOL_ROUNDS tool rounds + a per-tool char cap, so a
    runaway can't loop or blow the token budget.
  - Grounded: the model may only use numbers from tool results (same rule as the
    rest of the app); it never invents figures.
  - Opt-in + reversible: default is the proven pipeline; the dispatcher falls back
    to it on ANY error here. Same shadow/flag rollout we used for the router.
"""
import os
import json
import logging

from groq import Groq
from services.tools import execute_tool, schemas as tool_schemas

logger = logging.getLogger("bizassist.agent_loop")

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL          = os.getenv("GROQ_MODEL_COMPLEX", "llama-3.3-70b-versatile")
MAX_ROUNDS     = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "5"))
MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "4000"))


def _friendly_error(e: Exception) -> str:
    """Turn a raw exception into an honest, non-alarming message for the user.
    A 429/quota error means the daily AI budget is spent, not that anything broke."""
    msg = str(e).lower()
    is_quota = "429" in msg or "rate_limit" in msg or "tokens per day" in msg \
        or "quota" in msg or getattr(e, "status_code", None) == 429
    if is_quota:
        return ("*The daily AI analysis limit has been reached.* Quick answers "
                "(totals, overdue, invoices, customers) still work — only the deep "
                "analysis pauses until the limit resets (usually within an hour).")
    return "*The advisor hit an error — please try again.*"

_SYSTEM = (
    "You are BIZASSIST — a sharp business advisor for an Indian distributor/wholesaler, "
    "answering a complex question that needs real data.\n\n"
    "You have TOOLS that read the owner's live database. Use them to gather exactly the "
    "data the question needs — call several if useful, but don't fetch what's irrelevant. "
    "When you have enough, STOP calling tools and write the answer.\n\n"
    "RULES:\n"
    "- Use ONLY numbers returned by the tools. NEVER invent figures, customers, or products.\n"
    "- Pick the RIGHT tool for the question: for 'who owes the most' / biggest debtors use "
    "rank_top_debtors (per-customer overdue TOTALS) — NOT list_invoices (those are individual bills, "
    "not a customer's total). rank_top_customers is by REVENUE, a different thing.\n"
    "- A single invoice's amount is NOT a customer's total overdue — never present one as the other.\n"
    "- Do NOT give advice about a domain you haven't fetched data for. If you want to advise on "
    "inventory/stock, first call an inventory tool; otherwise don't mention it.\n"
    "- Answer the ACTUAL question asked — a profit/growth question is not just a collections question.\n"
    "- Be specific: cite customer names, invoice IDs, amounts, days overdue.\n"
    "- For overdue recovery, triage by recoverability: 0–60d (call now), 61–180d (payment plan), "
    "180+d (legal/write-off). Don't restate the symptom as the cause — dig one level deeper.\n"
    "- Use ₹, never $. Don't promise unrealistic outcomes.\n"
    "- End the final answer with exactly one '## This Week: Top 3 Actions' section.\n"
)

_FINALIZE = ("Stop calling tools. Using only the data already gathered above, write the final "
             "answer now. End with '## This Week: Top 3 Actions'.")


def _seed_messages(user_query: str, history: list) -> list:
    msgs = [{"role": "system", "content": _SYSTEM}]
    for m in (history or [])[-4:]:
        msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": user_query})
    return msgs


def _gather(messages: list, business_id: int, emit=None):
    """
    Run the adaptive tool rounds. Mutates `messages`, returns (answer_or_None,
    tokens_in, tokens_out). answer is non-None if the model finished within the
    round budget; None means we hit the cap and a forced finalize is needed.
    """
    t_in = t_out = 0
    for _round in range(MAX_ROUNDS):
        resp = _client.chat.completions.create(
            model=MODEL, messages=messages, tools=tool_schemas,
            tool_choice="auto", temperature=0.2, max_tokens=1600,
        )
        u = getattr(resp, "usage", None)
        t_in += getattr(u, "prompt_tokens", 0) or 0
        t_out += getattr(u, "completion_tokens", 0) or 0
        msg = resp.choices[0].message

        if not getattr(msg, "tool_calls", None):
            return (msg.content or ""), t_in, t_out      # model produced the answer

        messages.append(msg)
        for tc in msg.tool_calls:
            name = tc.function.name
            if emit:
                emit(f"Checking {name.replace('_', ' ')}…")
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            if not isinstance(args, dict):   # model may send `null` for a no-arg tool
                args = {}
            result = execute_tool(name, args, business_id)
            if isinstance(result, str) and len(result) > MAX_TOOL_CHARS:
                result = result[:MAX_TOOL_CHARS] + "\n…[truncated to fit the token budget]"
            messages.append({"role": "tool", "tool_call_id": tc.id, "name": name, "content": result})
            logger.info(f"[AGENT-LOOP] tool={name} round={_round + 1}")
    return None, t_in, t_out   # hit the round cap → caller must finalize


def run_agent_loop(user_query: str, business_id: int, history: list) -> dict:
    """Non-stream entry. Returns {text, tokens_in, tokens_out}."""
    logger.info(f"[AGENT-LOOP] start | '{user_query}'")
    t_in = t_out = 0
    try:
        messages = _seed_messages(user_query, history)
        answer, t_in, t_out = _gather(messages, business_id)
        if answer is None:
            messages.append({"role": "user", "content": _FINALIZE})
            resp = _client.chat.completions.create(
                model=MODEL, messages=messages, temperature=0.2, max_tokens=1800)
            u = getattr(resp, "usage", None)
            t_in += getattr(u, "prompt_tokens", 0) or 0
            t_out += getattr(u, "completion_tokens", 0) or 0
            answer = resp.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"[AGENT-LOOP] run failed: {e}", exc_info=True)
        answer = _friendly_error(e)
    _log_tokens(business_id, t_in, t_out, "/ask")
    return {"text": answer, "tokens_in": t_in, "tokens_out": t_out}


def run_agent_loop_stream(user_query: str, business_id: int, history: list):
    """
    Generator yielding SSE strings (status / token / ag_done) — matches the
    pipeline's streaming contract so ai_router needs no change.
    Tool rounds emit status; the final synthesis is streamed token-by-token.
    """
    def _sse(t, **kw):
        return "data: " + json.dumps({"type": t, **kw}, ensure_ascii=False) + "\n\n"

    yield _sse("status", content="Working out what to check…")
    t_in = t_out = 0
    full_text = ""
    try:
        statuses = []
        messages = _seed_messages(user_query, history)
        # Buffer status events emitted during the (blocking) gather, then flush.
        answer, t_in, t_out = _gather(messages, business_id, emit=statuses.append)
        for s in statuses:
            yield _sse("status", content=s)

        if answer is not None:
            full_text = answer                       # model stopped on its own
            yield _sse("token", content=answer)
        else:
            yield _sse("status", content="Writing your action plan…")
            messages.append({"role": "user", "content": _FINALIZE})
            _base = dict(model=MODEL, messages=messages,
                         temperature=0.2, max_tokens=1800, stream=True)
            try:
                # Real usage for the streamed finalize call (R1) — arrives on a
                # final choices-less chunk when include_usage is requested.
                stream = _client.chat.completions.create(
                    **_base, stream_options={"include_usage": True})
            except TypeError:    # SDK too old for stream_options
                stream = _client.chat.completions.create(**_base)
            synth_usage = None
            for chunk in stream:
                u = getattr(chunk, "usage", None)
                if u is not None:
                    synth_usage = u
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    full_text += delta
                    yield _sse("token", content=delta)
            if synth_usage is not None:
                t_in  += getattr(synth_usage, "prompt_tokens", 0) or 0
                t_out += getattr(synth_usage, "completion_tokens", 0) or 0
            elif full_text:
                # No usage exposed → estimate (~4 chars/token) instead of logging 0.
                t_in  += sum(len(str(m.get("content") if isinstance(m, dict)
                                     else getattr(m, "content", "") or "")) for m in messages) // 4
                t_out += max(1, len(full_text) // 4)
    except Exception as e:
        logger.error(f"[AGENT-LOOP] stream failed: {e}", exc_info=True)
        if not full_text:
            yield _sse("token", content=_friendly_error(e))

    _log_tokens(business_id, t_in, t_out, "/ask/stream")
    yield _sse("ag_done", tokens={"input": t_in, "output": t_out}, full_text=full_text)


def _log_tokens(business_id: int, t_in: int, t_out: int, endpoint: str) -> None:
    logger.info(f"[AGENT-LOOP] tokens in={t_in} out={t_out}")
    try:
        from database.db import SessionLocal
        from database.models import TokenUsage
        db = SessionLocal()
        try:
            db.add(TokenUsage(
                business_id=business_id, model=MODEL, model_tier="AI_COMPLEX",
                input_tokens=t_in, output_tokens=t_out,
                total_tokens=t_in + t_out, endpoint=endpoint,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"[AGENT-LOOP] token log failed: {e}")
