"""
tests/test_money_pure_functions.py
==================================
Unit coverage for the DETERMINISTIC money functions — the ones where a bug is
silently wrong money rather than a crash.

WHY THIS FILE EXISTS
--------------------
A coverage sweep of the 229 functions across the money modules found that only
~33% were referenced by any test, and the gap included the five functions in
``core/accounting/posting.py`` that decide **which account every rupee lands
in**:

    build_sale_lines · build_credit_note_lines · build_purchase_lines
    build_debit_note_lines · build_expense_lines

They are pure, deterministic and trivially testable, and nothing tested them
directly. A sign error or a swapped account in any one of them misstates the
trial balance, the P&L and the party ledger simultaneously — while the POS keeps
looking perfectly normal, which is exactly the failure mode of M-2 and M-7.

WHAT IS COVERED HERE
--------------------
Only functions that need no database. Everything is exact-value or property
based, so a failure names the defect rather than hinting at it.

  posting      _r2 · _gst_total · _chain_hash · all five line builders
  billing      _round2 · _state_code · _is_intra_state · _line_rates
               _pack_attributes · _compute_line
  apply_hooks  parse_dt · row_to_dict · payloads_differ · is_financial_overwrite
  repost       _is_advance_application
  shifts       _round2 · _norm_mode
  print_payload  amount_in_words (customer-facing on every printed bill)

THE LOAD-BEARING ASSERTION is `test_every_builder_foots_for_every_shape`: a
journal entry that does not balance is not bookkeeping, whatever else is true.
"""
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_bizassist.db")
os.environ.setdefault("GROQ_API_KEY", "mock_groq_api_key")

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_path)

import pytest
from core.accounting import posting
from core.accounting import repost
from core.billing import commands as billing
from core.billing import print_payload as PP
from core.shifts import service as shifts
from core.sync import apply_hooks

R2 = lambda x: round(float(x or 0.0), 2)


def _doc(total, *, cgst=0.0, sgst=0.0, igst=0.0, cess=0.0, paid=0.0,
         cash_discount=0.0, status="Pending", category=None, amount=None):
    """A stand-in for an Invoice / PurchaseInvoice / Expense header."""
    return SimpleNamespace(
        total_amount=total, cgst_total=cgst, sgst_total=sgst, igst_total=igst,
        cess_total=cess, paid_amount=paid, cash_discount=cash_discount,
        status=status, category=category, amount=(total if amount is None else amount),
    )


def _foots(lines):
    dr = R2(sum(d for _, d, _ in lines))
    cr = R2(sum(c for _, _, c in lines))
    return abs(dr - cr) < 0.01


def _acct(lines, name):
    """Debit-positive net on one account within a line set."""
    return R2(sum(d - c for a, d, c in lines if a == name))


# ═══════════════════════════════════════════════════════════════════════════
# posting — rounding and tax totals
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,want", [
    (None, 0.0), (0, 0.0), (1, 1.0), (1.005, 1.0), (1.006, 1.01),
    (2.675, 2.67), (-1.234, -1.23), ("3.456", 3.46), (1e-9, 0.0),
])
def test_posting_r2(raw, want):
    assert posting._r2(raw) == want


def test_gst_total_sums_every_head():
    assert posting._gst_total(_doc(1000, cgst=9.0, sgst=9.0, igst=0.0, cess=2.5)) == 20.5
    assert posting._gst_total(_doc(1000)) == 0.0


def test_gst_total_tolerates_missing_heads():
    d = SimpleNamespace(cgst_total=None, sgst_total=5.0, igst_total=None, cess_total=None)
    assert posting._gst_total(d) == 5.0


# ═══════════════════════════════════════════════════════════════════════════
# posting — the hash chain
# ═══════════════════════════════════════════════════════════════════════════

def _hash(**over):
    base = dict(business_id=1, entry_date="2026-07-01", source_type="sale",
                source_id=7, ref_no="INV-0001", narration="Sale",
                clean=[("Cash & Bank", 118.0, 0.0), ("Sales", 0.0, 100.0),
                       ("GST Payable", 0.0, 18.0)],
                prev_hash="GENESIS")
    base.update(over)
    return posting._chain_hash(**base)


def test_chain_hash_is_deterministic():
    assert _hash() == _hash()


