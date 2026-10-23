"""
app/billing_models.py — the billing tables this service reads.
==============================================================
Column-for-column SUBSETS of `bizassist-billing/backend/database/models.py`.
Only the columns used here are declared; the real tables have more, which is
harmless for reads and for the one insert we do (owner signup), because every
undeclared billing column is nullable or has a server default.

RULES (do not relax):
  * Never add a column here that billing does not have — the Postgres table is
    billing's, and this file is not a migration.
  * The ONLY write is creating an owner account (`/auth/signup`, same shape as
    billing's own signup). Field staff are NOT `users` rows — see
    app/models.FieldStaff for why. Invoices are read, never written: money and
    bills change only through billing's own code.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.db import BillingBase, utc_now


class BillingUser(BillingBase):
    """`users` — one row per business owner (parent_business_id IS NULL) plus
    billing's own counter staff (parent_business_id = owner id)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)  # bcrypt hash
    business_name = Column(String)
    role = Column(String, default="enterprise")
    parent_business_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    public_id = Column(String, unique=True, index=True, nullable=True)  # BizID BA-XXXXXX
    phone = Column(String, nullable=True)
    token_version = Column(Integer, default=0, nullable=False, server_default="0")
    # JSON. Read for one key only: `subscription` (the owner's plan, written by
    # billing's admin console) — see app/plan.py. Never written here.
    settings = Column(Text, nullable=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=True)


class BillingCustomer(BillingBase):
    """`customers` — the owner's buyers. For a wholesale/medical distributor these
    ARE the retail shops on a delivery route, so shops can be imported from here
    and stay linked (customer_id) for future B2B ordering through billing."""
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True, nullable=True)
    uid = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, index=True)
    phone = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    gstin = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=True)


class BillingInvoice(BillingBase):
    """`invoices` — the owner's sales bills, read to plan deliveries and
    collections per shop. Credit notes share the table (`invoice_type` =
    "credit_note"); the amount due is `total_amount - paid_amount`, the same
    formula billing's outstanding reports use."""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True, nullable=True)
    invoice_id = Column(String, index=True, nullable=True)  # the printed number, e.g. INV-0042
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    invoice_date = Column(String, nullable=True)  # YYYY-MM-DD
    status = Column(String, index=True, nullable=True)  # Pending | Partial | Paid
    invoice_type = Column(String, nullable=True)  # B2B | B2C | … | credit_note
    amount = Column(Float, nullable=True)  # legacy total (CSV imports set only this)
    total_amount = Column(Float, nullable=True, default=0.0)
    paid_amount = Column(Float, nullable=True, default=0.0)


class BillingInvoicePayment(BillingBase):
    """`invoice_payments` — billing's append-only receipts. Read to show which
    field collections the owner has confirmed in billing (app/collections.py)."""
    __tablename__ = "invoice_payments"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True, nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    amount_paid = Column(Float, nullable=False)
    payment_mode = Column(String, nullable=True)
    payment_date = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True, index=True)


class BillingInvoiceLine(BillingBase):
    """`invoice_line_items` — what was billed, to suggest the boxes to deliver."""
    __tablename__ = "invoice_line_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    product_name = Column(String, nullable=False)
    unit = Column(String, nullable=True, default="Nos")
    quantity = Column(Float, nullable=False, default=1.0)
    returned_qty = Column(Float, nullable=True, default=0.0)
    # Not read; declared because billing's column is NOT NULL without a server
    # default, so a row inserted through this mirror (tests) must set it.
    unit_price = Column(Float, nullable=False, default=0.0)
