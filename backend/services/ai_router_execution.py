"""
services/ai_router_execution.py
===============================
Execution layer split out of ai_router.py (MASTER_REVIEW §2.5).

Everything that RUNS a decided route — token accounting, streaming, session
title resolution, chat history/persistence, the polish/insight layer, and the
system prompts + message assembly for AI_SIMPLE turns.
"""
import os
import re
import logging

from groq import Groq

from services.embeddings import search_chat_memories, save_chat_memory
from services.recommendations import get_business_snapshot
from services.ai_router_cache import _safe_int
from database.db import SessionLocal
from database.models import ChatMessage

logger = logging.getLogger("bizassist.ai_router")

MODEL_SIMPLE  = os.getenv("GROQ_MODEL_SIMPLE",  "meta-llama/llama-4-scout-17b-16e-instruct")
MODEL_COMPLEX = os.getenv("GROQ_MODEL_COMPLEX", "openai/gpt-oss-120b")

# Max characters of a single tool result fed back to the model. A "draft a
# reminder" tool can return the entire overdue table (hundreds of rows); without
# a cap the follow-up call blows past the model's per-minute token limit (Groq
# free tier = 6000 TPM). ~4000 chars ≈ ~1000 tokens — plenty for a useful answer.
_MAX_TOOL_CHARS = int(os.getenv("MAX_TOOL_CHARS", "4000"))

def _log_token_usage(business_id, model, tier, usage, acc) -> None:
    """
    Record one Groq call's token usage to TokenUsage AND add it to the running
    per-request accumulator `acc`. This is the single source of token truth —
    every Groq call (conversational, polish, tool round, final round) flows
    through here, so budgets and the admin usage page reflect real spend.
    """
    ti = _safe_int(getattr(usage, "prompt_tokens", 0))
    to = _safe_int(getattr(usage, "completion_tokens", 0))
    acc["in"]  += ti
    acc["out"] += to
    if not (ti or to):
        return
    db = SessionLocal()
    try:
        from database.models import TokenUsage
        db.add(TokenUsage(
            business_id   = business_id,
            model         = model,
            model_tier    = tier,
            input_tokens  = ti,
            output_tokens = to,
            total_tokens  = ti + to,
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"[TOKENS] Failed to log usage ({tier}): {e}")
    finally:
        db.close()


_SESSION_PLACEHOLDER = "New chat"

# A leading greeting/filler shouldn't become the conversation title — otherwise
# every chat a user opens with "hi" is titled "hi" and they're indistinguishable.
_GREETING_RE = re.compile(
    r"^(hi+|hey+|hello+|hiya|yo|hola|sup|namaste|"
    r"thanks?|thank\s*you|thankyou|thx|ty|"
    r"ok(ay)?|cool|nice|great|good\s+(morning|afternoon|evening|day)|greetings)"
    r"[\s!.,?]*$",
    re.I,
)


def _is_titleable(text: str) -> bool:
    """True if this message is substantive enough to title a conversation."""
    t = (text or "").strip()
    return bool(t) and _GREETING_RE.match(t) is None


def _title_from(text: str) -> str:
    t = (text or "").strip()
    return t[:40] + ("..." if len(t) > 40 else "")


class _UsageEstimate:
    """
    Fallback usage for a streamed response that exposed no usage object
    (~4 chars/token heuristic). Streamed traffic is the app's main path, so it
    must never log 0 tokens (R1) — an estimate keeps budgets honest.
    """
    def __init__(self, messages, completion_text: str):
        def _clen(m):
            c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            return len(str(c or ""))
        self.prompt_tokens     = sum(_clen(m) for m in (messages or [])) // 4
        self.completion_tokens = (max(1, len(completion_text) // 4)
                                  if completion_text else 0)


def _stream_deltas(client, messages, model, business_id, tier, acc, **kw):
    """
    Stream a chat completion, yielding text deltas. Requests real usage via
    stream_options={"include_usage": True} (Groq is OpenAI-compatible); the
    usage arrives on a final choices-less chunk, which is captured and logged
    through _log_token_usage. Falls back gracefully:
      - SDK too old for stream_options → retry without it
      - no usage chunk seen           → character-count estimate
    """
    base = dict(messages=messages, model=model, stream=True, **kw)
    try:
        s = client.chat.completions.create(**base,
                                           stream_options={"include_usage": True})
    except TypeError:
        s = client.chat.completions.create(**base)

    usage, text = None, ""
    for chunk in s:
        u = getattr(chunk, "usage", None)
        if u is not None:
            usage = u                      # usage-only final chunk
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue
        delta = choices[0].delta.content
        if delta:
            text += delta
            yield delta
    _log_token_usage(business_id, model, tier,
                     usage or _UsageEstimate(messages, text), acc)


def _resolve_session(active_user_id: int, session_id: str, user_query: str) -> str:
    """
    Resolve the session title for this session_id. The title is the first
    SUBSTANTIVE user message — greetings ("hi", "thanks") are skipped so a chat
    opened with "hi" isn't permanently titled "hi". When the first real question
    arrives in a session that only had greetings, earlier rows are retro-fitted
    to the new title so the sidebar updates.
    """
    db = SessionLocal()
    session_title = _SESSION_PLACEHOLDER
    try:
        first = db.query(ChatMessage).filter(
            ChatMessage.business_id == active_user_id,
            ChatMessage.session_id  == session_id,
        ).order_by(ChatMessage.id.asc()).first()

        existing_title = first.session_title if first else None
        # Keep an existing real title (incl. one the user manually renamed to).
        if existing_title and existing_title not in (_SESSION_PLACEHOLDER, "Untitled Conversation") \
                and _is_titleable(existing_title):
            return existing_title

        if _is_titleable(user_query):
            session_title = _title_from(user_query)
            # Upgrade any earlier greeting-only rows in this session.
            if first is not None:
                db.query(ChatMessage).filter(
                    ChatMessage.business_id == active_user_id,
                    ChatMessage.session_id  == session_id,
                ).update({ChatMessage.session_title: session_title})
                db.commit()
        else:
            session_title = existing_title or _SESSION_PLACEHOLDER
    except Exception as e:
        db.rollback()
        logger.error(f"Error resolving session title: {e}", exc_info=True)
    finally:
        db.close()
    return session_title


def _fetch_history(active_user_id: int, session_id: str) -> list:
    """Last 6 turns for this session, long responses truncated to keep context lean."""
    db = SessionLocal()
    history = []
    try:
        rows = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.business_id == active_user_id,
                ChatMessage.session_id  == session_id,
            )
            .order_by(ChatMessage.id.desc())
            .limit(6)
            .all()
        )
        for m in reversed(rows):
            content = m.content
            if len(content) > 400:
                content = content[:400] + "... [truncated]"
            history.append({"role": m.role, "content": content})
    except Exception as e:
        logger.error(f"Error fetching chat history: {e}", exc_info=True)
    finally:
        db.close()
    return history