@pytest.mark.parametrize("field,value", [
    ("business_id", 2), ("entry_date", "2026-07-02"), ("source_type", "credit_note"),
    ("source_id", 8), ("ref_no", "INV-0002"), ("narration", "Something else"),
    ("prev_hash", "abc123"),
])
def test_chain_hash_changes_when_any_field_changes(field, value):
    """Tamper-evidence: every hashed input must actually affect the hash."""
    assert _hash(**{field: value}) != _hash()


def test_chain_hash_changes_when_an_amount_changes():
    """The whole point — editing a figure must break the chain."""
    tampered = [("Cash & Bank", 118.0, 0.0), ("Sales", 0.0, 100.01),
                ("GST Payable", 0.0, 18.0)]
    assert _hash(clean=tampered) != _hash()


def test_chain_hash_is_stable_across_float_noise():
    """Amounts are formatted to fixed 2dp before hashing, so representational
    noise must not shift the hash — otherwise the chain would 'break' on its own."""
    noisy = [("Cash & Bank", 118.00000000000001, 0.0), ("Sales", 0.0, 100.0),
             ("GST Payable", 0.0, 18.0)]
    assert _hash(clean=noisy) == _hash()


def test_chain_hash_is_order_sensitive():
    reordered = [("Sales", 0.0, 100.0), ("Cash & Bank", 118.0, 0.0),
                 ("GST Payable", 0.0, 18.0)]
    assert _hash(clean=reordered) != _hash()


# ═══════════════════════════════════════════════════════════════════════════
# posting — THE LINE BUILDERS (which account every rupee lands in)
# ═══════════════════════════════════════════════════════════════════════════

def test_build_sale_lines_unpaid_goes_to_receivables():
    lines = posting.build_sale_lines(_doc(118.0, cgst=9.0, sgst=9.0, paid=0.0))
    assert _foots(lines)
    assert _acct(lines, posting.ACC_AR) == 118.0
    assert _acct(lines, posting.ACC_CASH) == 0.0
    assert _acct(lines, posting.ACC_SALES) == -100.0      # credit
    assert _acct(lines, posting.ACC_GST_OUT) == -18.0


def test_build_sale_lines_paid_goes_to_cash():
    lines = posting.build_sale_lines(_doc(118.0, cgst=9.0, sgst=9.0, paid=118.0))
    assert _foots(lines)
    assert _acct(lines, posting.ACC_CASH) == 118.0
    assert _acct(lines, posting.ACC_AR) == 0.0


def test_build_sale_lines_splits_a_part_payment():
    lines = posting.build_sale_lines(_doc(118.0, cgst=9.0, sgst=9.0, paid=50.0))
    assert _foots(lines)
    assert _acct(lines, posting.ACC_CASH) == 50.0
    assert _acct(lines, posting.ACC_AR) == 68.0


def test_build_sale_lines_never_books_negative_receivables_on_overpayment():
    """Paid beyond the total must not produce a negative AR line — the excess is
    an advance, handled elsewhere, not a negative debt here."""
    lines = posting.build_sale_lines(_doc(118.0, cgst=9.0, sgst=9.0, paid=500.0))
    assert _foots(lines)
    assert _acct(lines, posting.ACC_AR) == 0.0
    assert _acct(lines, posting.ACC_CASH) == 118.0


def test_cash_discount_is_an_expense_and_revenue_stays_gross():
    """R4: a post-tax cash discount reduces what is collected, NOT Sales or GST.
    Booking it against Sales would understate revenue and misstate GST."""
    lines = posting.build_sale_lines(
        _doc(108.0, cgst=9.0, sgst=9.0, paid=108.0, cash_discount=10.0))
    assert _foots(lines)
    assert _acct(lines, posting.ACC_DISCOUNT) == 10.0
    assert _acct(lines, posting.ACC_SALES) == -100.0      # full revenue
    assert _acct(lines, posting.ACC_GST_OUT) == -18.0     # full tax
    assert _acct(lines, posting.ACC_CASH) == 108.0


def test_zero_cash_discount_produces_no_discount_line():
    """cash_discount == 0 must be byte-identical to the original two-sided entry."""
    lines = posting.build_sale_lines(_doc(118.0, cgst=9.0, sgst=9.0, paid=118.0))
    assert all(a != posting.ACC_DISCOUNT or (d == 0 and c == 0) for a, d, c in lines)


