"""Read current Billing identities and balances without changing its records.

One cache per request/session, always keyed by business as well as row ID.
List endpoints prime it in batches; nested run/task serializers reuse it.
"""
from sqlalchemy.orm import object_session

from app.billing_models import BillingCustomer, BillingInvoice
from app.invoices import CREDIT_NOTE, invoice_balances


class BillingReadContext:
    def __init__(self, db):
        self.db = db
        self.customers = {}
        self.invoices = {}
        self.balances = {}

    def prime(self, *, shops=(), tasks=()):
        tasks = list(tasks)
        shops = list(shops) + [t.shop for t in tasks if t.shop is not None]
        customers = {}
        invoices = {}
        for shop in shops:
            if shop.customer_id is not None and (shop.business_id, shop.customer_id) not in self.customers:
                customers.setdefault(shop.business_id, set()).add(shop.customer_id)
        for task in tasks:
            for line in task.invoices:
                if (task.business_id, line.invoice_id) not in self.invoices:
                    invoices.setdefault(task.business_id, set()).add(line.invoice_id)
        for bid, ids in customers.items():
            self.customers.update({(bid, cid): None for cid in ids})
            for row in self.db.query(BillingCustomer).filter(
                    BillingCustomer.business_id == bid, BillingCustomer.id.in_(ids)).all():
                self.customers[(bid, row.id)] = row
        for bid, ids in invoices.items():
            self.invoices.update({(bid, iid): None for iid in ids})
            rows = self.db.query(BillingInvoice).filter(
                BillingInvoice.business_id == bid, BillingInvoice.id.in_(ids)).all()
            for row in rows:
                self.invoices[(bid, row.id)] = row
            self.balances.update({(bid, iid): balance for iid, balance in invoice_balances(self.db, rows).items()})

    def customer(self, shop):
        self.prime(shops=[shop])
        return self.customers.get((shop.business_id, shop.customer_id))

    def task_balances(self, task):
        self.prime(tasks=[task])
        customer = self.customer(task.shop) if task.shop else None
        live = {}
        for line in task.invoices:
            inv = self.invoices.get((task.business_id, line.invoice_id))
            available = bool(customer and inv and inv.customer_id == customer.id
                             and (inv.invoice_type or "") != CREDIT_NOTE
                             and (inv.status or "").lower() not in {"cancelled", "canceled", "void", "draft"})
            balance = self.balances.get((task.business_id, line.invoice_id), {})
            live[line.invoice_id] = {
                "available": available,
                "current_total": balance.get("total") if available else None,
                "current_paid": balance.get("paid") if available else None,
                "current_credited": balance.get("credited") if available else None,
                "current_effective_total": balance.get("effective_total") if available else None,
                "current_credit_due": balance.get("credit_due") if available else None,
                "current_balance_due": balance.get("outstanding") if available else None,
                "current_status": inv.status if available else None,
            }
        available = all(row["available"] for row in live.values()) if live else None
        due = round(sum(row["current_balance_due"] for row in live.values()), 2) if available else None
        return {"billing_balance_available": available, "current_amount_due": due}, live


def billing_context(row):
    db = object_session(row)
    if db is None:
        return None
    if "billing_read_context" not in db.info:
        db.info["billing_read_context"] = BillingReadContext(db)
    return db.info["billing_read_context"]


def prime_billing_reads(*, shops=(), tasks=()):
    shops, tasks = list(shops), list(tasks)
    row = next(iter(tasks or shops), None)
    context = billing_context(row) if row is not None else None
    if context is not None:
        context.prime(shops=shops, tasks=tasks)
