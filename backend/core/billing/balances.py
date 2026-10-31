"""Read-only outstanding projections shared by money commands and views.

Credit/debit notes reduce the source document's obligation. They do not create a
cash refund or a new receipt. A paid return exposes credit due separately; callers
must not invent a payout or mutate the customer's banked advance balance.
"""
from collections import defaultdict
from sqlalchemy import func, and_, case
from database.models import Invoice, PurchaseInvoice
from core.models import InvoicePayment


def _money(value):
    return round(float(value or 0), 2)


def invoice_net_amount(invoice):
    """Support both historical negative notes and current positive note totals."""
    amount = float(invoice.total_amount or invoice.amount or 0)
    return -abs(amount) if invoice.invoice_type == "credit_note" else amount


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


def legacy_credit_notes(db, invoices):
    """Read old delimited return references without authorizing new payouts.

    Only an unambiguous number in the same business and named customer account
    may match. Modern notes always use the structural parent FK. Financial
    commands deliberately never accept this historical text link for refunds.
    """
    grouped, result = defaultdict(list), defaultdict(list)
    for inv in invoices:
        if inv.invoice_id and inv.invoice_type != "credit_note":
            grouped[inv.business_id].append(inv)
    def party(inv):
        return ("id", inv.customer_id) if inv.customer_id is not None else (
            ("name", inv.customer) if inv.customer else None)
    for business_id, group in grouped.items():
        numbers = {inv.invoice_id for inv in group}
        owners = defaultdict(list)
        # Include all candidate bills so a duplicated imported number is never
        # silently assigned to whichever bill happened to be requested first.
        for inv in db.query(Invoice).filter(Invoice.business_id == business_id,
                Invoice.invoice_id.in_(numbers),
                func.coalesce(Invoice.invoice_type, "") != "credit_note"):
            if party(inv) is not None:
                owners[(party(inv), inv.invoice_id)].append(inv.id)
        requested = {inv.id for inv in group}
        for note in db.query(Invoice).filter(Invoice.business_id == business_id,
                Invoice.invoice_type == "credit_note", Invoice.parent_invoice_id.is_(None)):
            if party(note) is None:
                continue
            for number in numbers:
                marker = f"Credit note against {number}."
                text = note.notes or ""
                if text != marker and not text.startswith(marker + " "):
                    continue
                candidates = owners.get((party(note), number), [])
                if len(candidates) == 1 and candidates[0] in requested:
                    result[candidates[0]].append(note)
    return result


def business_revenue_summary(db, business_id: int) -> dict:
    """Authoritative revenue, collection, and outstanding read model (BD-04).

    Distinguishes gross sales, credit-note returns, net revenue, actual cash
    collected, and overdue balances. Shared by AI tools, handlers, and dashboards.
    """
    from services.dates import biz_today_str
    from core.accounting.settlement_models import CustomerRefund, CustomerCreditAllocation
    invoices = db.query(Invoice).filter(Invoice.business_id == business_id).all()
    sales = [inv for inv in invoices if inv.invoice_type != "credit_note"]
    balances = invoice_balances(db, sales)
    receipts = db.query(InvoicePayment).filter(InvoicePayment.business_id == business_id).all()
    by_invoice = defaultdict(list)
    for receipt in receipts:
        by_invoice[receipt.invoice_id].append(receipt)
    gross = _money(sum(inv.total_amount or inv.amount or 0 for inv in sales))
    returns = _money(sum(abs(inv.total_amount or inv.amount or 0) for inv in invoices if inv.invoice_type == "credit_note"))
    # Fallback is PER INVOICE. A single modern receipt cannot hide paid legacy bills.
    cash = 0.0
    allocated_targets = {row[0] for row in db.query(CustomerCreditAllocation.target_invoice_id).filter(
        CustomerCreditAllocation.business_id == business_id).all()}
    for inv in sales:
        if inv.id in by_invoice:
            from core.accounting.repost import _is_advance_application
            cash += float(inv.legacy_paid_baseline or 0) + sum(
                float(p.amount_paid or 0) for p in by_invoice[inv.id] if not _is_advance_application(p))
        else:
            cash += float(inv.legacy_paid_baseline if inv.legacy_paid_baseline is not None else
                          (inv.paid_amount or ((inv.total_amount or inv.amount or 0)
                          if (inv.status or "").lower() == "paid" and inv.id not in allocated_targets else 0)))
    refunded = db.query(func.coalesce(func.sum(CustomerRefund.amount), 0)).filter(CustomerRefund.business_id == business_id).scalar()
    from core.models import JournalEntry, JournalLine
    from core.accounting.posting import ACC_CASH
    advances = db.query(func.coalesce(func.sum(JournalLine.debit), 0)).join(JournalEntry,
        JournalEntry.id == JournalLine.entry_id).filter(JournalEntry.business_id == business_id,
        JournalEntry.source_type == "advance_receipt", JournalLine.account == ACC_CASH).scalar()
    collected = _money(cash + float(advances or 0) - float(refunded or 0))
    net = _money(gross - returns)
    overdue = _money(sum(balances[inv.id]["outstanding"] for inv in sales
        if (inv.status or "").lower() == "overdue" or (inv.due_date and inv.due_date < biz_today_str())))
    pending = _money(sum(balance["outstanding"] for balance in balances.values()))
    return {"gross_revenue": gross, "sales_returns": returns, "net_revenue": net,
        "collected_revenue": collected, "cash_received": _money(cash + float(advances or 0)),
        "cash_refunded": _money(refunded), "advances_received": _money(advances),
        "overdue_revenue": overdue, "outstanding_revenue": pending,
        "pending_invoice_count": sum(balance["outstanding"] > 0 for balance in balances.values()),
        "invoice_count": len(sales), "paid_invoice_count": sum(balance["outstanding"] <= 0 for balance in balances.values()),
        "collection_rate_pct": round(collected / net * 100) if net > 0 else 0}


