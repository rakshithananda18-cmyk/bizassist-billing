"""
database/models.py
==================
SQLAlchemy ORM models for BizAssist.

SOLID design:
  S - each model owns one entity
  O - extend via Mixins; never modify existing columns
  L - all models honour BusinessOwnedMixin contract
  I - Mixins are small and composable
  D - code above depends on models, not raw SQL

Backward compatibility: all original columns kept, new columns nullable.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime,
    Boolean, Text, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from database.db import Base


# ---------------------------------------------------------------------------
# MIXINS
# ---------------------------------------------------------------------------

class TimestampMixin:
    """Adds created_at / updated_at. Does NOT add id or business_id."""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)


class BusinessOwnedMixin(TimestampMixin):
    """Every tenant-scoped table inherits this: id, business_id, timestamps."""
    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True, nullable=True)


class GSTFieldsMixin:
    """
    Composable GST fields for financial documents (Invoice, PurchaseOrder).
    Holds document-level tax totals only; per-line rates live on LineItem models.
    """
    gstin_buyer     = Column(String, nullable=True)
    place_of_supply = Column(String, nullable=True)
    invoice_type    = Column(String, nullable=True)       # B2B|B2C|Export|SEZ
    subtotal        = Column(Float,  nullable=True, default=0.0)
    cgst_total      = Column(Float,  nullable=True, default=0.0)
    sgst_total      = Column(Float,  nullable=True, default=0.0)
    igst_total      = Column(Float,  nullable=True, default=0.0)
    cess_total      = Column(Float,  nullable=True, default=0.0)
    total_amount    = Column(Float,  nullable=True, default=0.0)
    irn             = Column(String, nullable=True)       # e-invoice IRN (Phase 3)
    ack_no          = Column(String, nullable=True)
    ack_date        = Column(String, nullable=True)
    qr_code         = Column(Text,   nullable=True)


# ---------------------------------------------------------------------------
# USER / TENANT
# ---------------------------------------------------------------------------

class User(Base, TimestampMixin):
    """Business owner account. One User = one business tenant."""
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String, unique=True, index=True)
    password      = Column(String)
    business_name = Column(String)
    role          = Column(String, default="enterprise")  # enterprise|admin
    # Business GST identity (Phase 3)
    gstin         = Column(String, nullable=True)
    phone         = Column(String, nullable=True)
    email         = Column(String, nullable=True)
    address       = Column(Text,   nullable=True)
    state_code    = Column(String, nullable=True)
    pan           = Column(String, nullable=True)


class UploadedFile(Base, TimestampMixin):
    __tablename__ = "uploaded_files"

    id          = Column(Integer, primary_key=True, index=True)
    filename    = Column(String)
    file_type   = Column(String)
    rows_count  = Column(Integer)
    upload_time = Column(String)
    business_id = Column(Integer, nullable=True, index=True)
    file_hash   = Column(String,  nullable=True, index=True)


# ---------------------------------------------------------------------------
# CUSTOMER  (buyer entity)
# ---------------------------------------------------------------------------

class Customer(Base, BusinessOwnedMixin):
    """
    Buyer / client entity.
    Invoice.customer (string) preserved for CSV compat.
    customer_id FK on Invoice is nullable.
    """
    __tablename__ = "customers"

    name         = Column(String, index=True)
    gstin        = Column(String, nullable=True, index=True)
    phone        = Column(String, nullable=True)
    email        = Column(String, nullable=True)
    address      = Column(Text,   nullable=True)
    state_code   = Column(String, nullable=True)
    pan          = Column(String, nullable=True)
    credit_limit = Column(Float,   nullable=True, default=0.0)
    credit_days  = Column(Integer, nullable=True, default=30)
    is_active    = Column(Boolean, default=True)

    invoices = relationship(
        "Invoice", back_populates="customer_ref", lazy="dynamic",
        foreign_keys="Invoice.customer_id"
    )


# ---------------------------------------------------------------------------
# VENDOR  (supplier entity)
# ---------------------------------------------------------------------------

class Vendor(Base, BusinessOwnedMixin):
    """Supplier from whom the business purchases goods."""
    __tablename__ = "vendors"

    name               = Column(String, index=True)
    gstin              = Column(String, nullable=True, index=True)
    phone              = Column(String, nullable=True)
    email              = Column(String, nullable=True)
    address            = Column(Text,   nullable=True)
    state_code         = Column(String, nullable=True)
    pan                = Column(String, nullable=True)
    payment_terms_days = Column(Integer, nullable=True, default=30)
    last_gstr1_filed   = Column(String, nullable=True)   # YYYY-MM
    filing_reliability = Column(Float,  nullable=True)   # 0.0-1.0
    is_active          = Column(Boolean, default=True)

    inventory_items = relationship(
        "Inventory", back_populates="vendor_ref", lazy="dynamic",
        foreign_keys="Inventory.vendor_id"
    )
    purchase_orders = relationship("PurchaseOrder", back_populates="vendor", lazy="dynamic")


# ---------------------------------------------------------------------------
# PRODUCT  (catalogue)
# ---------------------------------------------------------------------------

class Product(Base, BusinessOwnedMixin):
    """Product/service catalogue. HSN and default tax rates auto-populate line items."""
    __tablename__ = "products"

    name          = Column(String, index=True)
    description   = Column(Text,   nullable=True)
    hsn_sac       = Column(String, nullable=True, index=True)
    unit          = Column(String, nullable=True, default="Nos")
    barcode       = Column(String, nullable=True, index=True)
    selling_price = Column(Float,  nullable=True, default=0.0)
    cost_price    = Column(Float,  nullable=True, default=0.0)
    mrp           = Column(Float,  nullable=True)
    cgst_rate     = Column(Float,  nullable=True, default=0.0)
    sgst_rate     = Column(Float,  nullable=True, default=0.0)
    igst_rate     = Column(Float,  nullable=True, default=0.0)
    is_service    = Column(Boolean, default=False)
    is_active     = Column(Boolean, default=True)

    invoice_line_items = relationship(
        "InvoiceLineItem", back_populates="product_ref", lazy="dynamic",
        foreign_keys="InvoiceLineItem.product_id"
    )


# ---------------------------------------------------------------------------
# INVOICE  (existing table, backward-compatible extension)
# ---------------------------------------------------------------------------

class Invoice(Base, BusinessOwnedMixin, GSTFieldsMixin):
    """
    Sales invoice.
    Original columns kept as-is. New columns are all nullable.
    CSV-imported rows use customer/product/amount.
    App-created invoices use customer_id and line_items.
    """
    __tablename__ = "invoices"

    # Original columns (handlers depend on these)
    invoice_id   = Column(String, index=True,  nullable=True)
    customer     = Column(String, index=True,  nullable=True)
    product      = Column(String, nullable=True)
    amount       = Column(Float,  nullable=True)
    status       = Column(String, index=True,  nullable=True)
    invoice_date = Column(String, nullable=True)
    due_date     = Column(String, nullable=True)
    file_id      = Column(Integer, nullable=True, index=True)

    # New FK
    customer_id  = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)

    # Payment tracking
    paid_amount  = Column(Float,  nullable=True, default=0.0)
    payment_date = Column(String, nullable=True)
    payment_mode = Column(String, nullable=True)
    notes        = Column(Text,   nullable=True)

    customer_ref = relationship("Customer", back_populates="invoices", foreign_keys=[customer_id])
    line_items   = relationship(
        "InvoiceLineItem", back_populates="invoice",
        cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_invoice_business_status", "business_id", "status"),
        Index("ix_invoice_business_date",   "business_id", "invoice_date"),
    )


# ---------------------------------------------------------------------------
# INVOICE LINE ITEM
# ---------------------------------------------------------------------------

class InvoiceLineItem(Base, TimestampMixin):
    """
    One product row on an invoice.
    product_name is denormalised (snapshot) so historical invoices stay accurate.
    Tax stored per-line for GSTR-1 HSN-summary generation.
    """
    __tablename__ = "invoice_line_items"

    id            = Column(Integer, primary_key=True, index=True)
    invoice_id    = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    product_id    = Column(Integer, ForeignKey("products.id"), nullable=True,  index=True)

    product_name  = Column(String, nullable=False)
    hsn_sac       = Column(String, nullable=True)
    unit          = Column(String, nullable=True, default="Nos")
    quantity      = Column(Float,  nullable=False, default=1.0)
    unit_price    = Column(Float,  nullable=False, default=0.0)
    discount      = Column(Float,  nullable=True,  default=0.0)
    discount_pct  = Column(Float,  nullable=True,  default=0.0)

    cgst_rate     = Column(Float,  nullable=True, default=0.0)
    sgst_rate     = Column(Float,  nullable=True, default=0.0)
    igst_rate     = Column(Float,  nullable=True, default=0.0)
    cess_rate     = Column(Float,  nullable=True, default=0.0)

    taxable_value = Column(Float,  nullable=True, default=0.0)
    cgst_amount   = Column(Float,  nullable=True, default=0.0)
    sgst_amount   = Column(Float,  nullable=True, default=0.0)
    igst_amount   = Column(Float,  nullable=True, default=0.0)
    cess_amount   = Column(Float,  nullable=True, default=0.0)
    line_total    = Column(Float,  nullable=True, default=0.0)

    invoice     = relationship("Invoice", back_populates="line_items")
    product_ref = relationship("Product", back_populates="invoice_line_items",
                               foreign_keys=[product_id])


# ---------------------------------------------------------------------------
# INVENTORY  (existing table, backward-compatible extension)
# ---------------------------------------------------------------------------

class Inventory(Base, BusinessOwnedMixin):
    """Stock position. Original columns kept. New columns nullable."""
    __tablename__ = "inventory"

    product_name  = Column(String,  index=True, nullable=True)
    stock         = Column(Integer, nullable=True)
    expiry_date   = Column(String,  nullable=True)
    supplier      = Column(String,  nullable=True)
    file_id       = Column(Integer, nullable=True, index=True)

    vendor_id     = Column(Integer, ForeignKey("vendors.id"),  nullable=True, index=True)
    product_id    = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)

    unit          = Column(String,  nullable=True, default="Nos")
    hsn_sac       = Column(String,  nullable=True)
    barcode       = Column(String,  nullable=True, index=True)
    batch_no      = Column(String,  nullable=True)
    mrp           = Column(Float,   nullable=True)
    cost_price    = Column(Float,   nullable=True, default=0.0)
    selling_price = Column(Float,   nullable=True, default=0.0)
    reorder_point = Column(Integer, nullable=True, default=10)
    category      = Column(String,  nullable=True)

    vendor_ref = relationship("Vendor", back_populates="inventory_items",
                              foreign_keys=[vendor_id])

    __table_args__ = (
        Index("ix_inventory_business_stock", "business_id", "stock"),
    )


# ---------------------------------------------------------------------------
# PAYMENT  (existing table, kept for backward compat)
# ---------------------------------------------------------------------------

class Payment(Base, BusinessOwnedMixin):
    """Legacy payment records from CSV imports."""
    __tablename__ = "payments"

    customer     = Column(String,  nullable=True)
    amount       = Column(Float,   nullable=True)
    due_date     = Column(String,  nullable=True)
    paid         = Column(String,  nullable=True)
    file_id      = Column(Integer, nullable=True, index=True)
    invoice_id   = Column(Integer, ForeignKey("invoices.id"), nullable=True, index=True)
    payment_mode = Column(String,  nullable=True)


# ---------------------------------------------------------------------------
# PURCHASE ORDER
# ---------------------------------------------------------------------------

class PurchaseOrder(Base, BusinessOwnedMixin, GSTFieldsMixin):
    """Purchase order sent to a vendor."""
    __tablename__ = "purchase_orders"

    po_number     = Column(String, index=True, nullable=True)
    vendor_id     = Column(Integer, ForeignKey("vendors.id"), nullable=True, index=True)
    vendor_name   = Column(String, nullable=True)
    po_date       = Column(String, nullable=True)
    expected_date = Column(String, nullable=True)
    received_date = Column(String, nullable=True)
    status        = Column(String, nullable=True, default="Draft")
    notes         = Column(Text,   nullable=True)

    vendor     = relationship("Vendor", back_populates="purchase_orders")
    line_items = relationship(
        "PurchaseOrderLineItem", back_populates="purchase_order",
        cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseOrderLineItem(Base, TimestampMixin):
    """One product line on a purchase order."""
    __tablename__ = "purchase_order_line_items"

    id                = Column(Integer, primary_key=True, index=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=False, index=True)
    product_id        = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)

    product_name  = Column(String, nullable=False)
    hsn_sac       = Column(String, nullable=True)
    unit          = Column(String, nullable=True, default="Nos")
    quantity      = Column(Float,  nullable=False, default=1.0)
    unit_price    = Column(Float,  nullable=False, default=0.0)
    cgst_rate     = Column(Float,  nullable=True,  default=0.0)
    sgst_rate     = Column(Float,  nullable=True,  default=0.0)
    igst_rate     = Column(Float,  nullable=True,  default=0.0)
    taxable_value = Column(Float,  nullable=True,  default=0.0)
    cgst_amount   = Column(Float,  nullable=True,  default=0.0)
    sgst_amount   = Column(Float,  nullable=True,  default=0.0)
    igst_amount   = Column(Float,  nullable=True,  default=0.0)
    line_total    = Column(Float,  nullable=True,  default=0.0)
    received_qty  = Column(Float,  nullable=True,  default=0.0)

    purchase_order = relationship("PurchaseOrder", back_populates="line_items")


# ---------------------------------------------------------------------------
# CHAT / AI  (unchanged)
# ---------------------------------------------------------------------------

class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id            = Column(Integer, primary_key=True, index=True)
    business_id   = Column(Integer, index=True)
    role          = Column(String)
    content       = Column(String)
    timestamp     = Column(DateTime, default=datetime.utcnow)
    session_id    = Column(String,  index=True, nullable=True)
    session_title = Column(String,  nullable=True)
    source        = Column(String,  nullable=True)
    model_tier    = Column(String,  nullable=True)
    cached        = Column(Boolean, default=False)


class DocumentEmbedding(Base, TimestampMixin):
    __tablename__ = "document_embeddings"

    id             = Column(Integer, primary_key=True, index=True)
    business_id    = Column(Integer, index=True)
    file_id        = Column(Integer, nullable=True, index=True)
    document_type  = Column(String)
    record_id      = Column(Integer, nullable=True)
    text_content   = Column(String)
    embedding_json = Column(String)


# ---------------------------------------------------------------------------
# OPERATIONAL / CONFIG  (unchanged)
# ---------------------------------------------------------------------------

class TokenUsage(Base, TimestampMixin):
    __tablename__ = "token_usage"

    id            = Column(Integer, primary_key=True, index=True)
    business_id   = Column(Integer, index=True)
    model         = Column(String)
    model_tier    = Column(String)
    input_tokens  = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens  = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    endpoint      = Column(String,  default="/ask")
    timestamp     = Column(DateTime, default=datetime.utcnow)


class RateLimitConfig(Base, TimestampMixin):
    __tablename__ = "rate_limit_configs"

    id                  = Column(Integer, primary_key=True, index=True)
    business_id         = Column(Integer, unique=True, index=True)
    requests_per_minute = Column(Integer, default=10)
    requests_per_day    = Column(Integer, default=500)
    max_tokens_per_day  = Column(Integer, default=50000)
    complex_per_day     = Column(Integer, default=20)
    active              = Column(Boolean, default=True)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlertConfig(Base, TimestampMixin):
    __tablename__ = "alert_configs"

    id                    = Column(Integer, primary_key=True, index=True)
    business_id           = Column(Integer, unique=True, index=True)
    business_name         = Column(String,  nullable=True)
    email                 = Column(String,  nullable=True)
    whatsapp_number       = Column(String,  nullable=True)
    alert_overdue         = Column(Boolean, default=True)
    alert_low_stock       = Column(Boolean, default=True)
    alert_expiry          = Column(Boolean, default=True)
    alert_daily_summary   = Column(Boolean, default=True)
    low_stock_threshold   = Column(Integer, default=10)
    expiry_days_threshold = Column(Integer, default=30)
    active                = Column(Boolean, default=True)
    created_at            = Column(DateTime, default=datetime.utcnow)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ActionLog(Base, TimestampMixin):
    """Audit trail for every gated agentic action."""
    __tablename__ = "action_log"

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    action      = Column(String)
    target      = Column(String, nullable=True)
    amount      = Column(Float,  nullable=True)
    detail      = Column(Text,   nullable=True)
    status      = Column(String, default="logged")
    created_at  = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# FEEDBACK / CORRECTIONS  (answer quality loop)
# ---------------------------------------------------------------------------

class Feedback(Base, TimestampMixin):
    """Append-only log of thumbs up/down on answers — every wrong answer becomes
    a labelled example for offline seed/regex tuning."""
    __tablename__ = "feedback"

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    session_id  = Column(String,  nullable=True)
    query       = Column(Text)
    route       = Column(String,  nullable=True)   # route the answer was served from
    handler_key = Column(String,  nullable=True)   # handler the answer was served from
    verdict     = Column(String)                    # 'up' | 'down'
    correction  = Column(String,  nullable=True)    # intent the user says it SHOULD be
    created_at  = Column(DateTime, default=datetime.utcnow)


class QueryOverride(Base, TimestampMixin):
    """Active per-user correction: an exact (normalized) query routes to a fixed
    intent. Applied at the top of routing so a corrected query returns the right
    answer on re-run. One row per (business_id, query_norm) — upserted."""
    __tablename__ = "query_override"
    __table_args__ = (
        UniqueConstraint("business_id", "query_norm", name="uq_query_override_biz_query"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    query_norm  = Column(String,  index=True)       # lowercased, whitespace-collapsed
    route       = Column(String)                     # DIRECT | AI_SIMPLE | AI_COMPLEX | CONVERSATIONAL
    handler_key = Column(String,  nullable=True)     # for DIRECT
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# Phase 4 — Proactive Memory
# ---------------------------------------------------------------------------

class BusinessFact(Base, TimestampMixin):
    """
    Durable, distilled business facts compiled weekly by the LLM memory job.

    Each row captures one stable pattern about a business — e.g. a customer
    who habitually pays late, a product that moves fastest on weekends, or a
    seasonal revenue dip — keyed by (business_id, fact_key).

    These facts are injected into every LLM system prompt under [Durable
    Memories] so the AI advisor can give personalised, context-aware answers
    without re-analysing history on every request.

    Lifecycle:
      • Written weekly by services.memory_service.distill_memory()
      • Read on every AI call by services.memory_service.get_business_facts()
      • Visible via GET /alerts/memory-facts (enterprise only)
    """
    __tablename__ = "business_facts"
    __table_args__ = (
        UniqueConstraint("business_id", "fact_key", name="uq_business_facts_biz_key"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True, nullable=False)
    fact_key    = Column(String,  index=True, nullable=False)   # e.g. "payment_delay_star_bazaar"
    category    = Column(String,  nullable=True)                 # e.g. "payment_delay" | "sales_pattern"
    fact_text   = Column(Text,    nullable=False)                # Human-readable sentence
    confidence  = Column(Float,   default=1.0, nullable=True)   # 0.0–1.0; low confidence facts hidden
