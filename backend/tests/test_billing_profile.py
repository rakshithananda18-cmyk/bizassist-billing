"""
tests/test_billing_profile.py
=============================
Phase 2 — multi-type businesses + billing-counter profiles:
  • /business/setup accepts a single template_key (legacy) AND template_keys[]
  • business_types resolves lazily to [template_key] (no-backfill contract)
  • /business/billing-profile resolves per mode: entry mode, customer gating,
    line fields, counter widgets, invoice template default
  • unknown mode → primary; unknown keys normalise to `general` and dedupe
  • owner overrides apply to the PRIMARY vertical only
  • all vertical configs (incl. the new electronics/repair/mobile/b2b_supplier)
    load and resolve

Uses TestClient + a real signup (mirrors test_business_template style).
"""
import os
import sys
import uuid

os.environ["DATABASE_URL"] = "sqlite:///./test_bizassist.db"
os.environ["GROQ_API_KEY"] = "mock_groq_api_key"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from fastapi.testclient import TestClient
from main_groq import app
from core import templates as T

client = TestClient(app)

ALL_KEYS = {"general", "supermarket", "pharmacy", "restaurant", "wholesale",
            "hardware", "textile", "services",
            "electronics", "repair", "mobile", "b2b_supplier"}


def _signup(prefix: str) -> dict:
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username, "password": "TestPass123!",
        "business_name": f"{prefix} Biz",
    })
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    body = resp.json()
    return {"headers": {"Authorization": f"Bearer {body['token']}"}, "bid": body["id"]}


