"""
tests/test_print_and_einvoice_pure.py — the customer-facing money surfaces.
==========================================================================
Direct unit coverage of the deterministic core of `core/billing/print_payload.py`
and `core/compliance/einvoice.py` — the two modules that turn stored figures into
**the document a customer receives and the payload a tax authority validates**.

Measured before writing this: of 14 functions in `print_payload.py`, 12 had no
reference anywhere in the test corpus; of 11 in `einvoice.py`, 5 had none. The
covered ones were `amount_in_words`, `_r2`, `build_einvoice_payload`,
`build_eway_payload`, `eway_required`, `einvoice_applicable`, `_state_code` — the
entry points. The helpers that actually shape the numbers were untested.

Why these two rank differently, stated so the priority is arguable:

  · **print_payload is silent when wrong.** A bad line total or a wrong tax
    annexure prints on a bill the customer keeps, and nothing in the system
    objects. Same failure class as M-2/M-7/M-11 — correct-looking output, wrong
    content.
  · **einvoice is loud when wrong.** A malformed IRN payload is rejected by the
    portal, so it fails visibly. It ranks below the bill for that reason, but a
    rejected e-invoice still blocks a shipment, and `_split_addr` / `_item_rows`
    are pure functions with fiddly rules that are cheap to pin.

No database. These are pure functions and the point is to exercise them without
one, so a failure here can only mean the arithmetic or the mapping is wrong.
"""
import os
import sys
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from core.billing import print_payload as PP
from core.compliance import einvoice as EI


# ══════════════════════════════════════════════════════════════════════════════
# print_payload — amount in words
# ══════════════════════════════════════════════════════════════════════════════

def test_under_100_of_zero_is_EMPTY_not_the_word_zero():
    """Corrected after running it: I assumed "Zero" and it returns "".

    That is correct, and load-bearing. `_under_100` is only ever called on a
    REMAINDER — `_int_words` special-cases a whole zero itself and otherwise only
    calls this when there is something left to say. If it returned "Zero" here,
    1,000 would render as "One Thousand Zero". The empty string is how the
    function says "nothing to add"."""
    assert PP._under_100(0) == ""
    assert PP._int_words(0) == "Zero", "the whole-zero case is handled one level up"


def test_under_100_covers_the_whole_range():
    assert PP._under_100(7) == "Seven"
    assert PP._under_100(13) == "Thirteen"
    assert PP._under_100(19) == "Nineteen"
    assert PP._under_100(20) == "Twenty"
    assert PP._under_100(21) == "Twenty One"
    assert PP._under_100(99) == "Ninety Nine"


def test_under_100_has_no_trailing_space_on_exact_tens():
    """A trailing space would show up in the middle of the printed words on
    every bill ending in a round ten."""
    for n in (20, 30, 40, 50, 60, 70, 80, 90):
        assert PP._under_100(n) == PP._under_100(n).strip()


def test_int_words_uses_indian_numbering():
    """Lakh and Crore, not million/billion. A bill in the wrong numbering system
    reads as a different amount to an Indian customer."""
    assert PP._int_words(0) == "Zero"
    assert PP._int_words(100) == "One Hundred"
    assert PP._int_words(1_000) == "One Thousand"
    assert PP._int_words(100_000) == "One Lakh"
    assert PP._int_words(10_000_000) == "One Crore"
    assert "Lakh" in PP._int_words(250_000)
    assert "Crore" in PP._int_words(12_345_678)
    assert "Million" not in PP._int_words(1_000_000)


def test_int_words_inserts_and_before_the_final_remainder_only():
    """The "and" attaches to the sub-hundred remainder, not to any group
    boundary — and only when something precedes it."""
    assert PP._int_words(1_005) == "One Thousand and Five"
    assert PP._int_words(1_180) == "One Thousand One Hundred and Eighty"
    assert PP._int_words(5) == "Five", "no leading 'and' when there is no prefix"
    assert PP._int_words(1_000) == "One Thousand", "no dangling 'and' on a round figure"
    assert PP._int_words(1_100) == "One Thousand One Hundred"


def test_int_words_is_composable_across_every_group():
    got = PP._int_words(1_23_45_678)     # 1 crore 23 lakh 45 thousand 678
    for token in ("Crore", "Lakh", "Thousand", "Hundred"):
        assert token in got, f"{token} missing from {got!r}"


