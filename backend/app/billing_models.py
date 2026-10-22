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
    app/models.FieldStaff for why.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

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