def _setup(acct, **body):
    r = client.post("/business/setup", json=body, headers=acct["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _profile(acct, mode=None):
    r = client.get("/business/billing-profile",
                   params=({"mode": mode} if mode else None),
                   headers=acct["headers"])
    assert r.status_code == 200, r.text
    return r.json()["profile"]


# ── Config integrity ──────────────────────────────────────────────────────────

def test_all_vertical_configs_load():
    keys = {t["key"] for t in T.list_templates()}
    assert ALL_KEYS <= keys, f"missing configs: {ALL_KEYS - keys}"
    for k in ALL_KEYS:
        cfg = T.get_template(k)
        assert cfg["key"] == k
        assert "billing" in cfg and "invoice_layout" in cfg


# ── Legacy single-type setup (unchanged behavior) ─────────────────────────────

def test_single_type_setup_legacy(gst=None):
    acct = _signup("test_bp_single")
    out = _setup(acct, template_key="supermarket")
    assert out["template_key"] == "supermarket"
    assert out["business_types"] == ["supermarket"]

    p = _profile(acct)
    assert p["mode_key"] == "supermarket"
    assert p["business_types"] == ["supermarket"]
    assert p["entry_mode"] == "barcode"
    assert p["customer_required"] is False
    assert p["tax_inclusive_default"] is True
    assert "split_tender" in p["counter_widgets"]
    assert p["invoice"]["default_template"] == "thermal"
    assert p["invoice"]["paper"] == "thermal_80mm"


def test_no_setup_falls_back_to_general():
    acct = _signup("test_bp_fresh")
    p = _profile(acct)
    assert p["mode_key"] == "general"
    assert p["business_types"] == ["general"]


# ── Multi-type setup + mode switching ─────────────────────────────────────────

def test_multi_type_setup_and_mode_switch():
    acct = _signup("test_bp_multi")
    out = _setup(acct, template_keys=["supermarket", "repair"])
    assert out["template_key"] == "supermarket"          # first = primary
    assert out["business_types"] == ["supermarket", "repair"]

    # default profile = primary
    p = _profile(acct)
    assert p["mode_key"] == "supermarket"
    assert p["entry_mode"] == "barcode"

    # mode switch → repair profile
    p2 = _profile(acct, mode="repair")
    assert p2["mode_key"] == "repair"
    assert p2["customer_required"] is True
    assert "job_card_no" in p2["line_fields"]
    assert "job_card" in p2["counter_widgets"]
    assert p2["invoice"]["default_template"] == "modern"  # a4_service layout
    assert p2["business_types"] == ["supermarket", "repair"]


def test_unregistered_mode_falls_back_to_primary():
    acct = _signup("test_bp_fallbk")
    _setup(acct, template_keys=["pharmacy"])
    p = _profile(acct, mode="restaurant")                 # not registered
    assert p["mode_key"] == "pharmacy"


def test_unknown_keys_normalise_and_dedupe():
    acct = _signup("test_bp_norm")
    out = _setup(acct, template_keys=["vaporwave", "supermarket", "supermarket"])
    # unknown → general; duplicates collapse; order preserved
    assert out["business_types"] == ["general", "supermarket"]
    assert out["template_key"] == "general"


# ── Vertical matrix (plan §2.2) ───────────────────────────────────────────────

@pytest.mark.parametrize("key,expect", [
    ("pharmacy",     {"line_has": "batch_no", "customer_required": False}),
    ("wholesale",    {"widget": "outstanding_balance", "customer_required": True,
                      "invoice_type": "B2B"}),
    ("electronics",  {"line_has": "serial_no", "widget": "serial_capture"}),
    ("mobile",       {"line_has": "serial_no", "entry": "barcode"}),
    ("b2b_supplier", {"widget": "b2b_order_convert", "customer_required": True,
                      "invoice_type": "B2B"}),
    ("services",     {"line_has": "sac", "customer_required": True}),
    ("hardware",     {"widget": "delivery_challan"}),
    ("textile",      {"line_has": "size"}),
    ("restaurant",   {"widget": "table_token", "entry": "menu"}),
])
def test_vertical_profile_matrix(key, expect):
    acct = _signup(f"test_bp_{key[:6]}")
    _setup(acct, template_key=key)
    p = _profile(acct)
    assert p["mode_key"] == key
    if "line_has" in expect:
        assert expect["line_has"] in p["line_fields"], p["line_fields"]
    if "widget" in expect:
        assert expect["widget"] in p["counter_widgets"], p["counter_widgets"]
    if "customer_required" in expect:
        assert p["customer_required"] is expect["customer_required"]
    if "invoice_type" in expect:
        assert p["default_invoice_type"] == expect["invoice_type"]
    if "entry" in expect:
        assert p["entry_mode"] == expect["entry"]


# ── Overrides apply to the primary only ───────────────────────────────────────

def test_overrides_apply_to_primary_only():
    acct = _signup("test_bp_ovr")
    _setup(acct, template_keys=["wholesale", "supermarket"])
    r = client.patch("/business/config", headers=acct["headers"],
                     json={"overrides": {"billing": {"entry_mode": "barcode"}}})
    assert r.status_code == 200, r.text

    assert _profile(acct)["entry_mode"] == "barcode"                # primary: overridden
    assert _profile(acct, mode="supermarket")["entry_mode"] == "barcode"  # its own default anyway
    # a secondary vertical whose template default differs stays CLEAN:
    acct2 = _signup("test_bp_ovr2")
    _setup(acct2, template_keys=["supermarket", "wholesale"])
    client.patch("/business/config", headers=acct2["headers"],
                 json={"overrides": {"billing": {"entry_mode": "menu"}}})
    assert _profile(acct2)["entry_mode"] == "menu"                  # primary overridden
    assert _profile(acct2, mode="wholesale")["entry_mode"] == "search"  # clean template


# ── Primary-change still clears overrides (existing contract) ────────────────

def test_primary_change_clears_overrides():
    acct = _signup("test_bp_clear")
    _setup(acct, template_key="supermarket")
    client.patch("/business/config", headers=acct["headers"],
                 json={"overrides": {"billing": {"entry_mode": "menu"}}})
    assert _profile(acct)["entry_mode"] == "menu"
    _setup(acct, template_keys=["pharmacy", "supermarket"])         # primary changes
    assert _profile(acct)["entry_mode"] == "search"                 # pharmacy default, overrides gone


# ── Logging ───────────────────────────────────────────────────────────────────

def test_profile_emits_applied_log(caplog):
    import logging
    acct = _signup("test_bp_log")
    _setup(acct, template_key="pharmacy")
    with caplog.at_level(logging.INFO, logger="bizassist.templates"):
        _profile(acct)
    assert any("billing_profile_applied" in r.message and "mode_key=pharmacy" in r.message
               for r in caplog.records)
