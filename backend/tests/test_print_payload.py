"""
tests/test_print_payload.py
===========================
The InvoicePrintPayload v1 (invoice-template system, Phase 1):
  • GST business → full payload: seller/buyer GSTIN, tax columns, HSN summary
  • non-GST business → gst_mode=False, simplified columns, no tax leakage
  • split payments appear as rows; credit invoice balance math
  • payload_hash determinism (the "switching templates never mutates" anchor)
  • tenant isolation (user B cannot read user A's payload)
  • amount-in-words (Indian numbering) unit cases
  • /sales/print-events beacon: accepted actions log, unknown action 422
  • settings: print.invoice_template default + round-trip

Uses TestClient + a real signup (mirrors test_sales_api style).
"""
import logging
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
from database.models import Product, Inventory, User, Customer, Invoice
from core.models import InvoicePayment
from core.billing.print_payload import amount_in_words

client = TestClient(app)


def _signup(prefix: str) -> dict:
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    resp = client.post("/signup", json={
        "username": username, "password": "TestPass123!",
        "business_name": f"{prefix} Biz",
    })
    assert resp.status_code == 200, f"Signup failed: {resp.text}"
    body = resp.json()
    return {"headers": {"Authorization": f"Bearer {body['token']}"}, "bid": body["id"]}


@pytest.fixture(scope="module")
def gst_biz():
    """A GST-registered Karnataka business with a product + a B2B customer."""
    acct = _signup("test_pp_gst")
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == acct["bid"]).first()
        u.gstin = "29ABCDE1234F1Z5"
        u.state_code = "29"
        u.address = "12 MG Road, Bengaluru"
        u.phone = "9876543210"
        p = Product(business_id=acct["bid"], name="Steel Bolt M8", sku="BOLT8",
                    unit="Pcs", hsn_sac="7318", cgst_rate=9, sgst_rate=9, igst_rate=18,
                    selling_price=50, mrp=60.0, track_inventory=True)
        db.add(p)
        db.flush()
        db.add(Inventory(business_id=acct["bid"], product_name="Steel Bolt M8",
                         product_id=p.id, stock=500))
        c = Customer(business_id=acct["bid"], name="Mehta Traders",
                     gstin="29FGHIJ5678K1Z2", state_code="29",
                     phone="9000000001", address="4 market road, Mysuru")
        db.add(c)
        db.commit()
        acct["pid"], acct["cid"] = p.id, c.id
    finally:
        db.close()
    return acct


@pytest.fixture(scope="module")
def plain_biz():
    """A non-GST business (no GSTIN) with one untaxed product."""
    acct = _signup("test_pp_plain")
    db = SessionLocal()
    try:
        p = Product(business_id=acct["bid"], name="Loose Jaggery", unit="Kg",
                    selling_price=80, track_inventory=False)
        db.add(p)
        db.commit()
        acct["pid"] = p.id
    finally:
        db.close()
    return acct