def test_amount_in_words_renders_paise_separately():
    """Corrected after running it. I expected the "and" after "Thousand"; it
    actually falls before the FINAL group, because `Hundred` is one of the
    divisors too: 1180 -> "One Thousand" + "One Hundred" + remainder 80 ->
    "and Eighty". That is the correct Indian convention, and it is now pinned
    from observed behaviour rather than from my expectation."""
    assert PP.amount_in_words(1180.50) == \
        "One Thousand One Hundred and Eighty Rupees and Fifty Paise Only"
    assert PP.amount_in_words(100.0) == "One Hundred Rupees Only", \
        "no paise clause when there are no paise"


def test_amount_in_words_rounds_to_paise_before_wording():
    """The numeral on the bill comes from the same rounded value, so the words
    and the figure must agree. If they disagree the bill contradicts itself."""
    assert PP.amount_in_words(99.999) == PP.amount_in_words(100.0)
    assert PP.amount_in_words(0.005) == "Zero Rupees and One Paise Only"


def test_amount_in_words_of_none_is_zero_rupees_not_blank():
    """Documented in review §31: `_r2(None)` is 0.0 throughout this codebase, so
    this returns "Zero Rupees Only" rather than "". Defensible — the figure
    derives from the same value — but pinned because it is an assertion about the
    bill rather than a blank."""
    assert PP.amount_in_words(None) == "Zero Rupees Only"
    assert PP.amount_in_words(0) == "Zero Rupees Only"


# ══════════════════════════════════════════════════════════════════════════════
# print_payload — line and tax rendering
# ══════════════════════════════════════════════════════════════════════════════

