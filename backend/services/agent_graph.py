"""
agent_graph.py
==============
LangGraph multi-agent system for BizAssist Phase 6.

Triggered for AI_COMPLEX queries (e.g. "analyse my Q1 business and give a growth plan").

Graph flow:
  START
    ↓
  planner_node          — decides which agents are needed + what to focus on
    ↓
  invoice_agent_node    — fetches invoice/revenue/overdue data
    ↓
  inventory_agent_node  — fetches stock/expiry data
    ↓
  payment_agent_node    — fetches cashflow/payment data
    ↓
  synthesizer_node      — Growth Advisor: combines all outputs into final response
    ↓
  END

Each agent checks the plan before running — skips if not needed,
so a "how much overdue do I have?" complex query won't trigger inventory/payment.
"""

import json
import logging
import os
from typing import TypedDict, Optional

from groq import Groq
from services.tools import execute_tool

logger = logging.getLogger("bizassist.agent_graph")

client        = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL_PLANNER = os.getenv("GROQ_MODEL_SIMPLE",  "llama-3.1-8b-instant")    # planner only needs JSON routing
MODEL_SYNTH   = os.getenv("GROQ_MODEL_COMPLEX", "llama-3.3-70b-versatile") # synthesizer needs reasoning


# ── State ─────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    user_query:        str
    business_id:       int
    history:           list
    plan:              dict   # planner output
    invoice_result:    str
    inventory_result:  str
    payment_result:    str
    final_response:    str
    tokens_in:         int    # token counts carried IN STATE (not a module global)
    tokens_out:        int    # — so concurrent AI_COMPLEX runs can't corrupt each other (C1)
    detected_topic:    Optional[str]


# ── Node 1: Planner ───────────────────────────────────────────────────

def planner_node(state: AgentState) -> AgentState:
    """
    Analyzes the query and produces a structured plan:
    which agents to activate and what each should focus on.
    Uses a low-temperature call for deterministic JSON output.
    """
    logger.info(f"[PLANNER] Analyzing: '{state['user_query']}'")

    from database.db import SessionLocal
    from database.models import Invoice, Inventory, Payment

    inv_count = 0
    stock_count = 0
    pay_count = 0

    db = SessionLocal()
    try:
        inv_count = db.query(Invoice).filter(Invoice.business_id == state["business_id"]).count()
        stock_count = db.query(Inventory).filter(Inventory.business_id == state["business_id"]).count()
        pay_count = db.query(Payment).filter(Payment.business_id == state["business_id"]).count()
    except Exception as e:
        logger.warning(f"[PLANNER] Failed to fetch database counts: {e}")
    finally:
        db.close()

    prompt = (
        f'User query: "{state["user_query"]}"\n\n'
        f"Active Business Database Context:\n"
        f"- Invoice records: {inv_count}\n"
        f"- Inventory/product records: {stock_count}\n"
        f"- Payment/cashflow records: {pay_count}\n\n"
        "Decide which business data areas are relevant. "
        "For general requests (e.g. 'analyze the uploaded file' or 'give an overview'), look at the database context "
        "to determine which data is populated and relevant to analyze. If a table has data, we should plan to analyze it.\n"
        "Respond with ONLY valid JSON — no markdown, no explanation:\n"
        "{\n"
        '  "needs_invoice": true or false,\n'
        '  "needs_inventory": true or false,\n'
        '  "needs_payment": true or false,\n'
        '  "invoice_focus": "what to analyse in invoices, or null",\n'
        '  "inventory_focus": "what to analyse in inventory, or null",\n'
        '  "payment_focus": "what to analyse in payments, or null",\n'
        '  "overall_goal": "one sentence — what the user ultimately wants"\n'
        "}"
    )

    p_in = p_out = 0
    try:
        resp = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_PLANNER,   # small model — just routing JSON, no reasoning needed
            temperature=0.0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        # Capture tokens right after the call (counted even if JSON parsing fails below).
        p_in  = resp.usage.prompt_tokens     or 0
        p_out = resp.usage.completion_tokens or 0
        logger.info(f"[PLANNER] Tokens — input: {p_in}, output: {p_out}")

        raw = resp.choices[0].message.content.strip()
        plan = json.loads(raw)
        logger.info(f"[PLANNER] Plan decided: {plan}")
    except Exception as e:
        logger.warning(f"[PLANNER] Could not parse plan ({e}). Using semantic fallback.")
        topic = state.get("detected_topic")
        needs_invoice = True
        needs_inventory = True
        needs_payment = True

        if topic:
            if topic in ["low_stock", "expiring_soon", "inventory_count", "product_performance"]:
                needs_invoice = False
                needs_inventory = True
                needs_payment = False
            elif topic in ["overdue_list", "overdue_amount", "pending_list", "total_revenue", 
                           "revenue_summary", "top_customers", "top_debtors", "dso_summary", 
                           "dormant_customers", "customer_margins"]:
                needs_invoice = True
                needs_inventory = False
                needs_payment = False
            elif topic in ["profit_summary", "business_summary"]:
                needs_invoice = True
                needs_inventory = False
                needs_payment = True

        plan = {
            "needs_invoice":   needs_invoice,
            "needs_inventory": needs_inventory,
            "needs_payment":   needs_payment,
            "overall_goal":    state["user_query"],
        }

    return {
        **state,
        "plan":       plan,
        "tokens_in":  state.get("tokens_in", 0)  + p_in,
        "tokens_out": state.get("tokens_out", 0) + p_out,
    }