def test_build_credit_note_lines_reverse_a_sale():
    """A return must mirror the sale exactly, or returns silently leak revenue."""
    sale = posting.build_sale_lines(_doc(118.0, cgst=9.0, sgst=9.0, paid=0.0))
    note = posting.build_credit_note_lines(_doc(118.0, cgst=9.0, sgst=9.0))
    assert _foots(note)
    assert _acct(note, posting.ACC_SALES) == -_acct(sale, posting.ACC_SALES)
    assert _acct(note, posting.ACC_GST_OUT) == -_acct(sale, posting.ACC_GST_OUT)
    assert _acct(note, posting.ACC_AR) == -118.0


def test_build_purchase_lines_unpaid_goes_to_payables():
    lines = posting.build_purchase_lines(_doc(118.0, cgst=9.0, sgst=9.0, status="Pending"))
    assert _foots(lines)
    assert _acct(lines, posting.ACC_PURCHASES) == 100.0
    assert _acct(lines, posting.ACC_GST_IN) == 18.0       # input credit is a DEBIT
    assert _acct(lines, posting.ACC_AP) == -118.0
    assert _acct(lines, posting.ACC_CASH) == 0.0


def test_build_purchase_lines_paid_settles_in_cash():
    lines = posting.build_purchase_lines(_doc(118.0, cgst=9.0, sgst=9.0, status="Paid"))
    assert _foots(lines)
    assert _acct(lines, posting.ACC_CASH) == -118.0
    assert _acct(lines, posting.ACC_AP) == 0.0


def test_build_debit_note_lines_reverse_a_purchase():
    pur = posting.build_purchase_lines(_doc(118.0, cgst=9.0, sgst=9.0, status="Pending"))
    note = posting.build_debit_note_lines(_doc(118.0, cgst=9.0, sgst=9.0, status="Pending"))
    assert _foots(note)
    assert _acct(note, posting.ACC_PURCHASES) == -_acct(pur, posting.ACC_PURCHASES)
    assert _acct(note, posting.ACC_GST_IN) == -_acct(pur, posting.ACC_GST_IN)


def test_build_expense_lines_uses_the_category_account():
    lines = posting.build_expense_lines(SimpleNamespace(amount=500.0, category="Rent"))
    assert _foots(lines)
    assert _acct(lines, "Rent Expense") == 500.0
    assert _acct(lines, posting.ACC_CASH) == -500.0


def test_build_expense_lines_falls_back_when_uncategorised():
    lines = posting.build_expense_lines(SimpleNamespace(amount=500.0, category=None))
    assert _foots(lines)
    assert _acct(lines, "Operating Expenses") == 500.0


# ── THE load-bearing property ──────────────────────────────────────────────

@pytest.mark.parametrize("total", [0.0, 0.01, 1.0, 118.0, 999.99, 123456.78])
@pytest.mark.parametrize("gst_pair", [(0.0, 0.0), (9.0, 9.0), (0.5, 0.5), (2.5, 2.5)])
@pytest.mark.parametrize("paid_frac", [0.0, 0.5, 1.0])
def test_every_builder_foots_for_every_shape(total, gst_pair, paid_frac):
    """Σ debits == Σ credits, for every builder, across the value space.

    An entry that does not foot is not bookkeeping. `post_entry` refuses to write
    one, so a builder that can produce an unbalanced set does not corrupt the
    ledger — it silently REFUSES TO RECORD THE SALE, which is worse: the money
    moves and nothing is booked.
    """
    cgst, sgst = gst_pair
    doc = _doc(total, cgst=cgst, sgst=sgst, paid=R2(total * paid_frac))
    assert _foots(posting.build_sale_lines(doc)), "sale"
    assert _foots(posting.build_credit_note_lines(doc)), "credit note"
    assert _foots(posting.build_purchase_lines(doc)), "purchase"
    assert _foots(posting.build_debit_note_lines(doc)), "debit note"
    assert _foots(posting.build_expense_lines(
        SimpleNamespace(amount=total, category="Misc"))), "expense"


@pytest.mark.parametrize("cash_discount", [0.0, 0.01, 5.0, 50.0])
def test_sale_foots_with_any_cash_discount(cash_discount):
    doc = _doc(118.0, cgst=9.0, sgst=9.0, paid=118.0, cash_discount=cash_discount)
    assert _foots(posting.build_sale_lines(doc))


