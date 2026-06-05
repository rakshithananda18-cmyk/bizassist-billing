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
from typing import TypedDict

from groq import Groq
from services.tools import execute_tool

logger = logging.getLogger("bizassist.agent_graph")

client        = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL_PLANNER = os.getenv("GROQ_MODEL_SIMPLE",  "llama-3.1-8b-instant")    # planner only needs JSON routing
MODEL_SYNTH   = os.getenv("GROQ_MODEL_COMPLEX", "llama-3.3-70b-versatile") # synthesizer needs reasoning

# Token counters accumulated across the graph run (reset per run_agent_graph call)
_run_tokens = {"input": 0, "output": 0}


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


# ── Node 1: Planner ───────────────────────────────────────────────────

def planner_node(state: AgentState) -> AgentState:
    """
    Analyzes the query and produces a structured plan:
    which agents to activate and what each should focus on.
    Uses a low-temperature call for deterministic JSON output.
    """
    logger.info(f"[Planner] Analyzing: '{state['user_query']}'")

    prompt = (
        f'User query: "{state["user_query"]}"\n\n'
        "Decide which business data areas are relevant. "
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

    try:
        resp = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_PLANNER,   # small model — just routing JSON, no reasoning needed
            temperature=0.0,
            max_tokens=300,
        )
        # Log tokens immediately after this call
        p_in  = resp.usage.prompt_tokens     or 0
        p_out = resp.usage.completion_tokens or 0
        _run_tokens["input"]  += p_in
        _run_tokens["output"] += p_out
        logger.info(f"[Planner] Tokens — input: {p_in}, output: {p_out}")

        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        plan = json.loads(raw.strip())
        logger.info(f"[Planner] Plan decided: {plan}")
    except Exception as e:
        logger.warning(f"[Planner] Could not parse plan ({e}). Defaulting to all agents.")
        plan = {
            "needs_invoice":   True,
            "needs_inventory": True,
            "needs_payment":   True,
            "overall_goal":    state["user_query"],
        }

    return {**state, "plan": plan}


# ── Node 2: Invoice Agent ─────────────────────────────────────────────

def invoice_agent_node(state: AgentState) -> AgentState:
    """
    Fetches invoice intelligence:
    - Status summary (paid / pending / overdue counts + amounts)
    - Top 5 overdue invoices
    - Top 5 customers by revenue
    """
    if not state["plan"].get("needs_invoice", True):
        logger.info("[Invoice Agent] Skipped — not needed.")
        return {**state, "invoice_result": ""}

    focus = state["plan"].get("invoice_focus", "general invoice analysis")
    logger.info(f"[Invoice Agent] Running — focus: {focus}")

    bid = state["business_id"]
    summary      = execute_tool("summarize_invoices",  {}, bid)
    overdue      = execute_tool("list_invoices",       {"status": "Overdue", "limit": 5}, bid)
    top_customers = execute_tool("rank_top_customers", {"limit": 5}, bid)

    result = (
        f"=== INVOICE DATA (focus: {focus}) ===\n"
        f"Summary by status:\n{summary}\n\n"
        f"Top 5 overdue invoices:\n{overdue}\n\n"
        f"Top 5 customers by revenue:\n{top_customers}"
    )
    logger.info(f"[Invoice Agent] Done ({len(result)} chars).")
    return {**state, "invoice_result": result}


# ── Node 3: Inventory Agent ───────────────────────────────────────────

def inventory_agent_node(state: AgentState) -> AgentState:
    """
    Fetches inventory intelligence:
    - Low stock items (≤ 10 units)
    - Items expiring within 30 days
    """
    if not state["plan"].get("needs_inventory", True):
        logger.info("[Inventory Agent] Skipped — not needed.")
        return {**state, "inventory_result": ""}

    focus = state["plan"].get("inventory_focus", "general inventory analysis")
    logger.info(f"[Inventory Agent] Running — focus: {focus}")

    bid = state["business_id"]
    low_stock = execute_tool("check_inventory_stock", {"filter_stock_under": 10}, bid)
    expiring  = execute_tool("check_inventory_stock", {"filter_expiry_days": 30},  bid)

    result = (
        f"=== INVENTORY DATA (focus: {focus}) ===\n"
        f"Low stock items (≤ 10 units):\n{low_stock}\n\n"
        f"Items expiring within 30 days:\n{expiring}"
    )
    logger.info(f"[Inventory Agent] Done ({len(result)} chars).")
    return {**state, "inventory_result": result}


# ── Node 4: Payment Agent ─────────────────────────────────────────────

