"""
tests/test_einvoice.py — GST e-invoice (INV-01) & e-way-bill JSON builders.
===========================================================================
The builders are PURE (ORM objects in, dict out), so these tests use lightweight
stand-in objects — no DB, no test_bizassist.db rebuild. They assert the schema
shape, the intra/inter tax split, money reconciliation (item sums vs ValDtls to
within the IRP's ₹1 tolerance), the DD/MM/YYYY date format, and that every
mandatory-field gap raises a warning instead of emitting silently-invalid JSON.
"""
from types import SimpleNamespace as NS

from core.compliance import einvoice


def _line(name, hsn, qty, up, tv, cg, sg, ig, cr, sr, igr, disc=0.0):
    return NS(product_name=name, hsn_sac=hsn, unit="NOS", quantity=qty, unit_price=up,
              discount=disc, taxable_value=tv, cgst_amount=cg, sgst_amount=sg,
              igst_amount=ig, cess_amount=0.0, cgst_rate=cr, sgst_rate=sr,
              igst_rate=igr, cess_rate=0.0)


def _intra_invoice():
    lines = [_line("Rice", "1006", 2, 100, 200, 5, 5, 0, 2.5, 2.5, 0),
             _line("Soap", "3401", 1, 120, 120, 7.2, 7.2, 0, 6, 6, 0)]
    inv = NS(invoice_id="INV-001", invoice_date="2026-06-21", place_of_supply="29",
             reverse_charge=False, igst_total=0.0, cgst_total=12.2, sgst_total=12.2,
             cess_total=0.0, subtotal=320.0, total_amount=344.0, round_off=-0.4,
             cash_discount=0.0, business_id=1, line_items=lines, irn=None)
    seller = NS(gstin="29ABCDE1234F1Z5", business_name="MR Traders",
                address="12 MG Road, Bengaluru, 560001", state_code="29",
                phone="9876543210", email="mr@traders.in")
    buyer = NS(name="Kirana Mart", gstin="29XYZAB6789C1Z2",
               address="5 Market St, Mysuru, 570001", state_code="29",
               phone="9000000000", email="km@mart.in")
    return seller, inv, buyer


def _inter_invoice():
    lines = [_line("Pump", "8413", 1, 1000, 1000, 0, 0, 180, 0, 0, 18)]
    inv = NS(invoice_id="INV-INT", invoice_date="2026-06-21", place_of_supply="27",
             reverse_charge=False, igst_total=180.0, cgst_total=0.0, sgst_total=0.0,
             cess_total=0.0, subtotal=1000.0, total_amount=1180.0, round_off=0.0,
             cash_discount=0.0, business_id=1, line_items=lines, irn=None)
    seller = NS(gstin="29ABCDE1234F1Z5", business_name="MR Traders",
                address="12 MG Road, Bengaluru, 560001", state_code="29",
                phone="", email="")
    buyer = NS(name="Mumbai Buyer", gstin="27PQRST1234A1Z9",
               address="9 Hill Rd, Mumbai, 400050", state_code="27", phone="", email="")
    return seller, inv, buyer


# ── e-invoice (INV-01) ────────────────────────────────────────────────────────

def test_einvoice_schema_shape_and_clean():
    seller, inv, buyer = _intra_invoice()
    payload, warnings = einvoice.build_einvoice_payload(seller=seller, invoice=inv, buyer=buyer)
    for sec in ("Version", "TranDtls", "DocDtls", "SellerDtls", "BuyerDtls", "ItemList", "ValDtls"):
        assert sec in payload
    assert payload["Version"] == "1.1"
    assert payload["TranDtls"]["SupTyp"] == "B2B"
    assert payload["DocDtls"]["Typ"] == "INV"
    assert payload["DocDtls"]["No"] == "INV-001"
    assert payload["DocDtls"]["Dt"] == "21/06/2026"   # DD/MM/YYYY
    assert warnings == []                              # fully-populated B2B sale


def test_einvoice_money_reconciles_within_one_rupee():
    seller, inv, buyer = _intra_invoice()
    payload, _ = einvoice.build_einvoice_payload(seller=seller, invoice=inv, buyer=buyer)
    v = payload["ValDtls"]
    items = payload["ItemList"]
    sum_item = round(sum(i["TotItemVal"] for i in items), 2)
    # AssVal + all taxes == Σ item values
    assert round(v["AssVal"] + v["CgstVal"] + v["SgstVal"] + v["IgstVal"] + v["CesVal"], 2) == sum_item
    # TotInvVal == Σ TotItemVal + round-off, within the IRP's ₹1 tolerance
    assert abs(v["TotInvVal"] - (sum_item + v["RndOffAmt"])) < 1.0