def _log_chat(business_id, user_query, response, session_id, session_title,
              source="ai", model_tier=None, cached=False, remember=True) -> None:
    """
    Persist a user+assistant turn to ChatMessage. When `remember` is True the
    turn is also embedded into the Chroma memory (skip for conversational chit-
    chat and cache replays, which add no durable business signal).
    """
    db = SessionLocal()
    try:
        db.add(ChatMessage(
            business_id=business_id, role="user", content=user_query,
            session_id=session_id, session_title=session_title,
        ))
        db.add(ChatMessage(
            business_id=business_id, role="assistant", content=response,
            session_id=session_id, session_title=session_title,
            source=source, model_tier=model_tier, cached=cached,
        ))
        db.commit()
        if remember:
            save_chat_memory(
                business_id=business_id, session_id=session_id,
                session_title=session_title,
                user_query=user_query, assistant_response=response,
            )
    except Exception as e:
        db.rollback()
        logger.error(f"[CHAT] {e}", exc_info=True)
    finally:
        db.close()


# Handlers whose output is a precise factual record — skip the AI insight layer
# (no analysis to add, and high confabulation risk on single records / tables).
_NO_POLISH = {"invoice_detail", "customer_invoices"}


def _polish(raw_markdown: str, topic: str, client: Groq,
            business_id=None, acc=None) -> str:
    """
    Adds a 2-sentence AI insight layer to raw DB/handler output.
    Cost: ~250 tokens FIRST call per topic (now logged via _log_token_usage).
    Falls back to raw_markdown on any Groq error — never blocks the response.
    """
    try:
        resp = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a business analyst. Read the BUSINESS DATA below and write at most 2 short sentences:\n"
                        "1. The single biggest risk or insight, citing the exact number from the data.\n"
                        "2. One concrete next step.\n"
                        "\n"
                        "HARD RULES — follow exactly:\n"
                        "- Use ONLY facts that appear in the data. NEVER invent or guess customer names, "
                        "customer IDs, invoice numbers, product names/IDs, or amounts.\n"
                        "- If the data names a specific customer or item, refer to it by that exact name. "
                        "If the data has only totals and names NO specific customer/item, give a GENERAL "
                        "next step — do NOT make up a name, an ID, or a figure.\n"
                        "- If the data says everything is fine (e.g. sufficient stock), say so plainly; do not invent a problem.\n"
                        "- NEVER infer timing: a 'Paid' status does NOT tell you WHEN it was paid. Never say "
                        "'paid N days early/late' or any payment date — that data is not here.\n"
                        "- NEVER do arithmetic between unlike things (e.g. an amount vs a date) and never "
                        "compute a difference or ratio unless BOTH numbers literally appear in the data.\n"
                        "- If the data says 'top N of M (₹X total)', then ₹X is the total of ALL M — never "
                        "describe it as the total of just the N shown.\n"
                        "- Do not contradict the data's own status labels (if it says Paid, it is Paid).\n"
                        "- Use the same currency symbol as the data (₹). Never use $.\n"
                        "- Exact numbers only (no rounding). No headers, no bullet points, no filler."
                    )
                },
                {"role": "user", "content": "BUSINESS DATA:\n" + raw_markdown[:900]}
            ],
            model=MODEL_SIMPLE,
            temperature=0.0,
            max_tokens=110,
        )
        if business_id is not None and acc is not None:
            _log_token_usage(business_id, MODEL_SIMPLE, "POLISH", getattr(resp, "usage", None), acc)
        insight = (resp.choices[0].message.content or "").strip()
        if insight:
            return f"{raw_markdown}\n\n---\n💡 {insight}"
        return raw_markdown
    except Exception as e:
        logger.warning(f"[POLISH] Groq polish failed — returning raw. Reason: {e}")
        return raw_markdown