def invoice_balances(db, invoices, *, purchase=False):
    """Batch by tenant, with two queries per business instead of per invoice."""
    model = PurchaseInvoice if purchase else Invoice
    notes_type = "debit_note" if purchase else "credit_note"
    grouped, result = defaultdict(list), {}
    for invoice in invoices:
        grouped[invoice.business_id].append(invoice)
    for business_id, group in grouped.items():
        ids = [invoice.id for invoice in group]
        credit_amount = (func.abs(func.coalesce(func.nullif(model.total_amount, 0), model.amount, 0))
                         if not purchase else func.abs(model.total_amount))
        credits = dict(db.query(model.parent_invoice_id, func.sum(credit_amount)).filter(
            model.business_id == business_id, model.parent_invoice_id.in_(ids),
            model.invoice_type == notes_type).group_by(model.parent_invoice_id).all())
        if not purchase:
            legacy_returns = legacy_credit_notes(db, group)
            for invoice_id, notes in legacy_returns.items():
                credits[invoice_id] = float(credits.get(invoice_id) or 0) + sum(
                    abs(float(note.total_amount or note.amount or 0)) for note in notes)
        receipts = {} if purchase else dict(db.query(InvoicePayment.invoice_id, func.sum(InvoicePayment.amount_paid)).filter(
            InvoicePayment.business_id == business_id, InvoicePayment.invoice_id.in_(ids)
        ).group_by(InvoicePayment.invoice_id).all())
        from core.accounting.settlement_models import SupplierPayment, CustomerRefund, CustomerCreditAllocation
        if purchase:
            receipts = dict(db.query(SupplierPayment.purchase_invoice_id, func.sum(SupplierPayment.amount)).filter(
                SupplierPayment.business_id == business_id, SupplierPayment.purchase_invoice_id.in_(ids)
            ).group_by(SupplierPayment.purchase_invoice_id).all())
            refunds, outgoing, incoming = {}, {}, {}
        else:
            refunds = dict(db.query(CustomerRefund.source_invoice_id, func.sum(CustomerRefund.amount)).filter(
                CustomerRefund.business_id == business_id, CustomerRefund.source_invoice_id.in_(ids)
            ).group_by(CustomerRefund.source_invoice_id).all())
            outgoing = dict(db.query(CustomerCreditAllocation.source_invoice_id, func.sum(CustomerCreditAllocation.amount)).filter(
                CustomerCreditAllocation.business_id == business_id, CustomerCreditAllocation.source_invoice_id.in_(ids)
            ).group_by(CustomerCreditAllocation.source_invoice_id).all())
            incoming = dict(db.query(CustomerCreditAllocation.target_invoice_id, func.sum(CustomerCreditAllocation.amount)).filter(
                CustomerCreditAllocation.business_id == business_id, CustomerCreditAllocation.target_invoice_id.in_(ids)
            ).group_by(CustomerCreditAllocation.target_invoice_id).all())
        for invoice in group:
            total = invoice.total_amount
            # Existing CSV-era migrations introduced total_amount with a zero
            # default while retaining the real amount in the legacy column.
            # Modern genuinely free sales persist zero in both columns.
            if not total and not purchase:
                total = invoice.amount
            if purchase:
                paid = receipts.get(invoice.id, total if (invoice.status or "").lower() == "paid" else 0.0)
            else:
                baseline = getattr(invoice, "legacy_paid_baseline", None)
                legacy_paid = baseline if baseline is not None else (invoice.paid_amount or
                    (total if (invoice.status or "").lower() == "paid" and invoice.id not in incoming else 0.0))
                paid = (_money(receipts[invoice.id] + float(getattr(invoice, "legacy_paid_baseline", None) or 0))
                        if invoice.id in receipts else legacy_paid)
                paid = _money(paid + incoming.get(invoice.id, 0) - outgoing.get(invoice.id, 0) - refunds.get(invoice.id, 0))
            balance = credit_adjusted_balance(total, paid, credits.get(invoice.id, 0))
            if invoice.invoice_type == notes_type:
                # A return document is a reduction, never a collectible bill.
                balance["outstanding"] = 0.0
                balance["credit_due"] = 0.0
            result[invoice.id] = balance
    return result


