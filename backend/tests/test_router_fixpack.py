"""
tests/test_router_fixpack.py
============================
The LLM-router "honor the decision" fix pack (from the live-trace review):

  B1  confidence floor — a low-confidence decision is dropped, legacy stands.
  B2  entity reroute   — a named customer + non-customer-scoped intent → client_summary.
  B3  invoice_detail   — bare INV-#### regex + an explicit extracted invoice_id wins.
  B4  action scoping   — reminders preview scopes to a single named target.
  B5  advise prompt    — bans hypothetical names/amounts.

B1/B2 are tested through the pure helper `_resolve_llm_decision`; B3/B4 against a
seeded DB; B5 is a prompt-content assertion.
"""
import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from database.db import SessionLocal
from database.models import Base, Invoice
from services.llm_router import RouteDecision

BID = 664422


def _ensure_schema():
    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
    finally:
        db.close()


def _clear():
    db = SessionLocal()
    try:
        db.query(Invoice).filter(Invoice.business_id == BID).delete()
        db.commit()
    finally:
        db.close()


def _seed():
    db = SessionLocal()
    try:
        db.add_all([
            Invoice(business_id=BID, invoice_id="INV-0007", customer="Sri Venkateswara Stores",
                    product="Rice", amount=800, status="Overdue",
                    invoice_date="2025-01-15", due_date="2025-01-30"),
            Invoice(business_id=BID, invoice_id="INV-0002", customer="Daily Needs Store",
                    product="Oil", amount=39393, status="Overdue",
                    invoice_date="2026-01-15", due_date="2026-01-30"),
        ])
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup():
    _ensure_schema()
    _clear()
    _seed()
    yield
    _clear()


# ── B1: confidence floor ─────────────────────────────────────────────────────

def test_b1_low_confidence_keeps_legacy():
    from services.ai_router import _resolve_llm_decision, _LLM_CONF_FLOOR
    # "Do you know rahul traders" → mode=chat conf=0.00 in the live trace.
    d = RouteDecision(mode="chat", intent=None, entities={"customer": "rahul traders"},
                      confidence=0.0)
    route, handler, ents, accepted = _resolve_llm_decision(d, "DIRECT", "client_summary")
    assert accepted is False
    assert (route, handler) == ("DIRECT", "client_summary")   # legacy stands


def test_b1_just_below_floor_rejected():
    from services.ai_router import _resolve_llm_decision, _LLM_CONF_FLOOR
    d = RouteDecision(mode="answer", intent="top_debtors", confidence=_LLM_CONF_FLOOR - 0.01)
    _, _, _, accepted = _resolve_llm_decision(d, "AI_SIMPLE", None)
    assert accepted is False


# ── B2: entity reroute ───────────────────────────────────────────────────────

def test_b2_named_customer_reroutes_to_client_summary():
    from services.ai_router import _resolve_llm_decision
    # "How much does Nilgiris Fresh owe me?" → answer/top_debtors + customer entity.
    d = RouteDecision(mode="answer", intent="top_debtors",
                      entities={"customer": "Nilgiris Fresh"}, confidence=0.8)
    route, handler, ents, accepted = _resolve_llm_decision(d, "DIRECT", "top_debtors")
    assert accepted and (route, handler) == ("DIRECT", "client_summary")
    assert ents["customer"] == "Nilgiris Fresh"


def test_b2_chat_with_customer_is_not_dropped_to_chat():
    from services.ai_router import _resolve_llm_decision
    d = RouteDecision(mode="chat", intent=None,
                      entities={"customer": "Rahul Traders"}, confidence=0.9)
    route, handler, _, accepted = _resolve_llm_decision(d, "AI_SIMPLE", None)
    assert accepted and (route, handler) == ("DIRECT", "client_summary")


def test_b2_customer_scoped_intent_not_rerouted():
    from services.ai_router import _resolve_llm_decision
    # invoice_detail already names one invoice → leave it, don't reroute.
    d = RouteDecision(mode="answer", intent="invoice_detail",
                      entities={"customer": "X", "invoice_id": "INV-0007"}, confidence=1.0)
    route, handler, _, accepted = _resolve_llm_decision(d, "DIRECT", "invoice_detail")
    assert accepted and handler == "invoice_detail"


def test_b2_advise_with_customer_keeps_advise():
    from services.ai_router import _resolve_llm_decision
    # advise is not 'answer'/'chat' → no reroute (it grounds on its own handler).
    d = RouteDecision(mode="advise", intent="top_customers",
                      entities={"customer": "X"}, confidence=0.85)
    route, handler, _, accepted = _resolve_llm_decision(d, "AI_ADVISE", "top_customers")
    assert accepted and (route, handler) == ("AI_ADVISE", "top_customers")


# ── B3: invoice_detail ───────────────────────────────────────────────────────

def test_b3_bare_invoice_id_matches():
    from services.handlers.invoices import _invoice_detail
    md = _invoice_detail(BID, "Invoice INV-0007 for Sri Venkateswara Stores: status and amount")
    assert md and "INV-0007" in md and "800" in md
    assert "Sri Venkateswara Stores" in md


def test_b3_explicit_invoice_id_wins_over_query_text():
    from services.handlers.invoices import _invoice_detail
    # query mentions INV-0002 but the extracted entity is INV-0007 → trust the entity
    md = _invoice_detail(BID, "tell me about INV-0002", invoice_id="INV-0007")
    assert "INV-0007" in md and "800" in md
    assert "39393" not in md.replace(",", "")   # not the INV-0002 amount


def test_b3_handle_passes_invoice_id_param():
    from services.direct_query_handler import handle
    md = handle("invoice_detail", "tell me about INV-0002", BID,
                params={"invoice_id": "INV-0007"})
    assert md and "INV-0007" in md and "800" in md


# ── B4: action target scoping ────────────────────────────────────────────────

def test_b4_reminders_preview_scopes_to_named_customer():
    from services.actions import _reminders_preview
    prev = _reminders_preview(BID, {"customer": "Sri Venkateswara Stores"})
    assert prev["count"] == 1
    assert prev["items"][0]["customer"] == "Sri Venkateswara Stores"


def test_b4_reminders_preview_resolves_invoice_id_to_customer():
    from services.actions import _reminders_preview
    prev = _reminders_preview(BID, {"invoice_id": "INV-0007"})
    assert prev["count"] == 1
    assert prev["items"][0]["customer"] == "Sri Venkateswara Stores"


def test_b4_no_target_still_previews_all():
    from services.actions import _reminders_preview
    prev = _reminders_preview(BID, {})
    assert prev["count"] == 2   # both overdue customers


# ── B5: advise prompt bans hypotheticals ─────────────────────────────────────

def test_b5_advise_prompt_forbids_hypotheticals():
    from services.ai_router import _ADVISE_SYSTEM_PROMPT
    p = _ADVISE_SYSTEM_PROMPT.lower()
    assert "hypothetical" in p
    assert "never invent" in p or "must appear" in p