def _li(**kw):
    base = dict(product_name="Soap", description=None, hsn_sac="3401",
                batch_no=None, expiry_date=None, mrp=None, serial_no=None,
                quantity=2, unit="Nos", unit_price=100.0, discount=0.0,
                taxable_value=200.0, cgst_rate=9.0, sgst_rate=9.0, igst_rate=0.0,
                cgst_amount=18.0, sgst_amount=18.0, igst_amount=0.0,
                cess_amount=0.0, line_total=236.0, attributes=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_line_out_sums_the_gst_rate_across_components():
    """The printed "GST %" column is cgst+sgst for intra-state and igst for
    inter-state. Showing 9% where 18% applies understates the tax on the bill."""
    out = PP._line_out(1, _li())
    assert out["gst_rate"] == 18.0
    inter = PP._line_out(1, _li(cgst_rate=0, sgst_rate=0, igst_rate=18.0))
    assert inter["gst_rate"] == 18.0


def test_line_out_never_recomputes_money():
    """Module contract: "All money figures here come from values the billing
    command already persisted; this module NEVER recomputes tax." So a line whose
    stored total disagrees with rate x qty must print the STORED value —
    recomputing would hide the real defect and print a number the books do not
    have."""
    out = PP._line_out(1, _li(line_total=999.99, taxable_value=1.0))
    assert out["line_total"] == 999.99
    assert out["taxable_value"] == 1.0


def test_line_out_defaults_a_missing_name_and_unit():
    out = PP._line_out(3, _li(product_name=None, unit=None))
    assert out["name"] == "Item"
    assert out["unit"] == "Nos"
    assert out["sno"] == 3


def test_line_out_rounds_every_money_field_to_paise():
    out = PP._line_out(1, _li(unit_price=1 / 3, discount=2 / 3,
                              taxable_value=1 / 7, cgst_amount=1 / 9,
                              line_total=10 / 3))
    for k in ("rate", "discount", "taxable_value", "cgst", "line_total"):
        assert out[k] == round(out[k], 2), k


def test_line_out_parses_json_attributes_and_survives_garbage():
    assert PP._line_out(1, _li(attributes='{"colour":"red"}'))["attributes"] == \
        {"colour": "red"}
    assert PP._line_out(1, _li(attributes="{not json"))["attributes"] is None
    assert PP._line_out(1, _li(attributes={"a": 1}))["attributes"] == {"a": 1}


def test_tax_summary_groups_by_hsn_and_rate():
    """The HSN annexure is what a GST officer reads. Grouping by HSN alone would
    merge two rates into one line and misstate the tax per slab."""
    lines = [
        PP._line_out(1, _li(hsn_sac="3401", taxable_value=100.0,
                            cgst_amount=9.0, sgst_amount=9.0)),
        PP._line_out(2, _li(hsn_sac="3401", taxable_value=200.0,
                            cgst_amount=18.0, sgst_amount=18.0)),
        PP._line_out(3, _li(hsn_sac="3401", cgst_rate=2.5, sgst_rate=2.5,
                            taxable_value=50.0, cgst_amount=1.25, sgst_amount=1.25)),
    ]
    summary = PP._tax_summary(lines)
    assert len(summary) == 2, "two different rates on one HSN must stay separate"
    by_rate = {g["rate"]: g for g in summary}
    assert by_rate[18.0]["taxable"] == 300.0
    assert by_rate[18.0]["cgst"] == 27.0
    assert by_rate[5.0]["taxable"] == 50.0


def test_tax_summary_labels_a_missing_hsn_rather_than_dropping_it():
    """A line with no HSN still carries tax. Dropping it would make the annexure
    foot to less than the invoice."""
    summary = PP._tax_summary([PP._line_out(1, _li(hsn_sac=None))])
    assert summary[0]["hsn"] == "—"
    assert summary[0]["taxable"] == 200.0


def test_tax_summary_totals_match_the_lines_they_summarise():
    """The annexure must foot to the invoice. This is the property that makes it
    a summary rather than a second opinion."""
    lines = [PP._line_out(i, _li(hsn_sac=h, taxable_value=v,
                                 cgst_amount=v * 0.09, sgst_amount=v * 0.09))
             for i, (h, v) in enumerate([("1001", 100.0), ("1002", 250.0),
                                         ("1001", 75.5)], start=1)]
    summary = PP._tax_summary(lines)
    assert round(sum(g["taxable"] for g in summary), 2) == \
        round(sum(l["taxable_value"] for l in lines), 2)
    assert round(sum(g["cgst"] for g in summary), 2) == \
        round(sum(l["cgst"] for l in lines), 2)


def test_tax_summary_is_deterministically_ordered():
    """Two builds of one invoice must produce byte-identical output — the
    payload hash depends on it."""
    lines = [PP._line_out(1, _li(hsn_sac="9999")),
             PP._line_out(2, _li(hsn_sac="1111")),
             PP._line_out(3, _li(hsn_sac="5555"))]
    first = PP._tax_summary(lines)
    assert first == PP._tax_summary(list(reversed(lines)))
    assert [g["hsn"] for g in first] == ["1111", "5555", "9999"]


def test_tax_summary_of_no_lines_is_empty_not_an_error():
    assert PP._tax_summary([]) == []


# ══════════════════════════════════════════════════════════════════════════════
# print_payload — the payload hash (tamper-evidence of the printed bill)
# ══════════════════════════════════════════════════════════════════════════════

def test_payload_hash_is_stable_across_builds():
    """The e2e "switching templates never mutates the bill" check rests on this."""
    totals = {"subtotal": 200.0, "total": 236.0, "amount_in_words": "irrelevant"}
    lines = [PP._line_out(1, _li())]
    assert PP._payload_hash("INV-1", totals, lines) == \
        PP._payload_hash("INV-1", totals, lines)


def test_payload_hash_ignores_float_noise():
    """Same trick as the journal chain hash. A hash that breaks on its own
    arithmetic proves nothing."""
    lines = [PP._line_out(1, _li())]
    a = PP._payload_hash("INV-1", {"total": 236.0}, lines)
    b = PP._payload_hash("INV-1", {"total": 236.00000000000003}, lines)
    assert a == b


def test_payload_hash_ignores_the_words_but_not_the_figures():
    """`amount_in_words` is derived from the total, so hashing it would be
    double-counting; the total itself must be covered."""
    lines = [PP._line_out(1, _li())]
    base = PP._payload_hash("INV-1", {"total": 236.0, "amount_in_words": "A"}, lines)
    assert base == PP._payload_hash("INV-1", {"total": 236.0, "amount_in_words": "B"}, lines)
    assert base != PP._payload_hash("INV-1", {"total": 236.01, "amount_in_words": "A"}, lines)


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda l: l.update({"name": "Different"}), id="item-name"),
    pytest.param(lambda l: l.update({"qty": 3.0}), id="quantity"),
    pytest.param(lambda l: l.update({"rate": 101.0}), id="rate"),
    pytest.param(lambda l: l.update({"line_total": 237.0}), id="line-total"),
])
def test_payload_hash_changes_when_any_money_bearing_field_changes(mutate):
    """Every field the hash claims to cover is asserted to move it. An
    uncovered field is a field that can be altered without evidence."""
    lines = [PP._line_out(1, _li())]
    before = PP._payload_hash("INV-1", {"total": 236.0}, lines)
    mutate(lines[0])
    assert PP._payload_hash("INV-1", {"total": 236.0}, lines) != before


