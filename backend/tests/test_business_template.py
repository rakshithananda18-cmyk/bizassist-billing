"""
tests/test_business_template.py
===============================
The Business Template System (Phase 1B §1):
  • all 8 shipped templates load and carry the required shape
  • get_template falls back to `general` for an unknown key
  • resolve_for merges saved overrides over the template
  • validate_overrides deep-merges and rejects unknown top-level sections
  • vertical specifics: pharmacy tracks batch+expiry; restaurant items are
    non-stock by default; textile exposes the size/colour variant attrs
  • endpoints: GET /business/templates, POST /business/setup,
    GET/PATCH /business/config — scoped to the caller's business
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
from database.db import SessionLocal
from core.models import BusinessSettings
from core import templates as T

client = TestClient(app)

SHIPPED = {"supermarket", "pharmacy", "restaurant", "textile",
           "wholesale", "hardware", "services", "general"}


# ── Pure loader unit tests ───────────────────────────────────────────────────

def test_all_templates_load_and_have_shape():
    keys = {t["key"] for t in T.list_templates()}
    assert SHIPPED.issubset(keys), f"missing templates: {SHIPPED - keys}"
    for key in SHIPPED:
        cfg = T.get_template(key)
        assert cfg["key"] == key
        assert cfg.get("label")
        # required sections present
        for section in ("terminology", "billing", "inventory", "product_fields", "invoice_layout"):
            assert section in cfg, f"{key} missing {section}"
        assert cfg["terminology"].get("customer")
        assert isinstance(cfg["billing"].get("payment_modes"), list)
        assert isinstance(cfg["product_fields"], list) and cfg["product_fields"]


def test_unknown_key_falls_back_to_general():
    cfg = T.get_template("does_not_exist")
    assert cfg["key"] == "general"


def test_pharmacy_tracks_batch_and_expiry():
    cfg = T.get_template("pharmacy")
    assert cfg["inventory"]["track_batch"] is True
    assert cfg["inventory"]["track_expiry"] is True
    assert cfg["billing"]["tax_inclusive_default"] is True
    assert cfg["terminology"]["customer"] == "Patient"


def test_restaurant_items_are_non_stock_by_default():
    cfg = T.get_template("restaurant")
    assert cfg["inventory"].get("track_inventory_default") is False
    assert cfg["billing"]["entry_mode"] == "menu"


def test_textile_exposes_variant_attributes():
    schema = T.attributes_schema("textile")
    attrs = {a["attr"] for a in schema}
    assert {"size", "colour"}.issubset(attrs)
    assert "variant_matrix" in T.get_template("textile")["workflows"]


def test_supermarket_is_barcode_first_with_loose_qty():
    cfg = T.get_template("supermarket")
    assert cfg["billing"]["entry_mode"] == "barcode"
    assert cfg["inventory"]["loose_qty"] is True


def test_validate_overrides_merges_and_guards():
    # legitimate override: flip a billing default + a label
    resolved = T.validate_overrides("pharmacy", {
        "billing": {"tax_inclusive_default": False},
        "terminology": {"customer": "Client"},
    })
    assert resolved["billing"]["tax_inclusive_default"] is False
    assert resolved["terminology"]["customer"] == "Client"
    # untouched keys survive the deep-merge
    assert resolved["inventory"]["track_batch"] is True
    assert resolved["key"] == "pharmacy"
    # cannot rename the vertical via overrides
    forced = T.validate_overrides("pharmacy", {"key": "supermarket"})
    assert forced["key"] == "pharmacy"
    # cannot introduce a brand-new top-level section
    with pytest.raises(ValueError):
        T.validate_overrides("pharmacy", {"secret_section": {"x": 1}})


# ── DB-backed resolution ─────────────────────────────────────────────────────

def test_resolve_for_uses_saved_template_and_overrides():
    import json
    db = SessionLocal()
    try:
        bid = 990001
        db.query(BusinessSettings).filter(BusinessSettings.business_id == bid).delete()
        db.add(BusinessSettings(
            business_id=bid, template_key="textile",
            overrides=json.dumps({"billing": {"tax_inclusive_default": True}}),
        ))
        db.commit()
        cfg = T.resolve_for(bid, db)
        assert cfg["key"] == "textile"
        assert cfg["billing"]["tax_inclusive_default"] is True   # override applied
        assert cfg["inventory"]["default_uoms"]                  # template base survives
    finally:
        db.query(BusinessSettings).filter(BusinessSettings.business_id == 990001).delete()
        db.commit()
        db.close()


def test_resolve_for_defaults_to_general_when_no_row():
    db = SessionLocal()
    try:
        cfg = T.resolve_for(999999, db)  # no settings row
        assert cfg["key"] == "general"
    finally:
        db.close()


# ── Endpoint tests (scoped to the caller) ────────────────────────────────────

@pytest.fixture(scope="module")
def auth():
    username = f"test_tmpl_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username, "password": "TestPass123!", "business_name": "Template Test Biz",
    })
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    body = resp.json()
    return {"headers": {"Authorization": f"Bearer {body['token']}"}, "bid": body["id"]}


def test_get_templates_endpoint():
    resp = client.get("/business/templates")
    assert resp.status_code == 200, resp.text
    keys = {t["key"] for t in resp.json()["templates"]}
    assert SHIPPED.issubset(keys)


def test_setup_and_get_config_scoped(auth):
    # default before setup → general
    resp = client.get("/business/config", headers=auth["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["config"]["key"] == "general"

    # switch to pharmacy
    resp = client.post("/business/setup", headers=auth["headers"], json={"template_key": "pharmacy"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["config"]["key"] == "pharmacy"

    # config now reflects pharmacy + attributes schema for the form
    resp = client.get("/business/config", headers=auth["headers"])
    body = resp.json()
    assert body["config"]["key"] == "pharmacy"
    assert body["config"]["terminology"]["customer"] == "Patient"
    attrs = {a["attr"] for a in body["attributes_schema"]}
    assert "salt" in attrs and "drug_schedule" in attrs


def test_patch_config_override(auth):
    # ensure a known template first
    client.post("/business/setup", headers=auth["headers"], json={"template_key": "supermarket"})
    resp = client.patch("/business/config", headers=auth["headers"], json={
        "overrides": {"terminology": {"customer": "Guest"}},
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["config"]["terminology"]["customer"] == "Guest"
    # persisted on re-fetch
    resp = client.get("/business/config", headers=auth["headers"])
    assert resp.json()["config"]["terminology"]["customer"] == "Guest"


def test_patch_config_rejects_bad_override(auth):
    client.post("/business/setup", headers=auth["headers"], json={"template_key": "general"})
    resp = client.patch("/business/config", headers=auth["headers"], json={
        "overrides": {"not_a_real_section": {"x": 1}},
    })
    assert resp.status_code == 422, resp.text


def test_unauthenticated_config_blocked():
    resp = client.get("/business/config")
    assert resp.status_code == 401