_AI_SIMPLE_SYSTEM_PROMPT = (
    "You are BIZASSIST, a sharp business advisor for distributors, wholesalers, and small businesses.\n"
    "\n"
    "CRITICAL — NEVER FABRICATE DATA:\n"
    "You may ONLY state an invoice ID, amount, date, status, customer name, or any figure\n"
    "that appears in a TOOL RESULT from THIS conversation. If you don't have the rows, CALL\n"
    "THE TOOL to fetch them. If a tool cannot supply them, say plainly 'I don't have those\n"
    "details' — do NOT invent, estimate, guess, or pattern-fill them (e.g. inventing\n"
    "INV-0001, INV-0002… with made-up amounts). The conversation summary holds TOTALS, not\n"
    "line items — never reconstruct individual invoices from it. Fabricating financial data\n"
    "is the single worst thing you can do.\n"
    "\n"
    "RULES:\n"
    "1. Call a tool first for any business-data question. The summary in context has totals,\n"
    "   not the underlying rows — fetch the real rows before listing anything.\n"
    "2. Write like a trusted advisor. Use a table ONLY when the user asks for one, and fill\n"
    "   it STRICTLY from tool results; otherwise short paragraphs or a brief list.\n"
    "3. Always name specifics drawn from the data: customer names, invoice IDs, rupee\n"
    "   amounts, dates, days overdue. Vague answers are useless.\n"
    "4. End with ONE concrete action the owner can take right now — not a generic tip.\n"
    "5. Never write code. Never pad with filler sentences.\n"
    "6. You CANNOT perform actions — you cannot send emails/reminders, escalate, mark\n"
    "   invoices paid, or place orders. NEVER claim you did ('Done.', 'Sent.',\n"
    "   'I've escalated…'). If the user asks you to DO one of these, draft the content\n"
    "   if helpful and tell them to use the action button to actually send/run it.\n"
    "\n"
    "TONE: Direct, clear, human. Think 'smart accountant on the phone', not 'dashboard report'.\n"
    "\n"
    "Tool args must be valid JSON.\n"
)

_CONVERSATIONAL_SYSTEM_PROMPT = (
    "You are BIZASSIST, a business assistant. The user sent a short conversational "
    "message. Reply briefly and naturally in 1-2 sentences. Do NOT volunteer business "
    "data, reports, or unsolicited recommendations."
)

_ADVISE_SYSTEM_PROMPT = (
    "You are BIZASSIST, a sharp business advisor for distributors and wholesalers. The user "
    "asked for SUGGESTIONS, and their REAL data is provided below. Give practical, "
    "specific advice grounded in that data.\n\n"
    "RULES:\n"
    "- Use ONLY the numbers, customers, and products in the data. NEVER invent any.\n"
    "- NEVER use hypothetical examples, illustrative names, or made-up amounts — "
    "no \"if Customer X has ₹50,000…\", no \"for example, a customer who…\". Every "
    "name and figure you write MUST appear verbatim in the data below. If the data "
    "doesn't support a point, leave it out.\n"
    "- Name names: tie each suggestion to a specific customer/product/amount.\n"
    "- 3-5 concrete suggestions, most impactful first. Short paragraphs or a brief "
    "numbered list.\n"
    "- Use ₹ with comma formatting (₹2,48,669). Never $.\n"
    "- End with ONE thing to do today.\n"
)


def _build_ai_simple_messages(user_query: str, history: list, active_user_id: int) -> list:
    """Assemble the message list for an AI_SIMPLE tool-calling turn."""
    messages = [{"role": "system", "content": _AI_SIMPLE_SYSTEM_PROMPT}]
    past_memories = search_chat_memories(active_user_id, user_query, limit=3)
    if past_memories:
        messages.append({"role": "system", "content": f"[Relevant past context]\n{past_memories}"})
    if os.getenv("SNAPSHOT_CONTEXT", "true").lower() != "false":
        snap = get_business_snapshot(active_user_id)
        if snap:
            messages.append({"role": "system", "content": snap})
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_query})
    return messages