def _make_sale(acct, **overrides):
    body = {
        "lines": [{"product_id": acct["pid"], "quantity": 4, "unit_price": 50.0}],
        "customer_id": acct.get("cid"),
        "payment_mode": "Cash",
        "paid_amount": 0.0,
    }
    body.update(overrides)
    r = client.post("/sales", json=body, headers=acct["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _payload(acct, invoice_no):
    r = client.get(f"/sales/{invoice_no}/print-payload", headers=acct["headers"])
    assert r.status_code == 200, r.text
    return r.json()


# ── GST payload ───────────────────────────────────────────────────────────────

def test_gst_payload_has_required_sections(gst_biz):
    inv = _make_sale(gst_biz, invoice_type="B2B", place_of_supply="29-Karnataka")
    pl = _payload(gst_biz, inv["invoice_no"])

    assert pl["version"] == 1
    for section in ("invoice", "seller", "buyer", "lines", "totals",
                    "payments", "tax_summary", "footer", "visibility", "meta"):
        assert section in pl, f"missing section {section}"

    assert pl["seller"]["gstin"] == "29ABCDE1234F1Z5"
    assert pl["seller"]["state_code"] == "29"
    assert pl["seller"]["state"] == "Karnataka"
    assert pl["invoice"]["title"] == "Tax Invoice"
    assert pl["invoice"]["number"] == inv["invoice_no"]
    assert pl["buyer"]["gstin"] == "29FGHIJ5678K1Z2"       # from the customer record
    assert pl["buyer"]["customer_type"] == "registered"
    assert pl["invoice"]["place_of_supply"] == "29-Karnataka"

    v = pl["visibility"]
    assert v["gst_mode"] is True
    assert v["igst_mode"] is False                          # intra-state
    for col in ("hsn", "taxable", "gst", "cgst", "sgst"):
        assert col in v["columns"]
    assert "igst" not in v["columns"]

    # per-line tax + HSN annexure
    line = pl["lines"][0]
    assert line["hsn_sac"] == "7318"
    assert line["gst_rate"] == 18.0
    assert line["cgst"] > 0 and line["sgst"] > 0 and line["igst"] == 0
    assert pl["tax_summary"] and pl["tax_summary"][0]["hsn"] == "7318"

    # totals foot: taxable + tax == grand (intra, no discounts, round-off aside)
    t = pl["totals"]
    assert t["grand_total"] == pytest.approx(
        t["taxable_amount"] + t["cgst_total"] + t["sgst_total"] + t["round_off"], abs=0.02)
    assert t["amount_in_words"].endswith("Only")
    assert len(pl["meta"]["payload_hash"]) == 64


def test_mrp_snapshot_on_line(gst_biz):
    inv = _make_sale(gst_biz)
    pl = _payload(gst_biz, inv["invoice_no"])
    assert pl["lines"][0]["mrp"] == 60.0                    # snapshotted from the product
    assert "mrp" in pl["visibility"]["columns"]


# ── Non-GST payload ───────────────────────────────────────────────────────────

def test_non_gst_payload_hides_tax_safely(plain_biz):
    inv = _make_sale(plain_biz, lines=[{"product_id": plain_biz["pid"],
                                        "quantity": 2, "unit_price": 80.0}])
    pl = _payload(plain_biz, inv["invoice_no"])

    v = pl["visibility"]
    assert v["gst_mode"] is False
    for col in ("hsn", "gst", "cgst", "sgst", "igst", "taxable"):
        assert col not in v["columns"]
    assert pl["tax_summary"] == []
    assert pl["seller"]["gstin"] is None
    assert pl["invoice"]["title"] == "Retail Invoice"
    assert pl["totals"]["grand_total"] == pytest.approx(160.0)


# ── Payments & credit ─────────────────────────────────────────────────────────

def test_split_payment_rows(gst_biz):
    inv = _make_sale(gst_biz, paid_amount=100.0, payment_mode="Cash")
    db = SessionLocal()
    try:
        row = db.query(Invoice).filter(Invoice.id == inv["id"]).first()
        db.add(InvoicePayment(business_id=gst_biz["bid"], invoice_id=row.id,
                              amount_paid=36.0, payment_mode="UPI",
                              idempotency_key=uuid.uuid4().hex))
        row.paid_amount = 136.0
        db.commit()
    finally:
        db.close()

    pl = _payload(gst_biz, inv["invoice_no"])
    modes = sorted(p["mode"] for p in pl["payments"])
    assert modes == ["Cash", "UPI"]
    assert sum(p["amount"] for p in pl["payments"]) == pytest.approx(pl["totals"]["amount_paid"])


def test_credit_invoice_balance(gst_biz):
    inv = _make_sale(gst_biz, paid_amount=50.0, due_date="2026-08-01")
    pl = _payload(gst_biz, inv["invoice_no"])
    t = pl["totals"]
    assert t["balance_due"] == pytest.approx(t["grand_total"] - 50.0)
    assert pl["invoice"]["due_date"] == "2026-08-01"
    assert "balance_due" in pl["visibility"]["blocks"]


# ── Determinism / isolation ───────────────────────────────────────────────────

def test_payload_hash_deterministic(gst_biz):
    inv = _make_sale(gst_biz)
    h1 = _payload(gst_biz, inv["invoice_no"])["meta"]["payload_hash"]
    h2 = _payload(gst_biz, inv["invoice_no"])["meta"]["payload_hash"]
    assert h1 == h2


def test_tenant_isolation(gst_biz, plain_biz):
    inv = _make_sale(gst_biz)
    r = client.get(f"/sales/{inv['invoice_no']}/print-payload",
                   headers=plain_biz["headers"])
    assert r.status_code == 404


# ── Amount in words ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("amount,expected", [
    (0, "Zero Rupees Only"),
    (1, "One Rupees Only"),
    (10.50, "Ten Rupees and Fifty Paise Only"),
    (100000, "One Lakh Rupees Only"),
    (10000000, "One Crore Rupees Only"),
    (9999999.99,
     "Ninety Nine Lakh Ninety Nine Thousand Nine Hundred and Ninety Nine Rupees"
     " and Ninety Nine Paise Only"),
])
def test_amount_in_words(amount, expected):
    assert amount_in_words(amount) == expected


# ── Logging events ────────────────────────────────────────────────────────────

def test_payload_build_emits_log(gst_biz, caplog):
    inv = _make_sale(gst_biz)
    with caplog.at_level(logging.INFO, logger="bizassist.invoice_render"):
        _payload(gst_biz, inv["invoice_no"])
    msgs = [r.message for r in caplog.records if "[INVOICE_RENDER]" in r.message]
    assert any("action=payload_built" in m for m in msgs)
    assert any(f"business_id={gst_biz['bid']}" in m for m in msgs)


def test_print_event_beacon(gst_biz, caplog):
    with caplog.at_level(logging.INFO, logger="bizassist.invoice_render"):
        r = client.post("/sales/print-events", headers=gst_biz["headers"], json={
            "action": "template_selected", "invoice_no": "INV-1",
            "template_type": "modern",
        })
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert any("action=template_selected" in rec.message and "template_type=modern" in rec.message
               for rec in caplog.records)


def test_print_event_unknown_action_rejected(gst_biz):
    r = client.post("/sales/print-events", headers=gst_biz["headers"],
                    json={"action": "rm_rf_slash", "template_type": "classic"})
    assert r.status_code == 422


# ── Template preference (settings round-trip) ────────────────────────────────

def test_invoice_template_setting_roundtrip(gst_biz):
    r = client.get("/settings", headers=gst_biz["headers"])
    assert r.status_code == 200
    assert r.json()["print"]["invoice_template"] == "classic"   # default

    r = client.put("/settings", headers=gst_biz["headers"],
                   json={"print": {"invoice_template": "modern"}})
    assert r.status_code == 200

    r = client.get("/settings", headers=gst_biz["headers"])
    assert r.json()["print"]["invoice_template"] == "modern"


def test_payload_reports_template_default(gst_biz):
    """meta.template_default reflects the saved business default."""
    inv = _make_sale(gst_biz)
    pl = _payload(gst_biz, inv["invoice_no"])
    assert pl["meta"]["template_default"] in ("classic", "modern", "thermal")
