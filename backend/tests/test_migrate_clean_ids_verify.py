"""
tests/test_migrate_clean_ids_verify.py
======================================
The gate that decides whether a clean-id migration may be called done.

It compares the SOURCE export against the DESTINATION'S OWN re-export, not
against what the importer said it wrote — the importer marking its own homework
is how a migration reports success while a table is missing. The money check
exists because row counts alone pass a table that arrived with the right number
of rows and the wrong amounts in them, which is the shape that actually hurts.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from migrate_clean_ids import _counts, _money, _verify   # noqa: E402


def _payload(invoices=(), payments=()):
    return {"tables": {
        "invoices": [{"total_amount": a} for a in invoices],
        "invoice_payments": [{"amount_paid": a} for a in payments],
    }}


def test_identical_books_verify():
    p = _payload(invoices=(100.0, 250.5), payments=(50.0,))
    assert _verify(p, p) is True


def test_a_missing_table_fails():
    before = _payload(invoices=(100.0,), payments=(50.0,))
    after = {"tables": {"invoices": [{"total_amount": 100.0}]}}   # payments lost
    assert _verify(before, after) is False


def test_a_dropped_row_fails():
    assert _verify(_payload(invoices=(100.0, 250.5)),
                   _payload(invoices=(100.0,))) is False


def test_same_row_count_but_wrong_money_fails():
    """The case row counts alone would wave through."""
    assert _verify(_payload(invoices=(100.0, 250.5)),
                   _payload(invoices=(100.0, 25.05))) is False


def test_sub_paisa_drift_is_tolerated():
    """Float round-tripping through JSON must not fail a good migration."""
    assert _verify(_payload(invoices=(100.001,)),
                   _payload(invoices=(100.0,))) is True


def test_counts_ignore_empty_tables():
    # An export omits empty tables; a destination that also has none must match.
    assert _counts({"tables": {"invoices": [], "customers": [{"id": 1}]}}) == {"customers": 1}


def test_money_totals_treat_missing_and_null_as_zero():
    assert _money({"tables": {"invoices": [{"total_amount": None}, {}]}})["invoices"] == 0.0