# ── Node 2: Invoice Agent ─────────────────────────────────────────────

def invoice_agent_node(state: AgentState) -> AgentState:
    """
    Fetches invoice intelligence:
    - Status summary (paid / pending / overdue counts + amounts)
    - Top 5 overdue invoices
    - Top 5 customers by revenue
    """
    if not state["plan"].get("needs_invoice", True):
        logger.info("[INVOICE] Skipped — not needed.")
        return {**state, "invoice_result": ""}

    focus = state["plan"].get("invoice_focus", "general invoice analysis")
    logger.info(f"[INVOICE] Running — focus: {focus}")

    bid = state["business_id"]
    summary       = execute_tool("summarize_invoices",    {}, bid)
    aging         = execute_tool("overdue_aging_summary", {}, bid)
    overdue       = execute_tool("list_invoices",         {"status": "Overdue", "limit": 10}, bid)
    top_customers = execute_tool("rank_top_customers",    {"limit": 5}, bid)

    result = (
        f"=== INVOICE DATA (focus: {focus}) ===\n"
        f"Summary by status:\n{summary}\n\n"
        f"Overdue aging buckets (recoverability triage):\n{aging}\n\n"
        f"Top 10 overdue invoices (by amount):\n{overdue}\n\n"
        f"Top 5 customers by total revenue:\n{top_customers}"
    )
    logger.info(f"[INVOICE] Done ({len(result)} chars).")
    return {**state, "invoice_result": result}


# ── Node 3: Inventory Agent ───────────────────────────────────────────

def inventory_agent_node(state: AgentState) -> AgentState:
    """
    Fetches inventory intelligence:
    - Low stock items (≤ 10 units)
    - Items expiring within 30 days
    """
    if not state["plan"].get("needs_inventory", True):
        logger.info("[INVENTORY] Skipped — not needed.")
        return {**state, "inventory_result": ""}

    focus = state["plan"].get("inventory_focus", "general inventory analysis")
    logger.info(f"[INVENTORY] Running — focus: {focus}")

    bid = state["business_id"]
    low_stock = execute_tool("check_inventory_stock", {"filter_stock_under": 10}, bid)
    expiring  = execute_tool("check_inventory_stock", {"filter_expiry_days": 30},  bid)

    result = (
        f"=== INVENTORY DATA (focus: {focus}) ===\n"
        f"Low stock items (≤ 10 units):\n{low_stock}\n\n"
        f"Items expiring within 30 days:\n{expiring}"
    )
    logger.info(f"[INVENTORY] Done ({len(result)} chars).")
    return {**state, "inventory_result": result}


# ── Node 4: Payment Agent ─────────────────────────────────────────────

