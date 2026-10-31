"""Use Billing's complete models for fixture writes into its real schema.

The service reads through a deliberately small mirror. Its read-only invoice
classes cannot stand in for Billing's write contract (UIDs and posting defaults).
The local development mirror remains sufficient for standalone SQLite tests.
"""
import os
import sys

if os.environ.get("TASK_TEST_BILLING_SCHEMA") == "external":
    billing_dir = os.environ["BILLING_BACKEND_DIR"]
    if billing_dir not in sys.path:
        sys.path.append(billing_dir)
    from database.models import Customer as BillingCustomer, Invoice as BillingInvoice, InvoiceLineItem as BillingInvoiceLine
    from core.models import InvoicePayment as BillingInvoicePayment
else:
    from app.billing_models import BillingCustomer, BillingInvoice, BillingInvoiceLine, BillingInvoicePayment
