"""
tests/test_purchase_status_vocabulary.py
========================================
Purchase-bill status is LOWERCASE — 'pending' / 'confirmed'.

A B2B order wrote `status="Pending"` while the Purchase Bills list buckets on
`'pending'`. `"Pending" !== "pending"`, so the bill matched neither tab, was not
a debit note, and appeared in NO bucket — invisible in the UI while still
driving the supplier's outstanding balance, which is computed server-side from
the same row. The owner saw a vendor owed ₹1,731 against a bill shown nowhere,
and an order stamped "Purchase bill posted".

Nothing catches a case mismatch at runtime: it is a valid string, it stores
fine, and every total that reads the row is correct. Only the reader silently
disagrees. So this is a source guard, not a behaviour test.

Sale invoices use a SEPARATE, capitalised vocabulary ("Pending") that is
consistent with create_sale_invoice and the dashboard filters — do not unify
them. This checks `PurchaseInvoice(...)` constructions only.
"""
import ast
import os
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]

# Directories that construct domain objects. Tests and migrations are excluded:
# a migration legitimately writes historical values.
SEARCH_DIRS = ("core", "routes", "services")

ALLOWED = {"pending", "confirmed", "debit_note", "cancelled", "draft", "paid",
           "partial", "unpaid"}


def _purchase_invoice_statuses():
    """(file, line, value) for every literal `status=` on a PurchaseInvoice()."""
    found = []
    for d in SEARCH_DIRS:
        for path in (BACKEND / d).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if name != "PurchaseInvoice":
                    continue
                for kw in node.keywords:
                    if kw.arg == "status" and isinstance(kw.value, ast.Constant) \
                            and isinstance(kw.value.value, str):
                        found.append((path.relative_to(BACKEND).as_posix(),
                                      kw.value.lineno, kw.value.value))
    return found


def test_purchase_bill_status_is_lowercase():
    offenders = [(f, ln, v) for f, ln, v in _purchase_invoice_statuses() if v != v.lower()]
    assert not offenders, (
        "PurchaseInvoice.status must be lowercase — the Purchase Bills list "
        "buckets on 'pending'/'confirmed', and a mismatch hides the bill in "
        "every tab while it still drives the supplier balance:\n  "
        + "\n  ".join(f"{f}:{ln} status={v!r}" for f, ln, v in offenders)
    )


def test_purchase_bill_status_uses_a_known_value():
    """A status outside the vocabulary lands in no bucket for the same reason,
    even when it is correctly lowercased."""
    unknown = [(f, ln, v) for f, ln, v in _purchase_invoice_statuses()
               if v.lower() not in ALLOWED]
    assert not unknown, (
        "unrecognised purchase-bill status — add it to ALLOWED here and give it "
        "a home in the Purchase Bills tabs, or the bill is invisible:\n  "
        + "\n  ".join(f"{f}:{ln} status={v!r}" for f, ln, v in unknown)
    )


def test_the_guard_actually_finds_the_constructions():
    """Guard the guard: if PurchaseInvoice were renamed or the search dirs moved,
    both tests above would pass by finding nothing at all."""
    assert _purchase_invoice_statuses(), (
        "found no PurchaseInvoice(status=...) constructions — this guard has "
        "stopped looking at the right code and is now vacuously green"
    )