def payment_agent_node(state: AgentState) -> AgentState:
    """
    Fetches payment / cashflow intelligence:
    - Unpaid payment records
    - Overall business health metrics
    """
    if not state["plan"].get("needs_payment", True):
        logger.info("[PAYMENT] Skipped — not needed.")
        return {**state, "payment_result": ""}

    focus = state["plan"].get("payment_focus", "general payment analysis")
    logger.info(f"[PAYMENT] Running — focus: {focus}")

    bid = state["business_id"]
    unpaid  = execute_tool("list_payment_records",  {"paid_status": "No", "limit": 10}, bid)
    metrics = execute_tool("view_business_metrics", {}, bid)

    result = (
        f"=== PAYMENT DATA (focus: {focus}) ===\n"
        f"Unpaid records:\n{unpaid}\n\n"
        f"Business health metrics:\n{metrics}"
    )
    logger.info(f"[PAYMENT] Done ({len(result)} chars).")
    return {**state, "payment_result": result}


# ── Synthesizer prompt + message builder (shared by both run paths) ──
# One source of truth so the non-stream node and the streaming path can't drift.

_SYNTH_SYSTEM = (
    "You are BIZASSIST — a sharp, direct business advisor for Indian distributors and wholesalers. "
    "Specialist agents have fetched the real business data below. Synthesize it into a tight, useful response.\n\n"
    "STRICT RULES:\n"
    "1. Never repeat a section header. Each heading appears exactly once.\n"
    "2. Never include a section then dismiss it as 'not relevant' — skip it entirely if it adds nothing.\n"
    "3. Do not restate the symptom as the root cause. Dig one level deeper: "
    "   Is it aged debt (>90 days, likely bad debt)? A few large accounts dominating the risk? "
    "   Seasonal slump? Recent invoices that are just late?\n"
    "4. When prioritising overdue recovery, triage by RECOVERABILITY first, amount second:\n"
    "   - 0–60 days overdue → call this week, high chance of payment\n"
    "   - 61–180 days → negotiate payment plan, partial recovery\n"
    "   - 180+ days → legal notice or write-off consideration\n"
    "5. Be specific: name the customer, invoice ID, amount, days overdue. No generic advice.\n"
    "6. End with exactly ONE '## This Week: Top 3 Actions' section — concrete steps, not platitudes.\n"
    "7. Never invent numbers. Only use data the agents provided.\n"
    "8. Set realistic expectations — do not promise 100% collection in a week."
)


def _synth_messages(user_query, history, plan, invoice_result, inventory_result, payment_result):
    """Assemble the full message list (system + last 2 turns + user) for the synthesizer."""
    data_blocks = [r for r in [invoice_result, inventory_result, payment_result] if r]
    combined_data = "\n\n".join(data_blocks) or "No specific data retrieved."
    overall_goal  = (plan or {}).get("overall_goal", user_query)

    # last 2 turns only (4 messages) — prevents token bloat as the session grows
    messages = [{"role": m["role"], "content": m["content"]} for m in (history or [])[-4:]]
    messages.append({
        "role": "user",
        "content": (
            f"Goal: {overall_goal}\n\n"
            f"--- Agent-fetched data ---\n{combined_data}\n"
            f"-------------------------\n\n"
            f"Original query: {user_query}"
        ),
    })
    return [{"role": "system", "content": _SYNTH_SYSTEM}] + messages


# ── Node 5: Synthesizer (Growth Advisor) ─────────────────────────────

def synthesizer_node(state: AgentState) -> AgentState:
    """
    Growth Advisor — the final node.
    Receives all agent outputs and synthesizes them into a clear,
    actionable business growth response.
    """
    logger.info("[SYNTH] Building final growth plan...")

    messages = _synth_messages(
        state["user_query"], state.get("history", []), state["plan"],
        state.get("invoice_result"), state.get("inventory_result"), state.get("payment_result"),
    )

    s_in = s_out = 0
    try:
        resp = client.chat.completions.create(
            messages=messages,
            model=MODEL_SYNTH,   # big model — needs reasoning + synthesis
            temperature=0.2,
            max_tokens=1800,
        )
        s_in  = resp.usage.prompt_tokens     or 0
        s_out = resp.usage.completion_tokens or 0
        logger.info(f"[SYNTH] Tokens — input: {s_in}, output: {s_out}")

        final = resp.choices[0].message.content
    except Exception as e:
        logger.error(f"[SYNTH] Failed: {e}", exc_info=True)
        final = "I was unable to generate the growth plan. Please try again."

    logger.info(f"[SYNTH] Done ({len(final)} chars).")
    return {
        **state,
        "final_response": final,
        "tokens_in":      state.get("tokens_in", 0)  + s_in,
        "tokens_out":     state.get("tokens_out", 0) + s_out,
    }