# ═══════════════════════════════════════════════════════════════════════════
# billing — GST resolution and line math
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,want", [
    (None, 0.0), (0, 0.0), (1.005, 1.01), (2.675, 2.68), (-1.234, -1.23),
])
def test_billing_round2_rounds_half_up(raw, want):
    """Billing uses +1e-9 half-up, unlike posting's banker's rounding. The
    difference is deliberate: a customer-facing total should never round a
    half-paisa AWAY from the printed figure."""
    assert billing._round2(raw) == want


@pytest.mark.parametrize("raw,want", [
    ("29", "29"), ("29-Karnataka", "29"), (" 07 Delhi", "07"),
    ("Karnataka", None), (None, None), ("", None),
    ("2", None),        # a single digit is not a GST state code
])
def test_state_code_extracts_the_gst_prefix(raw, want):
    assert billing._state_code(raw) == want


@pytest.mark.parametrize("biz,pos,intra", [
    ("29", "29", True), ("29", "29-Karnataka", True),
    ("29", "07", False), ("07", "29", False),
    (None, "29", True),        # unknown → assume local retail
    ("29", None, True),
    (None, None, True),
    ("Karnataka", "29", True), # unparseable → same conservative default
])
def test_intra_state_resolution(biz, pos, intra):
    """Get this wrong and the invoice charges CGST+SGST where IGST is due — a
    filing error on every affected bill."""
    assert billing._is_intra_state(biz, pos) is intra


def test_line_rates_prefer_the_line_override_then_the_product():
    product = SimpleNamespace(cgst_rate=9.0, sgst_rate=9.0, igst_rate=18.0)
    assert billing._line_rates({}, product) == (9.0, 9.0, 18.0, 0.0)
    assert billing._line_rates({"cgst_rate": 2.5, "sgst_rate": 2.5}, product)[:2] == (2.5, 2.5)
    assert billing._line_rates({}, None) == (0.0, 0.0, 0.0, 0.0)
    assert billing._line_rates({"cess_rate": 12.0}, None)[3] == 12.0


def test_line_rates_treat_an_explicit_zero_as_an_override():
    """0% is a real GST rate (exempt goods). It must not fall through to the
    product's rate, or exempt items get taxed."""
    product = SimpleNamespace(cgst_rate=9.0, sgst_rate=9.0, igst_rate=18.0)
    assert billing._line_rates({"cgst_rate": 0.0, "sgst_rate": 0.0}, product)[:2] == (0.0, 0.0)


@pytest.mark.parametrize("attrs,want", [
    (None, None), ({}, None), ("", None), ("null", None),
    ({"size": "L"}, '{"size": "L"}'),
    ({"size": "L", "colour": None, "fit": ""}, '{"size": "L"}'),
    ('{"size": "L"}', '{"size": "L"}'),
    ("not json", None),
])
def test_pack_attributes(attrs, want):
    assert billing._pack_attributes(attrs) == want


def test_compute_line_intra_state_splits_cgst_and_sgst():
    out = billing._compute_line(
        {"quantity": 2, "unit_price": 100.0}, None, intra=True, tax_inclusive=False)
    assert out["taxable_value"] == 200.0
    assert out["igst_amount"] == 0.0
    assert out["line_total"] == 200.0


def test_compute_line_inter_state_uses_igst_only():
    product = SimpleNamespace(cgst_rate=9.0, sgst_rate=9.0, igst_rate=18.0,
                              name="X", hsn_sac="1", unit="Nos", mrp=None)
    out = billing._compute_line(
        {"quantity": 1, "unit_price": 100.0}, product, intra=False, tax_inclusive=False)
    assert out["cgst_amount"] == 0.0 and out["sgst_amount"] == 0.0
    assert out["igst_amount"] == 18.0
    assert out["line_total"] == 118.0


def test_compute_line_tax_inclusive_back_calculates():
    """MRP billing: ₹118 inclusive of 18% must yield ₹100 taxable, not ₹118."""
    product = SimpleNamespace(cgst_rate=9.0, sgst_rate=9.0, igst_rate=18.0,
                              name="X", hsn_sac="1", unit="Nos", mrp=None)
    out = billing._compute_line(
        {"quantity": 1, "unit_price": 118.0}, product, intra=True, tax_inclusive=True)
    assert out["taxable_value"] == 100.0
    assert R2(out["cgst_amount"] + out["sgst_amount"]) == 18.0
    assert out["line_total"] == 118.0