def test_einvoice_intra_state_split():
    seller, inv, buyer = _intra_invoice()
    payload, _ = einvoice.build_einvoice_payload(seller=seller, invoice=inv, buyer=buyer)
    v = payload["ValDtls"]
    assert v["IgstVal"] == 0
    assert v["CgstVal"] == 12.2 and v["SgstVal"] == 12.2
    assert payload["ItemList"][0]["GstRt"] == 5.0     # 2.5 + 2.5
    assert payload["ItemList"][1]["GstRt"] == 12.0    # 6 + 6


def test_einvoice_inter_state_split():
    seller, inv, buyer = _inter_invoice()
    payload, warnings = einvoice.build_einvoice_payload(seller=seller, invoice=inv, buyer=buyer)
    v = payload["ValDtls"]
    assert v["CgstVal"] == 0 and v["SgstVal"] == 0
    assert v["IgstVal"] == 180.0
    assert payload["ItemList"][0]["GstRt"] == 18.0
    assert payload["BuyerDtls"]["Pos"] == "27"
    assert warnings == []


def test_einvoice_b2c_and_missing_fields_warn():
    lines = [_line("Tea", "", 1, 50, 50, 0, 0, 0, 0, 0, 0)]
    inv = NS(invoice_id="INV-002", invoice_date="2026-06-21", place_of_supply="",
             reverse_charge=False, igst_total=0.0, cgst_total=0.0, sgst_total=0.0,
             cess_total=0.0, subtotal=50.0, total_amount=47.0, round_off=0.0,
             cash_discount=3.0, business_id=1, line_items=lines, irn=None)
    seller = NS(gstin="", business_name="", address="", state_code="", phone="", email="")
    payload, warnings = einvoice.build_einvoice_payload(seller=seller, invoice=inv, buyer=None)
    assert payload["BuyerDtls"]["Gstin"] == "URP"
    joined = " | ".join(warnings)
    assert "Seller GSTIN" in joined
    assert "Buyer GSTIN" in joined
    assert "HSN/SAC" in joined
    assert "Cash discount" in joined          # cash-discount caveat surfaced


def test_einvoice_reverse_charge_flag():
    seller, inv, buyer = _intra_invoice()
    inv.reverse_charge = True
    payload, _ = einvoice.build_einvoice_payload(seller=seller, invoice=inv, buyer=buyer)
    assert payload["TranDtls"]["RegRev"] == "Y"


# ── e-Way Bill ────────────────────────────────────────────────────────────────

def test_eway_clean_with_transport():
    seller, inv, buyer = _intra_invoice()
    payload, warnings = einvoice.build_eway_payload(
        seller=seller, invoice=inv, buyer=buyer,
        transport={"mode": "road", "distance": 42, "vehicle_no": "ka01ab1234"})
    assert payload["docNo"] == "INV-001"
    assert payload["docDate"] == "21/06/2026"
    assert payload["transMode"] == "1"            # road
    assert payload["transDistance"] == "42"
    assert payload["vehicleNo"] == "KA01AB1234"   # upper-cased
    assert payload["fromStateCode"] == 29 and payload["toStateCode"] == 29
    assert len(payload["itemList"]) == 2
    assert warnings == []


def test_eway_missing_transport_warns():
    seller, inv, buyer = _intra_invoice()
    _, warnings = einvoice.build_eway_payload(
        seller=seller, invoice=inv, buyer=buyer, transport={"mode": "road"})
    joined = " | ".join(warnings)
    assert "distance" in joined.lower()
    assert "vehicle number or transport document" in joined.lower()


def test_eway_mode_mapping():
    seller, inv, buyer = _intra_invoice()
    for word, code in (("rail", "2"), ("air", "3"), ("ship", "4"), ("road", "1")):
        payload, _ = einvoice.build_eway_payload(
            seller=seller, invoice=inv, buyer=buyer,
            transport={"mode": word, "distance": 10, "vehicle_no": "KA01AB1234"})
        assert payload["transMode"] == code


# ── threshold gating (R7a-next) ───────────────────────────────────────────────

def test_eway_required_threshold():
    """E-way bill is mandatory only ABOVE ₹50,000 (strictly greater)."""
    assert einvoice.EWAY_THRESHOLD == 50000.0
    assert einvoice.eway_required(NS(total_amount=50001)) is True
    assert einvoice.eway_required(NS(total_amount=50000)) is False   # exactly at limit
    assert einvoice.eway_required(NS(total_amount=49999.99)) is False
    assert einvoice.eway_required(NS(total_amount=120000)) is True
    assert einvoice.eway_required(NS(total_amount=0)) is False


def test_einvoice_applicable_is_flag_gated():
    """E-invoice applicability is the owner-set turnover flag (₹5 cr is PAN-level,
    not computable from one tenant's data)."""
    assert einvoice.einvoice_applicable(True) is True
    assert einvoice.einvoice_applicable(False) is False
    assert einvoice.einvoice_applicable(None) is False
    assert einvoice.einvoice_applicable("") is False
    assert einvoice.einvoice_applicable(1) is True