def test_payload_hash_covers_the_invoice_number_and_line_order():
    lines = [PP._line_out(1, _li(product_name="A")),
             PP._line_out(2, _li(product_name="B"))]
    base = PP._payload_hash("INV-1", {"total": 1.0}, lines)
    assert PP._payload_hash("INV-2", {"total": 1.0}, lines) != base
    assert PP._payload_hash("INV-1", {"total": 1.0}, list(reversed(lines))) != base


# ══════════════════════════════════════════════════════════════════════════════
# print_payload — title, header layout, dates
# ══════════════════════════════════════════════════════════════════════════════

def _inv(**kw):
    base = dict(invoice_title=None, invoice_type=None, status=None,
                total_amount=236.0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_stored_title_always_wins():
    assert PP._resolve_title(_inv(invoice_title="Custom Bill"), "27AAA", {}) == "Custom Bill"


def test_title_reflects_gst_registration_and_scheme():
    """The wrong heading on a bill is a compliance problem, not cosmetics: an
    unregistered seller may not issue a "Tax Invoice", and a composition dealer
    must issue a "Bill of Supply"."""
    assert PP._resolve_title(_inv(), "27AAAAA0000A1Z5", {}) == "Tax Invoice"
    assert PP._resolve_title(_inv(), None, {}) == "Retail Invoice"
    assert PP._resolve_title(_inv(), "27AAAAA0000A1Z5",
                             {"composite_scheme": True}) == "Bill of Supply"


def test_title_recognises_non_invoice_documents():
    assert PP._resolve_title(_inv(invoice_type="estimate"), "27A", {}) == "Estimate"
    assert PP._resolve_title(_inv(status="estimate"), "27A", {}) == "Estimate"
    assert PP._resolve_title(_inv(invoice_type="proforma"), "27A", {}) == "Proforma Invoice"
    assert PP._resolve_title(_inv(invoice_type="credit_note"), "27A", {}) == "Credit Note"


def test_a_negative_total_is_a_credit_note_even_without_the_type():
    """Defence in depth: a refund printed as a "Tax Invoice" with a negative
    total is a document that should not exist."""
    assert PP._resolve_title(_inv(total_amount=-100.0), "27A", {}) == "Credit Note"


def test_header_layout_falls_back_to_the_default():
    default = PP._header_layout({})
    assert [d["key"] for d in default] == [
        "logo", "company_name", "company_address", "company_contact", "gstin"]
    assert PP._header_layout({"header_layout": "not-a-list"}) == default
    assert PP._header_layout({"header_layout": []}) == default


def test_header_layout_keeps_every_default_key_even_if_saved_omits_it():
    """A saved layout missing `gstin` must not silently drop the GSTIN off the
    bill — that is a mandatory field for a registered seller."""
    out = PP._header_layout({"header_layout": [{"key": "company_name", "align": "left"}]})
    keys = [d["key"] for d in out]
    assert keys[0] == "company_name" and out[0]["align"] == "left"
    for d in PP._header_layout({}):
        assert d["key"] in keys, f"{d['key']} was dropped"


def test_header_layout_rejects_unknown_keys_and_bad_alignments():
    out = PP._header_layout({"header_layout": [
        {"key": "evil_injection", "align": "center"},
        {"key": "logo", "align": "diagonal"},
    ]})
    assert all(d["key"] != "evil_injection" for d in out)
    assert all(d["align"] in ("left", "center", "right") for d in out)


def test_local_time_str_renders_in_the_business_timezone():
    """Timestamps are stored as naive UTC. Printing them raw put UTC on invoices
    — 5h30 behind the merchant's wall clock."""
    got = PP._local_time_str(datetime(2026, 7, 26, 19, 51, 0))   # 19:51 UTC
    assert got == "1:21 AM", f"expected IST conversion, got {got!r}"
    assert PP._local_time_str(None) is None


def test_local_time_str_has_no_leading_zero():
    assert not PP._local_time_str(datetime(2026, 7, 26, 3, 30, 0)).startswith("0")


# ══════════════════════════════════════════════════════════════════════════════
# einvoice — string, date and address normalisation
# ══════════════════════════════════════════════════════════════════════════════

def test_s_is_none_safe_and_strips():
    assert EI._s(None) == ""
    assert EI._s("  x  ") == "x"
    assert EI._s(42) == "42"
    assert EI._s(0) == "0", "0 must not become empty — it is a value, not a blank"


def test_fmt_date_converts_iso_to_the_portal_format():
    assert EI._fmt_date("2026-07-26") == "26/07/2026"
    assert EI._fmt_date("2026-07-26T14:30:00") == "26/07/2026"
    assert EI._fmt_date("26/07/2026") == "26/07/2026"


def test_fmt_date_passes_an_unknown_format_through_rather_than_crashing():
    """A rejected e-invoice is recoverable; a 500 while printing is not."""
    assert EI._fmt_date("July 26 2026") == "July 26 2026"
    assert EI._fmt_date(None) == ""
    assert EI._fmt_date("") == ""


def test_state_code_prefers_the_gstin():
    """The GSTIN's first two digits are authoritative. A mismatched `state_code`
    field would otherwise decide place-of-supply and flip CGST/SGST to IGST."""
    assert EI._state_code("99", gstin="27AAAAA0000A1Z5") == "27"
    assert EI._state_code("7") == "07", "single digit must be zero-padded"
    assert EI._state_code(None) == ""
    assert EI._state_code("Maharashtra") == ""


def test_split_addr_extracts_the_pin_and_locality():
    a1, a2, loc, pin = EI._split_addr("12 MG Road, Shivajinagar, Pune 411005")
    assert pin == "411005"
    assert a1 == "12 MG Road"
    assert loc == "Pune"
    assert a2 == "Shivajinagar"


def test_split_addr_handles_a_single_chunk_and_a_blank():
    a1, a2, loc, pin = EI._split_addr("Shop 4")
    assert (a1, a2, loc, pin) == ("Shop 4", "", "Shop 4", "")
    assert EI._split_addr(None) == ("", "", "", "")
    assert EI._split_addr("") == ("", "", "", "")


def test_split_addr_removes_the_pin_from_the_text_it_returns():
    """Leaving the pin inside the locality prints it twice on the portal record."""
    _, _, loc, pin = EI._split_addr("A Road, Bengaluru 560001")
    assert pin == "560001"
    assert "560001" not in loc


def test_split_addr_never_raises_on_odd_input():
    for weird in (",,,", "   ", "123456", "a, , b", "12345678901"):
        assert len(EI._split_addr(weird)) == 4


def test_item_rows_foot_to_the_invoice_totals():
    """The load-bearing property: the portal validates that the per-item
    assessable values and taxes sum to the document totals. A mismatch is a
    rejected filing."""
    inv = SimpleNamespace(line_items=[
        _li(taxable_value=200.0, cgst_amount=18.0, sgst_amount=18.0, line_total=236.0),
        _li(taxable_value=100.0, cgst_amount=9.0, sgst_amount=9.0, line_total=118.0),
    ])
    rows, tot = EI._item_rows(inv, intra=True)
    assert len(rows) == 2
    assert tot["ass"] == 300.0
    assert tot["cgst"] == 27.0
    assert tot["sgst"] == 27.0
    assert round(tot["inv"], 2) == 354.0
    assert round(sum(r["AssAmt"] for r in rows), 2) == tot["ass"]


def test_item_rows_pick_the_right_rate_for_intra_vs_inter_state():
    """Intra-state reports cgst+sgst; inter-state reports igst. Reporting the
    wrong one on an inter-state supply misstates the tax the buyer can claim."""
    intra_rows, _ = EI._item_rows(
        SimpleNamespace(line_items=[_li(cgst_rate=9, sgst_rate=9, igst_rate=0)]),
        intra=True)
    assert intra_rows[0]["GstRt"] == 18.0
    inter_rows, _ = EI._item_rows(
        SimpleNamespace(line_items=[_li(cgst_rate=0, sgst_rate=0, igst_rate=18,
                                        cgst_amount=0, sgst_amount=0,
                                        igst_amount=36.0)]),
        intra=False)
    assert inter_rows[0]["GstRt"] == 18.0
    assert inter_rows[0]["IgstAmt"] == 36.0


def test_item_rows_number_sequentially_from_one():
    inv = SimpleNamespace(line_items=[_li(), _li(), _li()])
    rows, _ = EI._item_rows(inv, intra=True)
    assert [r["SlNo"] for r in rows] == ["1", "2", "3"]


def test_item_rows_default_the_mandatory_fields():
    """`PrdDesc` and `Unit` are mandatory in INV-01. An empty one is a rejection."""
    rows, _ = EI._item_rows(
        SimpleNamespace(line_items=[_li(product_name=None, unit=None)]), intra=True)
    assert rows[0]["PrdDesc"] == "Item"
    assert rows[0]["Unit"] == "NOS"
    assert rows[0]["IsServc"] == "N"


def test_item_rows_uppercase_and_truncate_the_unit():
    rows, _ = EI._item_rows(
        SimpleNamespace(line_items=[_li(unit="kilogramsxx")]), intra=True)
    assert rows[0]["Unit"] == "KILOGRAM", "the portal caps Unit at 8 characters"


def test_item_rows_of_an_empty_invoice_are_empty_and_footed_to_zero():
    rows, tot = EI._item_rows(SimpleNamespace(line_items=[]), intra=True)
    assert rows == []
    assert all(v == 0.0 for v in tot.values())


# ══════════════════════════════════════════════════════════════════════════════
# einvoice — the buyer block
# ══════════════════════════════════════════════════════════════════════════════

def test_buyer_block_for_a_walk_in_is_marked_unregistered():
    """"URP" (unregistered person) with POS 96 is how a counter sale to a
    walk-in is declared. Sending a blank GSTIN instead is a rejection."""
    b = EI._buyer_block(None, None, "27")
    assert b["Gstin"] == "URP"
    assert b["Pos"] == "27"
    assert b["Addr1"] == "NA" and b["Loc"] == "NA"


def test_buyer_block_falls_back_to_pos_96_with_no_place_of_supply():
    assert EI._buyer_block(None, None, None)["Pos"] == "96"


def test_buyer_block_uses_the_buyers_details_when_present():
    buyer = SimpleNamespace(name="Acme Traders", address="5 Park St, Kolkata 700016",
                            state_code="19", phone="9876543210", email="a@b.com")
    b = EI._buyer_block(buyer, "19AAAAA0000A1Z5", None)
    assert b["Gstin"] == "19AAAAA0000A1Z5"
    assert b["LglNm"] == "Acme Traders"
    assert b["Pin"] == "700016"
    assert b["Loc"] == "Kolkata"
    assert b["Stcd"] == "19"
    assert b["Ph"] == "9876543210"


def test_buyer_block_never_emits_an_empty_mandatory_field():
    """A buyer row with nothing filled in must still produce a submittable
    block — the fallbacks are the difference between a filed invoice and a
    rejected one."""
    buyer = SimpleNamespace(name="", address="", state_code=None,
                            phone=None, email=None)
    b = EI._buyer_block(buyer, None, None)
    assert b["Gstin"] == "URP"
    assert b["LglNm"] == "Buyer"
    assert b["Addr1"] == "NA"
    assert b["Loc"] == "NA"
    assert b["Pos"] == "96"


def test_buyer_block_prefers_the_gstin_state_over_the_stored_state_code():
    """Same rule as `_state_code`, asserted through the block because this is
    where it decides the place of supply on a real filing."""
    buyer = SimpleNamespace(name="X", address="A, B 560001", state_code="27",
                            phone=None, email=None)
    assert EI._buyer_block(buyer, "29AAAAA0000A1Z5", None)["Stcd"] == "29"