def test_compute_line_absolute_discount_beats_percent():
    out = billing._compute_line(
        {"quantity": 1, "unit_price": 100.0, "discount": 10.0, "discount_pct": 50.0},
        None, intra=True, tax_inclusive=False)
    assert out["discount"] == 10.0
    assert out["taxable_value"] == 90.0


def test_compute_line_percent_discount_applies_when_no_absolute():
    out = billing._compute_line(
        {"quantity": 1, "unit_price": 100.0, "discount_pct": 10.0},
        None, intra=True, tax_inclusive=False)
    assert out["taxable_value"] == 90.0


def test_compute_line_discount_cannot_drive_the_line_negative():
    out = billing._compute_line(
        {"quantity": 1, "unit_price": 100.0, "discount": 500.0},
        None, intra=True, tax_inclusive=False)
    assert out["taxable_value"] == 0.0
    assert out["line_total"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# apply_hooks — sync predicates
# ═══════════════════════════════════════════════════════════════════════════

def test_parse_dt_handles_the_shapes_that_cross_the_wire():
    from datetime import datetime
    assert apply_hooks.parse_dt(None) is None
    assert apply_hooks.parse_dt("") is None
    now = datetime(2026, 7, 1, 12, 0, 0)
    assert apply_hooks.parse_dt(now) is now
    assert apply_hooks.parse_dt("2026-07-01T12:00:00") == now
    assert apply_hooks.parse_dt("2026-07-01T12:00:00Z").year == 2026   # Z → +00:00
    assert apply_hooks.parse_dt("not-a-date") is None
    assert apply_hooks.parse_dt("2026-13-45") is None


def test_row_to_dict_strips_sa_state_and_isoformats_datetimes():
    from datetime import datetime
    row = SimpleNamespace(id=1, name="x", created_at=datetime(2026, 7, 1))
    row._sa_instance_state = object()
    out = apply_hooks.row_to_dict(row)
    assert "_sa_instance_state" not in out
    assert out["created_at"] == "2026-07-01T00:00:00"


@pytest.mark.parametrize("incoming,existing,differs", [
    ({"total_amount": 100}, {"total_amount": 100}, False),
    ({"total_amount": 100}, {"total_amount": 200}, True),
    # cross-dialect: the same value arrives as a different Python type
    ({"total_amount": 100}, {"total_amount": "100"}, False),
    # bookkeeping columns always differ and must not count
    ({"updated_at": "a"}, {"updated_at": "b"}, False),
    ({"created_at": "a", "sync_status": "x", "id": 9}, {"created_at": "b", "sync_status": "y", "id": 8}, False),
    # a key the peer didn't send says nothing
    ({"total_amount": 100}, {"total_amount": 100, "status": "Paid"}, False),
    ({}, {"total_amount": 100}, False),
])
def test_payloads_differ(incoming, existing, differs):
    assert apply_hooks.payloads_differ(incoming, existing) is differs


def test_is_financial_overwrite_requires_every_condition():
    from datetime import datetime
    older, newer = datetime(2026, 7, 1), datetime(2026, 7, 2)
    row = SimpleNamespace(total_amount=100)
    inc = {"total_amount": 200}

    assert apply_hooks.is_financial_overwrite("invoices", inc, row, newer, older) is True
    # not a financial entity
    assert apply_hooks.is_financial_overwrite("products", inc, row, newer, older) is False
    # incoming is older → it loses LWW, nothing is overwritten
    assert apply_hooks.is_financial_overwrite("invoices", inc, row, older, newer) is False
    # identical timestamps prove nothing
    assert apply_hooks.is_financial_overwrite("invoices", inc, row, newer, newer) is False
    # an unknown timestamp proves nothing either
    assert apply_hooks.is_financial_overwrite("invoices", inc, row, None, older) is False
    assert apply_hooks.is_financial_overwrite("invoices", inc, row, newer, None) is False
    # no existing row → this is an insert, not an overwrite
    assert apply_hooks.is_financial_overwrite("invoices", inc, None, newer, older) is False
    # newer but IDENTICAL → normal propagation, must not spam the review list
    assert apply_hooks.is_financial_overwrite(
        "invoices", {"total_amount": 100}, row, newer, older) is False


def test_financial_entities_covers_every_money_table():
    for t in ("invoices", "invoice_line_items", "payments", "invoice_payments",
              "purchase_invoices", "expenses", "stock_ledger", "b2b_ledgers"):
        assert t in apply_hooks.FINANCIAL_ENTITIES


# ═══════════════════════════════════════════════════════════════════════════
# repost — advance vs cash routing
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("key,note,want", [
    ("advance-credit::12", None, True),
    (None, "Applied advance credit", True),
    (None, "  APPLIED ADVANCE CREDIT  ", True),
    ("receipt::12", None, False),
    (None, "Initial payment for invoice INV-0001", False),
    (None, None, False),
])
def test_is_advance_application(key, note, want):
    """Misrouting this double-counts cash: an advance was already booked when it
    came in, so applying it must draw down the liability, not book cash again."""
    pay = SimpleNamespace(idempotency_key=key, note=note)
    assert repost._is_advance_application(pay) is want


def test_advance_detection_ignores_the_ambiguous_payment_mode():
    """payment_mode 'Credit' means store credit here but users also pick it for
    card payments — it must not drive the account choice."""
    pay = SimpleNamespace(idempotency_key=None, note=None, payment_mode="Credit")
    assert repost._is_advance_application(pay) is False


# ═══════════════════════════════════════════════════════════════════════════
# shifts — cash tally normalisation
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,want", [
    (None, 0.0), (0, 0.0), (1.005, 1.01), (2.675, 2.68), (-1.234, -1.23),
])
def test_shifts_round2(raw, want):
    assert shifts._round2(raw) == want


