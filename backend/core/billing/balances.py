"""Read-only outstanding projections shared by money commands and views.

Credit/debit notes reduce the source document's obligation. They do not create a
cash refund or a new receipt. A paid return exposes credit due separately; callers
must not invent a payout or mutate the customer's banked advance balance.
"""
from collections import defaultdict
from sqlalchemy import func
from database.models import Invoice, PurchaseInvoice
from core.models import InvoicePayment


def _money(value):
    return round(float(value or 0), 2)


def credit_adjusted_balance(total, paid, credits):
    total, paid, credits = _money(total), _money(paid), _money(credits)
    effective_total = max(_money(total - credits), 0.0)
    signed = _money(effective_total - paid)
    return {"total": total, "paid": paid, "credited": credits,
            "effective_total": effective_total, "outstanding": max(signed, 0.0),
            "credit_due": max(-signed, 0.0)}


def collection_status(balance, fallback="Pending"):
    if balance["outstanding"] <= 0 and (balance["total"] > 0 or balance["credited"] > 0):
        return "Paid"
    if balance["paid"] > 0:
        return "Partial"
    return fallback if balance["total"] == 0 else "Pending"


def invoice_balances(db, invoices, *, purchase=False):
    """Batch by tenant, with two queries per business instead of per invoice."""
    model = PurchaseInvoice if purchase else Invoice
    notes_type = "debit_note" if purchase else "credit_note"
    grouped, result = defaultdict(list), {}
    for invoice in invoices:
        grouped[invoice.business_id].append(invoice)
    for business_id, group in grouped.items():
        ids = [invoice.id for invoice in group]
        credits = dict(db.query(model.parent_invoice_id, func.sum(model.total_amount)).filter(
            model.business_id == business_id, model.parent_invoice_id.in_(ids),
            model.invoice_type == notes_type).group_by(model.parent_invoice_id).all())
        receipts = {} if purchase else dict(db.query(InvoicePayment.invoice_id, func.sum(InvoicePayment.amount_paid)).filter(
            InvoicePayment.business_id == business_id, InvoicePayment.invoice_id.in_(ids)
        ).group_by(InvoicePayment.invoice_id).all())
        for invoice in group:
            total = invoice.total_amount
            # Existing CSV-era migrations introduced total_amount with a zero
            # default while retaining the real amount in the legacy column.
            # Modern genuinely free sales persist zero in both columns.
            if not total and not purchase:
                total = invoice.amount
            if purchase:
                paid = total if (invoice.status or "").lower() == "paid" else 0.0
            else:
                paid = receipts.get(invoice.id, invoice.paid_amount)
            balance = credit_adjusted_balance(total, paid, credits.get(invoice.id, 0))
            if invoice.invoice_type == notes_type:
                # A return document is a reduction, never a collectible bill.
                balance["outstanding"] = 0.0
                balance["credit_due"] = 0.0
            result[invoice.id] = balance
    return result


def invoice_balance(db, invoice, *, purchase=False):
    return invoice_balances(db, [invoice], purchase=purchase)[invoice.id]


def party_balance(db, business_id, party_id, *, purchase=False):
    model = PurchaseInvoice if purchase else Invoice
    party_column = model.supplier_id if purchase else model.customer_id
    note_type = "debit_note" if purchase else "credit_note"
    # Read header columns directly: querying the ORM entity would eagerly load
    # every invoice's line_items on a party list even though no lines are needed.
    columns = [model.id, model.business_id, model.invoice_type, model.invoice_date,
               model.total_amount, model.status]
    if not purchase:
        columns.extend([model.amount, model.paid_amount])
    invoices = db.query(*columns).filter(model.business_id == business_id, party_column == party_id,
        func.coalesce(model.invoice_type, "") != note_type).all()
    balances = invoice_balances(db, invoices, purchase=purchase)
    signed = _money(sum(value["outstanding"] - value["credit_due"] for value in balances.values()))
    last_date = max((invoice.invoice_date for invoice in invoices if invoice.invoice_date), default=None)
    return {"outstanding": max(signed, 0.0), "credit_due": max(-signed, 0.0), "last_date": last_date}