# ── Graph Assembly ────────────────────────────────────────────────────

def _build_graph():
    from langgraph.graph import StateGraph, START, END

    g = StateGraph(AgentState)

    g.add_node("planner",          planner_node)
    g.add_node("invoice_agent",    invoice_agent_node)
    g.add_node("inventory_agent",  inventory_agent_node)
    g.add_node("payment_agent",    payment_agent_node)
    g.add_node("synthesizer",      synthesizer_node)

    g.add_edge(START,             "planner")
    g.add_edge("planner",         "invoice_agent")
    g.add_edge("invoice_agent",   "inventory_agent")
    g.add_edge("inventory_agent", "payment_agent")
    g.add_edge("payment_agent",   "synthesizer")
    g.add_edge("synthesizer",     END)

    compiled = g.compile()
    logger.info("[AGENT] LangGraph multi-agent graph compiled ✓")
    return compiled


_graph = None

def get_agent_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ── Public entry point ────────────────────────────────────────────────

def run_agent_graph(user_query: str, business_id: int, history: list, detected_topic: Optional[str] = None) -> dict:
    """
    Entry point called by main_groq.py for AI_COMPLEX queries.
    Returns the final synthesized response string.
    Also logs token usage to the token_usage table.
    """
    # Phase 2: opt into the adaptive tool-calling agent. Falls back to the proven
    # pipeline below on ANY error, so the flag is safe to flip.
    if os.getenv("AGENT_MODE", "pipeline").lower() == "loop":
        try:
            from services.agent_loop import run_agent_loop
            return run_agent_loop(user_query, business_id, history)
        except Exception as e:
            logger.error(f"[AGENT] loop failed, falling back to pipeline: {e}", exc_info=True)

    graph = get_agent_graph()

    initial: AgentState = {
        "user_query":       user_query,
        "business_id":      business_id,
        "history":          history,
        "plan":             {},
        "invoice_result":   "",
        "inventory_result": "",
        "payment_result":   "",
        "final_response":   "",
        "tokens_in":        0,
        "tokens_out":       0,
        "detected_topic":    detected_topic,
    }

    logger.info(f"[AGENT] ── Starting multi-agent run ──")
    result = graph.invoke(initial)
    logger.info(f"[AGENT] ── Multi-agent run complete ──")

    # Combined token usage for the full run — read from state (race-free, per-run)
    total_in  = result.get("tokens_in", 0)
    total_out = result.get("tokens_out", 0)
    logger.info(f"[AGENT] Tokens used — input: {total_in}, output: {total_out}, total: {total_in + total_out}")
    try:
        from database.db import SessionLocal
        from database.models import TokenUsage
        db = SessionLocal()
        try:
            db.add(TokenUsage(
                business_id   = business_id,
                model         = MODEL_SYNTH,
                model_tier    = "AI_COMPLEX",
                input_tokens  = total_in,
                output_tokens = total_out,
                total_tokens  = total_in + total_out,
                endpoint      = "/ask",
            ))
            db.commit()
        except Exception as te:
            logger.warning(f"[TOKENS] Could not log tokens: {te}")
        finally:
            db.close()
    except Exception as te:
        logger.warning(f"[TOKENS] Import/DB error: {te}")

    return {
        "text":       result["final_response"],
        "tokens_in":  total_in,
        "tokens_out": total_out,
    }


# ── Streaming entry point ─────────────────────────────────────────────

