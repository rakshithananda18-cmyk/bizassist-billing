"""Parse invoice templates and render synthetic settlement/no-adjustment cases.

Run from the repository root with the test environment's Python interpreter.
This imports no application, opens no database and uses no external service.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


root = Path(__file__).resolve().parents[4]
base = root / "backend/core/billing/templates"
environment = Environment(loader=FileSystemLoader(str(base)), autoescape=True)
names = sorted(str(path.relative_to(base)) for path in base.rglob("*.html"))
for name in names:
    environment.get_template(name)
print(f"Parsed templates: {len(names)} ({', '.join(names)})")

payload = {
    "settings": {},
    "invoice": {"title": "Synthetic Invoice", "number": "TEST-1", "date": "2026-10-31"},
    "seller": {"name": "Synthetic Seller"},
    "buyer": {"name": "Synthetic Buyer"},
    "visibility": {},
    "lines": [], "tax_summary": [], "payments": [], "footer": {},
    "totals": {
        "taxable_amount": 100, "grand_total": 100, "amount_paid": 30,
        "total_discount": 0, "cgst_total": 0, "sgst_total": 0,
        "igst_total": 0, "cess_total": 0, "round_off": 0,
        "cash_discount": 0, "amount_in_words": "One hundred only",
        "credited_amount": 20, "adjusted_total": 80,
        "amount_refunded": 5, "return_credit": 10, "balance_due": 50,
    },
}
labels = ("Credit Notes", "Adjusted Payable", "Refund Paid", "Credit Owed to Customer", "Payments / Credit Applied")
for name in names:
    html = environment.get_template(name).render(payload=payload, **payload)
    assert all(label in html for label in labels), name
print(f"Credit/refund/application summary renders: {len(names)} passed")

payload["totals"].update(credited_amount=0, amount_refunded=0, return_credit=0)
for name in names:
    html = environment.get_template(name).render(payload=payload, **payload)
    assert "Payments / Credit Applied" in html, name
    assert "Refund Paid" not in html and "Credit Notes" not in html, name
print(f"Zero-adjustment summary renders: {len(names)} passed")