def payment_agent_node(state: AgentState) -> AgentState:
    """
    Fetches payment / cashflow intelligence:
    - Unpaid payment records
    - Overall business health metrics
    """
    if not state["plan"].get("needs_payment", True):
        logger.info("[Payment Agent] Skipped — not needed.")
        return {**state, "payment_result": ""}

    focus = state["plan"].get("payment_focus", "general payment analysis")
    logger.info(f"[Payment Agent] Running — focus: {focus}")

    bid = state["business_id"]
    unpaid  = execute_tool("list_payment_records",  {"paid_status": "No", "limit": 10}, bid)
    metrics = execute_tool("view_business_metrics", {}, bid)

    result = (
        f"=== PAYMENT DATA (focus: {focus}) ===\n"
        f"Unpaid records:\n{unpaid}\n\n"
        f"Business health metrics:\n{metrics}"
    )
    logger.info(f"[Payment Agent] Done ({len(result)} chars).")
    return {**state, "payment_result": result}


# ── Node 5: Synthesizer (Growth Advisor) ─────────────────────────────

def synthesizer_node(state: AgentState) -> AgentState:
    """
    Growth Advisor — the final node.
    Receives all agent outputs and synthesizes them into a clear,
    actionable business growth response.
    """
    logger.info("[Synthesizer] Building final growth plan...")

    data_blocks = [
        r for r in [
            state.get("invoice_result"),
            state.get("inventory_result"),
            state.get("payment_result"),
        ] if r
    ]
    combined_data = "\n\n".join(data_blocks) or "No specific data retrieved."
    overall_goal  = state["plan"].get("overall_goal", state["user_query"])

    SYSTEM = (
        "You are BIZASSIST Growth Advisor for Indian retail businesses (pharmacies, supermarkets, stores). "
        "Specialist agents have already fetched the relevant business data for you — it is provided below. "
        "Your job is to synthesize this data into a clear, structured, actionable response.\n\n"
        "Rules:\n"
        "- Use ₹ for all amounts. Be specific: name customers, products, dates.\n"
        "- Organise with clear headers (## Revenue, ## Inventory, ## Action Plan etc.).\n"
        "- End with a prioritised ## Action Plan — top 3 specific actions the owner should take today.\n"
        "- Never invent numbers. Only use data provided by the agents."
    )

    # Include last 2 turns only (4 messages max) — prevents token bloat as session grows
    recent_history = state.get("history", [])[-4:]
    messages = []
    for msg in recent_history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({
        "role": "user",
        "content": (
            f"Goal: {overall_goal}\n\n"
            f"--- Agent-fetched data ---\n{combined_data}\n"
            f"-------------------------\n\n"
            f"Original query: {state['user_query']}"
        )
    })

    try:
        resp = client.chat.completions.create(
            messages=[{"role": "system", "content": SYSTEM}] + messages,
            model=MODEL_SYNTH,   # big model — needs reasoning + synthesis
            temperature=0.2,
            max_tokens=1200,
        )
        # Log tokens immediately after this call
        s_in  = resp.usage.prompt_tokens     or 0
        s_out = resp.usage.completion_tokens or 0
        _run_tokens["input"]  += s_in
        _run_tokens["output"] += s_out
        logger.info(f"[Synthesizer] Tokens — input: {s_in}, output: {s_out}")

        final = resp.choices[0].message.content
    except Exception as e:
        logger.error(f"[Synthesizer] Failed: {e}", exc_info=True)
        final = "I was unable to generate the growth plan. Please try again."

    logger.info(f"[Synthesizer] Done ({len(final)} chars).")
    return {**state, "final_response": final}


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
    logger.info("[AgentGraph] LangGraph multi-agent graph compiled ✓")
    return compiled


_graph = None

def get_agent_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ── Public entry point ────────────────────────────────────────────────

def run_agent_graph(user_query: str, business_id: int, history: list) -> str:
    """
    Entry point called by main_groq.py for AI_COMPLEX queries.
    Returns the final synthesized response string.
    Also logs token usage to the token_usage table.
    """
    global _run_tokens
    _run_tokens = {"input": 0, "output": 0}  # reset for this run

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
    }

    logger.info(f"[AgentGraph] ── Starting multi-agent run ──")
    result = graph.invoke(initial)
    logger.info(f"[AgentGraph] ── Multi-agent run complete ──")

    # Log combined token usage for the full agent run
    try:
        from database.db import SessionLocal
        from database.models import TokenUsage
        db = SessionLocal()
        try:
            db.add(TokenUsage(
                business_id   = business_id,
                model         = f"{MODEL_PLANNER}+{MODEL_SYNTH}",
                model_tier    = "AI_COMPLEX",
                input_tokens  = _run_tokens["input"],
                output_tokens = _run_tokens["output"],
                total_tokens  = _run_tokens["input"] + _run_tokens["output"],
                endpoint      = "/ask (multi-agent)",
            ))
            db.commit()
            logger.info(
                f"[AgentGraph] Tokens used — "
                f"input: {_run_tokens['input']}, output: {_run_tokens['output']}, "
                f"total: {_run_tokens['input'] + _run_tokens['output']}"
            )
        finally:
            db.close()
    except Exception as te:
        logger.warning(f"[AgentGraph] Failed to log token usage: {te}")

    return result["final_response"]