def invoice_balance(db, invoice, *, purchase=False):
    return invoice_balances(db, [invoice], purchase=purchase)[invoice.id]


def outstanding_rows(db, business_id, *, overdue=None):
    """Canonical collection rows for AI, reminders and reports; never mutate ORM facts."""
    from types import SimpleNamespace
    from services.dates import biz_today_str
    invoices = db.query(Invoice).filter(Invoice.business_id == business_id,
        func.coalesce(Invoice.invoice_type, "") != "credit_note").all()
    balances = invoice_balances(db, invoices)
    rows = []
    for invoice in invoices:
        balance = balances[invoice.id]
        is_overdue = ((invoice.status or "").lower() == "overdue"
                      or bool(invoice.due_date and invoice.due_date < biz_today_str()))
        if balance["outstanding"] <= 0 or (overdue is not None and overdue != is_overdue):
            continue
        rows.append(SimpleNamespace(id=invoice.id, invoice_id=invoice.invoice_id, customer=invoice.customer,
            customer_id=invoice.customer_id, invoice_date=invoice.invoice_date, due_date=invoice.due_date,
            amount=balance["outstanding"], paid_amount=balance["paid"], total_amount=balance["total"],
            credited_amount=balance["credited"], status="Overdue" if is_overdue else collection_status(balance)))
    return sorted(rows, key=lambda row: row.amount, reverse=True)


def customer_revenue_rows(db, business_id):
    """Net signed sales by customer, preserving zero-net returned customers."""
    totals = defaultdict(lambda: {"total_amount": 0.0, "invoice_count": 0})
    for invoice in db.query(Invoice.customer, Invoice.amount, Invoice.total_amount, Invoice.invoice_type).filter(
            Invoice.business_id == business_id):
        row = totals[invoice.customer]
        amount = float(invoice.total_amount or invoice.amount or 0)
        row["total_amount"] += -abs(amount) if invoice.invoice_type == "credit_note" else amount
        row["invoice_count"] += invoice.invoice_type != "credit_note"
    from types import SimpleNamespace
    return sorted((SimpleNamespace(customer=name, total_amount=_money(row["total_amount"]), invoice_count=row["invoice_count"])
                   for name, row in totals.items()), key=lambda row: row.total_amount, reverse=True)


def debtor_rows(db, business_id):
    from types import SimpleNamespace
    totals = defaultdict(lambda: [0.0, 0])
    for row in outstanding_rows(db, business_id, overdue=True):
        totals[row.customer][0] += row.amount
        totals[row.customer][1] += 1
    return sorted((SimpleNamespace(customer=name, overdue_total=_money(value[0]), invoices=value[1], overdue_count=value[1])
                   for name, value in totals.items()), key=lambda row: row.overdue_total, reverse=True)


def grouped_overdue_rows(db, business_id, selected=None):
    from types import SimpleNamespace
    grouped = {}
    for row in outstanding_rows(db, business_id, overdue=True):
        if selected and row.customer not in selected:
            continue
        current = grouped.setdefault(row.customer, {"total": 0.0, "due": None, "n": 0})
        current["total"] += row.amount
        current["n"] += 1
        if row.due_date and (current["due"] is None or row.due_date > current["due"]):
            current["due"] = row.due_date
    return sorted((SimpleNamespace(customer=name, total=_money(value["total"]), due=value["due"],
                                   n=value["n"], invoices=value["n"]) for name, value in grouped.items()),
                  key=lambda row: row.total, reverse=True)