def run_agent_graph_stream(user_query: str, business_id: int, history: list, detected_topic: Optional[str] = None):
    """
    Generator for SSE streaming.
    Runs agent nodes manually, streams synthesizer output token by token.

    Yields SSE strings:
      data: {"type": "status",  "content": "..."}
      data: {"type": "token",   "content": "..."}
      data: {"type": "ag_done", "tokens": {...}, "full_text": "..."}
    """
    import json as _json

    def _sse(event_type, **kwargs):
        return "data: " + _json.dumps({"type": event_type, **kwargs}, ensure_ascii=False) + "\n\n"

    # Phase 2: adaptive agent loop (opt-in). The loop handles its own mid-stream
    # errors internally; we only fall back to the pipeline if it can't even import.
    if os.getenv("AGENT_MODE", "pipeline").lower() == "loop":
        try:
            from services.agent_loop import run_agent_loop_stream
        except Exception as e:
            logger.error(f"[AGENT] loop import failed, using pipeline: {e}", exc_info=True)
        else:
            yield from run_agent_loop_stream(user_query, business_id, history)
            return

    state: AgentState = {
        "user_query":       user_query,
        "business_id":      business_id,
        "history":          history,
        "plan":             {},
        "invoice_result":   "",
        "inventory_result": "",
        "payment_result":   "",
        "final_response":   "",
        "tokens_in":        0,
        "tokens_out":       0,
        "detected_topic":    detected_topic,
    }

    yield _sse("status", content="Planning query\u2026")
    state = planner_node(state)

    if state["plan"].get("needs_invoice", True):
        yield _sse("status", content="Fetching invoice & revenue data\u2026")
        state = invoice_agent_node(state)

    if state["plan"].get("needs_inventory", True):
        yield _sse("status", content="Checking inventory & stock\u2026")
        state = inventory_agent_node(state)

    if state["plan"].get("needs_payment", True):
        yield _sse("status", content="Analysing cash flow\u2026")
        state = payment_agent_node(state)

    yield _sse("status", content="Building your action plan\u2026")

    messages = _synth_messages(
        user_query, history, state["plan"],
        state.get("invoice_result"), state.get("inventory_result"), state.get("payment_result"),
    )

    full_text = ""
    synth_usage = None
    try:
        _base = dict(messages=messages, model=MODEL_SYNTH,
                     temperature=0.2, max_tokens=1800, stream=True)
        try:
            # Real usage for the streamed synthesizer (R1) — arrives on a final
            # choices-less chunk when include_usage is requested.
            stream = client.chat.completions.create(
                **_base, stream_options={"include_usage": True})
        except TypeError:    # SDK too old for stream_options
            stream = client.chat.completions.create(**_base)
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
    except Exception as e:
        logger.error(f"[SYNTH] {e}", exc_info=True)
        yield _sse("token", content=f"\n\n*Could not complete: {e}*")

    # Count the synthesizer's streamed tokens — it's the biggest call in the
    # graph. If no usage chunk was exposed, estimate (~4 chars/token) rather
    # than logging 0.
    if synth_usage is not None:
        state["tokens_in"]  = state.get("tokens_in", 0)  + (getattr(synth_usage, "prompt_tokens", 0) or 0)
        state["tokens_out"] = state.get("tokens_out", 0) + (getattr(synth_usage, "completion_tokens", 0) or 0)
    elif full_text:
        _est_in = sum(len(str(m.get("content") or "")) for m in messages) // 4
        state["tokens_in"]  = state.get("tokens_in", 0)  + _est_in
        state["tokens_out"] = state.get("tokens_out", 0) + max(1, len(full_text) // 4)

    total_in  = state.get("tokens_in", 0)
    total_out = state.get("tokens_out", 0)
    logger.info(f"[AGENT] Tokens in={total_in} out={total_out}")
    try:
        from database.db import SessionLocal
        from database.models import TokenUsage
        _db = SessionLocal()
        try:
            _db.add(TokenUsage(
                business_id=business_id, model=MODEL_SYNTH, model_tier="AI_COMPLEX",
                input_tokens=total_in, output_tokens=total_out,
                total_tokens=total_in + total_out, endpoint="/ask/stream",
            ))
            _db.commit()
        except Exception:
            pass
        finally:
            _db.close()
    except Exception:
        pass

    yield _sse("ag_done", tokens={"input": total_in, "output": total_out}, full_text=full_text)
