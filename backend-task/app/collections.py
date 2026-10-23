"""
app/collections.py — field collections and billing payments.

Staff collect money on a `payment_collect` task. The owner confirms it in
BizAssist Billing (Contacts & Payments → Field collections); billing records one
payment per bill through its own payment command, keyed
`ft-collect:<task uid>:<invoice id>` so it is never recorded twice
(billing core/field_team.py). Field Team never writes billing's tables: it reads
those payments back to show what the owner has confirmed.
"""
from __future__ import annotations

from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.billing_models import BillingInvoicePayment

# Must equal billing's core/field_team.KEY_PREFIX (tests/test_billing_contract.py).
KEY_PREFIX = "ft-collect:"
# Billing's payment modes (invoice_payments.payment_mode).
PAYMENT_MODES = ("Cash", "UPI", "Cheque", "NEFT", "Card")


def confirmed_in_billing(db: Session, business_id: int, task_uids: Iterable[str]) -> dict:
    """task uid → amount the owner has confirmed in billing so far."""
    uids = [u for u in set(task_uids) if u]
    if not uids:
        return {}
    uid_of_key = func.substr(BillingInvoicePayment.idempotency_key, len(KEY_PREFIX) + 1, 36)
    rows = (db.query(uid_of_key, func.sum(BillingInvoicePayment.amount_paid))
            .filter(BillingInvoicePayment.business_id == business_id,
                    BillingInvoicePayment.idempotency_key.like(f"{KEY_PREFIX}%"),
                    uid_of_key.in_(uids))
            .group_by(uid_of_key).all())
    return {uid: round(float(total or 0.0), 2) for uid, total in rows}