def signed_invoice_amount():
    amount = func.coalesce(func.nullif(Invoice.total_amount, 0), Invoice.amount, 0)
    return case((Invoice.invoice_type == "credit_note", -func.abs(amount)), else_=amount)


def monthly_revenue_rows(db, business_id, months=12):
    """Net dated sales and actual dated receipts, never Paid-status sums."""
    from core.accounting.settlement_models import CustomerRefund, CustomerCreditAllocation
    from core.accounting.repost import _is_advance_application
    from services.dates import parse_date_only
    aggregate = defaultdict(lambda: {"billed": 0.0, "collected": 0.0, "invoices": 0})
    invoices = db.query(Invoice).filter(Invoice.business_id == business_id).all()
    receipts = db.query(InvoicePayment).filter(InvoicePayment.business_id == business_id).all()
    receipt_ids = {row.invoice_id for row in receipts}
    allocated = {row[0] for row in db.query(CustomerCreditAllocation.target_invoice_id).filter(CustomerCreditAllocation.business_id == business_id)}
    def period(value):
        value = parse_date_only(value)
        return value.strftime("%Y-%m") if value else None
    for invoice in invoices:
        month = period(invoice.invoice_date)
        if not month:
            continue
        note = invoice.invoice_type == "credit_note"
        amount = float(invoice.total_amount or invoice.amount or 0)
        aggregate[month]["billed"] += -abs(amount) if note else amount
        aggregate[month]["invoices"] += not note
        if not note and invoice.id not in receipt_ids:
            legacy = (invoice.legacy_paid_baseline if invoice.legacy_paid_baseline is not None else
                (invoice.paid_amount or ((invoice.total_amount or invoice.amount or 0)
                     if invoice.status == "Paid" and invoice.id not in allocated else 0)))
            aggregate[period(invoice.legacy_paid_baseline_date or invoice.payment_date) or month]["collected"] += float(legacy)
        elif not note and invoice.legacy_paid_baseline:
            aggregate[period(invoice.legacy_paid_baseline_date) or month]["collected"] += float(invoice.legacy_paid_baseline)
    for row in receipts:
        month = period(row.payment_date)
        if month and not _is_advance_application(row):
            aggregate[month]["collected"] += float(row.amount_paid or 0)
    for row in db.query(CustomerRefund).filter(CustomerRefund.business_id == business_id):
        month = period(row.payment_date)
        if month:
            aggregate[month]["collected"] -= row.amount
    from core.models import JournalEntry, JournalLine
    from core.accounting.posting import ACC_CASH
    for entry_date, amount in db.query(JournalEntry.entry_date, JournalLine.debit).join(JournalLine,
        JournalLine.entry_id == JournalEntry.id).filter(JournalEntry.business_id == business_id,
        JournalEntry.source_type == "advance_receipt", JournalLine.account == ACC_CASH):
        month = period(entry_date)
        if month:
            aggregate[month]["collected"] += float(amount or 0)
    keys = sorted(aggregate)
    if months:
        keys = keys[-months:]
    return [{"month": month, **{key: _money(value) if key != "invoices" else int(value)
             for key, value in aggregate[month].items()}} for month in keys]


def party_balance(db, business_id, party_id, *, purchase=False):
    model = PurchaseInvoice if purchase else Invoice
    party_column = model.supplier_id if purchase else model.customer_id
    note_type = "debit_note" if purchase else "credit_note"
    # Read header columns directly: querying the ORM entity would eagerly load
    # every invoice's line_items on a party list even though no lines are needed.
    columns = [model.id, model.business_id, model.invoice_type, model.invoice_date,
               model.total_amount, model.status]
    if not purchase:
        columns.extend([model.amount, model.paid_amount, model.legacy_paid_baseline,
                        model.invoice_id, model.customer_id, model.customer])
    invoices = db.query(*columns).filter(model.business_id == business_id, party_column == party_id,
        func.coalesce(model.invoice_type, "") != note_type).all()
    balances = invoice_balances(db, invoices, purchase=purchase)
    signed = _money(sum(value["outstanding"] - value["credit_due"] for value in balances.values()))
    last_date = max((invoice.invoice_date for invoice in invoices if invoice.invoice_date), default=None)
    return {"outstanding": max(signed, 0.0), "credit_due": max(-signed, 0.0), "last_date": last_date}