@pytest.mark.parametrize("raw,bucket", [
    ("cash", "cash"), ("Cash", "cash"), ("  CASH  ", "cash"), (None, "cash"), ("", "cash"),
    ("upi", "upi"), ("GPay", "upi"), ("phonepe", "upi"), ("paytm", "upi"), ("QR", "upi"),
    ("card", "card"), ("Credit Card", "card"), ("debit card", "card"),
    ("cheque", "other"), ("netbanking", "other"), ("bitcoin", "other"),
])
def test_norm_mode_buckets_free_text(raw, bucket):
    """The drawer tally is split by bucket — a mode landing in the wrong one
    makes the counter's cash count disagree with the till."""
    assert shifts._norm_mode(raw) == bucket


def test_norm_mode_defaults_unknown_to_other_not_cash():
    """An unrecognised mode must NEVER default into the cash bucket, or the
    expected drawer total is inflated and the shift shows a false shortfall."""
    assert shifts._norm_mode("some-new-wallet") == "other"


# ═══════════════════════════════════════════════════════════════════════════
# print_payload — the amount in words on every printed bill
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("amount,want", [
    (0, "Zero Rupees Only"),
    (1, "One Rupees Only"),
    (19, "Nineteen Rupees Only"),
    (100, "One Hundred Rupees Only"),
    (118, "One Hundred and Eighteen Rupees Only"),
    (1000, "One Thousand Rupees Only"),
    (100000, "One Lakh Rupees Only"),
    (10000000, "One Crore Rupees Only"),
])
def test_amount_in_words_indian_numbering(amount, want):
    assert PP.amount_in_words(amount) == want


def test_amount_in_words_includes_paise():
    assert PP.amount_in_words(118.50) == "One Hundred and Eighteen Rupees and Fifty Paise Only"


def test_amount_in_words_never_raises():
    """It is rendered onto a customer's bill — a failure must degrade to an empty
    string, never take the print path down."""
    assert PP.amount_in_words("abc") == ""
    assert PP.amount_in_words(object()) == ""


def test_amount_in_words_treats_none_as_zero():
    """Documents ACTUAL behaviour rather than asserting what I first assumed.

    `_r2(None)` is 0.0 throughout this codebase, so a missing amount renders as
    "Zero Rupees Only" rather than an empty string. That is defensible — the
    numeral on the bill comes from the same value, so the words and the figure
    still agree — but it is worth pinning, because "Zero Rupees Only" is an
    ASSERTION about the bill, not a blank. If the amount ever becomes optional
    for a real reason, this test is the place that argument gets made.
    """
    assert PP.amount_in_words(None) == "Zero Rupees Only"
    assert PP.amount_in_words(0) == "Zero Rupees Only"
