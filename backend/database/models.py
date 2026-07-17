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
from __future__ import annotations  # PEP 604 (X | Y) on Python 3.9 dev venvs
from services.dates import utc_now

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime,
    Boolean, Text, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from database.db import Base
# Shared mixins live in database.db (a model-free module) so core/models.py can
# inherit them too without an import cycle. Re-exported here for back-compat.
from database.db import TimestampMixin, BusinessOwnedMixin  # noqa: F401


# ---------------------------------------------------------------------------
# MIXINS
# ---------------------------------------------------------------------------

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
    # GST-mandatory + universal compatibility (Rule 46 + all business types).
    # All additive/nullable — a format uses only what applies (the template decides).
    reverse_charge  = Column(Boolean, default=False)      # Rule-46 MANDATORY field (was missing)
    is_tax_inclusive= Column(Boolean, default=False)      # retail: prices entered incl. GST (MRP)
    discount_total  = Column(Float,  nullable=True, default=0.0)  # invoice-level PRE-tax discount (reduces taxable)
    round_off       = Column(Float,  nullable=True, default=0.0)  # final rounding adjustment (₹)
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
    role          = Column(String, default="enterprise")  # enterprise|admin (owner-level) | cashier (staff)
    # Staff sub-accounts: NULL for an owner (this row IS the business); for a
    # staff login it points to the owner's user id — the business they belong to.
    parent_business_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    public_id     = Column(String, unique=True, index=True, nullable=True)  # BizID (BA-XXXXXX)
    # Business GST identity (Phase 3)
    gstin         = Column(String, nullable=True)
    phone         = Column(String, nullable=True)
    email         = Column(String, nullable=True)
    address       = Column(Text,   nullable=True)
    state_code    = Column(String, nullable=True)
    pan           = Column(String, nullable=True)
    logo          = Column(Text,   nullable=True)
    # App configuration blob — JSON-encoded key/value preferences (own naming schema)
    settings      = Column(Text,   nullable=True)
    # Per-login POS counter prefix (multi-terminal POS, plan §9.3a). Owner-assigned
    # per staff (owner defaults to "OW"); drives this account's invoice-number
    # series (C1-0001, C2-0001…) so two logins never collide. Owner-only to set.
    counter_prefix = Column(String, nullable=True)
    # Staff display/login name within the owner's business (multi-tenant staff,
    # §9.5). For a staff row this is the bare name the owner typed (e.g. "counter_1")
    # — unique only WITHIN parent_business_id, so two businesses can both have a
    # "counter_1". The global-unique `username` is auto-derived internally; staff
    # never log in by it directly (they go owner → counter dropdown). NULL for owners.
    staff_login_name = Column(String, nullable=True)
    # Premium/paid subscription flag. Cloud-sync nudges (cloud↔local sync popups)
    # and other paid capabilities are gated on this. Defaults to False (free tier).
    is_premium    = Column(Boolean, default=False, nullable=False, server_default="0")
    # Editable UPI VPA (e.g. "name@upi") for POS collection QR + invoices. Distinct
    # from `phone` — a merchant's UPI handle is often NOT number@upi.
    upi_vpa       = Column(String, nullable=True)
    # Session revocation (REVIEW_1 GAP-1): JWTs carry a `tv` claim checked against
    # this counter. Bumping it invalidates every outstanding token for the account
    # within the auth-cache TTL (~30s). Admin "force logout" bumps owner + staff.
    token_version = Column(Integer, default=0, nullable=False, server_default="0")


class DeletedBusiness(Base):
    """Tombstone for a retired business account (orphan-safety).

    Written whenever an owner account is erased (admin wipe) or re-keyed onto a
    new cloud identity (reclaim). It turns "was this account deleted?" from a
    guess — previously inferred from a signup 400 or a reconcile "Identity
    mismatch" — into a recorded fact any device or the cloud can consult.

    Deliberately standalone: no foreign keys, so recording a tombstone can never
    block or fail a delete, and the tombstone survives after the owning row is
    gone. Purely additive.
    """
    __tablename__ = "deleted_businesses"

    id            = Column(Integer, primary_key=True, index=True)
    public_id     = Column(String, index=True, nullable=True)   # retired BizID (BA-XXXXXX)
    username      = Column(String, index=True, nullable=True)   # freed owner username
    business_name = Column(String, nullable=True)
    reason        = Column(String, nullable=True)               # 'admin_wipe' | 'reclaim_rekey'
    deleted_at    = Column(DateTime, default=utc_now, nullable=False)


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
    price_tier   = Column(String, nullable=True, default="standard")

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
    purchase_invoices = relationship("PurchaseInvoice", back_populates="supplier_ref", lazy="dynamic")


# ---------------------------------------------------------------------------
# PRODUCT  (catalogue)
# ---------------------------------------------------------------------------

class Product(Base, BusinessOwnedMixin):
    """Product/service catalogue. HSN and default tax rates auto-populate line items."""
    __tablename__ = "products"

    name          = Column(String, index=True)
    description   = Column(Text,   nullable=True)
    hsn_sac       = Column(String, nullable=True, index=True)
    unit          = Column(String, nullable=True, default="Nos")   # stock/sale UoM
    barcode       = Column(String, nullable=True, index=True)       # primary/display code (see ProductBarcode)
    selling_price = Column(Float,  nullable=True, default=0.0)
    wholesale_price = Column(Float,  nullable=True, default=0.0)
    distributor_price = Column(Float,  nullable=True, default=0.0)
    cost_price    = Column(Float,  nullable=True, default=0.0)
    mrp           = Column(Float,  nullable=True)
    cgst_rate     = Column(Float,  nullable=True, default=0.0)
    sgst_rate     = Column(Float,  nullable=True, default=0.0)
    igst_rate     = Column(Float,  nullable=True, default=0.0)
    is_service    = Column(Boolean, default=False)
    is_active     = Column(Boolean, default=True)

    # ── Universal item-master fields (ERPNext-style) — make the catalogue fit
    #    EVERY business type. All additive/nullable; a format uses only what it needs.
    sku             = Column(String,  nullable=True, index=True)   # item code / internal SKU (≠ barcode)
    brand           = Column(String,  nullable=True)
    manufacturer    = Column(String,  nullable=True)
    category        = Column(String,  nullable=True, index=True)
    track_inventory = Column(Boolean, default=True)               # services / prepared food → False
    price_includes_tax = Column(Boolean, default=False)           # retail MRP-inclusive pricing
    purchase_unit   = Column(String,  nullable=True)              # e.g. "Carton" (buy unit)
    conversion_factor = Column(Float, nullable=True, default=1.0) # stock units per purchase unit (carton→pcs)
    variant_of      = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)  # garments size/colour
    attributes      = Column(Text,    nullable=True)              # JSON escape-hatch: size/colour, drug-schedule,
                                                                  # IMEI, fabric, table-no… any vertical field,
                                                                  # NO migration needed to add a vertical

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
    godown_id    = Column(Integer, nullable=True, index=True)

    # Payment tracking
    paid_amount  = Column(Float,  nullable=True, default=0.0)
    payment_date = Column(String, nullable=True)
    payment_mode = Column(String, nullable=True)
    notes        = Column(Text,   nullable=True)

    # POST-tax cash discount / round-off (R4) — sales-only, so it lives on Invoice
    # (NOT the shared GSTFieldsMixin). Reduces the payable, never the taxable/GST.
    cash_discount = Column(Float, nullable=True, default=0.0)

    # Invoice-template system (plan Phase 1): stored display-title override
    # ("Tax Invoice" | "Bill of Supply" | "Estimate" | …). NULL → derived at
    # render time by core/billing/print_payload.py. Presentation-only.
    invoice_title = Column(String, nullable=True)

    # Shift & cash-drawer management (plan Phase 3): links every counter sale to
    # the register shift it was rung under. Nullable — historical invoices and
    # non-counter flows (imports, B2B) carry NULL.
    shift_id = Column(Integer, ForeignKey("register_shifts.id"), nullable=True, index=True)

    # Public share link (plan Phase 4): unguessable token for Trust Ledger.
    uid_token = Column(String, unique=True, index=True, nullable=True, default=lambda: str(uuid.uuid4()))

    # Per-invoice template override (plan Phase 4): e.g. "classic_a4", overrides business default
    print_template = Column(String, nullable=True)

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
    uid           = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
    invoice_id    = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    product_id    = Column(Integer, ForeignKey("products.id"), nullable=True,  index=True)

    product_name  = Column(String, nullable=False)
    description   = Column(Text,   nullable=True)                  # extra line description (GST allows)
    hsn_sac       = Column(String, nullable=True)
    unit          = Column(String, nullable=True, default="Nos")
    quantity      = Column(Float,  nullable=False, default=1.0)
    unit_price    = Column(Float,  nullable=False, default=0.0)
    discount      = Column(Float,  nullable=True,  default=0.0)
    discount_pct  = Column(Float,  nullable=True,  default=0.0)
    batch_no      = Column(String, nullable=True)                  # pharma/perishable at point of sale
    serial_no     = Column(String, nullable=True)                  # electronics/IMEI tracking
    # Invoice-template system (plan Phase 1) — sale-time snapshots so historical
    # invoices print exactly what was sold. All nullable/additive.
    mrp           = Column(Float,  nullable=True)                  # MRP at sale time (retail/pharma column)
    expiry_date   = Column(String, nullable=True)                  # expiry at sale time (pharma column)
    attributes    = Column(Text,   nullable=True)                  # JSON snapshot of vertical fields (size/color/warranty…)

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
    godown_id     = Column(Integer, nullable=True, index=True)

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

class LegacyPayment(Base, BusinessOwnedMixin):
    """Legacy payment records from CSV imports."""
    __tablename__ = "payments"

    customer     = Column(String,  nullable=True)
    amount       = Column(Float,   nullable=True)
    due_date     = Column(String,  nullable=True)
    paid         = Column(String,  nullable=True)
    file_id      = Column(Integer, nullable=True, index=True)
    invoice_id   = Column(Integer, ForeignKey("invoices.id"), nullable=True, index=True)
    payment_mode = Column(String,  nullable=True)
    # Shift & cash-drawer management (plan Phase 3) — see Invoice.shift_id.
    shift_id     = Column(Integer, ForeignKey("register_shifts.id"), nullable=True, index=True)


# ---------------------------------------------------------------------------
# REGISTER SHIFT  (shift & cash-drawer management, plan Phase 3)
# ---------------------------------------------------------------------------

class RegisterShift(Base, BusinessOwnedMixin):
    """
    One cashier session at the register: opened with a counted cash float,
    closed with counted cash/UPI tallied against the system's expectation.

    Rules:
      • ONE OPEN shift per user at a time (enforced in routes/shifts.py).
      • EVERY counter sale requires an open shift — all roles, including the
        owner (single-operator businesses need day-wise accounting too).
      • APPEND-ONLY: a closed shift is never reopened or edited; corrections
        are notes on the next shift.

    PK follows codebase convention (Integer id + uuid `uid`) rather than a raw
    UUID PK, so the sync layer treats it like every other business table.
    """
    __tablename__ = "register_shifts"

    # The operator (staff or owner user id) — NOT the business id; that's
    # `business_id` from BusinessOwnedMixin.
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    start_time   = Column(DateTime, nullable=False, default=utc_now)
    end_time     = Column(DateTime, nullable=True)

    opening_cash = Column(Float, nullable=False, default=0.0)
    # Float carry-forward (Shopify-style): the suggested opening at open time
    # (= previous shift's closing_float). Stored so an operator editing the
    # prefill leaves an auditable opening variance. NULL = no prior shift.
    opening_expected = Column(Float, nullable=True)

    # Snapshotted at close (expected = opening + system-recorded takings).
    closing_cash_expected = Column(Float, nullable=True)
    closing_cash_actual   = Column(Float, nullable=True)
    closing_upi_expected  = Column(Float, nullable=True)
    closing_upi_actual    = Column(Float, nullable=True)
    # What was LEFT IN THE DRAWER at close (≤ counted cash) — becomes the next
    # shift's suggested opening float; the removed remainder is recorded as a
    # closing_removal cash movement (bank deposit / owner withdrawal).
    closing_float = Column(Float, nullable=True)

    status = Column(String, nullable=False, default="OPEN", index=True)  # OPEN | CLOSED
    notes  = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_register_shifts_biz_status", "business_id", "status"),
        Index("ix_register_shifts_user_status", "user_id", "status"),
    )


class ShiftCashMovement(Base, BusinessOwnedMixin):
    """
    One non-sale cash movement in/out of the drawer during a shift — the
    Square "Paid In / Paid Out" & Lightspeed "Cash In/Out, Petty Cash" model.
    APPEND-ONLY: corrections are opposite movements, never edits.

    movement_type: paid_in | paid_out
    category:
      paid_in  → change_top_up   (cash added to make change)
      paid_out → bank_deposit | expense | owner_withdrawal
      system   → opening_variance (prefilled float edited at open — audit only,
                 NEVER enters the tally: the entered opening cash is the truth),
                 closing_removal  (cash taken out at close, after the count —
                 audit only: the close snapshot already happened)
    """
    __tablename__ = "shift_cash_movements"

    shift_id      = Column(Integer, ForeignKey("register_shifts.id"), nullable=False, index=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    movement_type = Column(String, nullable=False)               # paid_in | paid_out
    category      = Column(String, nullable=False)
    amount        = Column(Float,  nullable=False)               # always positive
    note          = Column(Text,   nullable=True)
    # When category='expense', the auto-created Expense row (books link).
    expense_id    = Column(Integer, ForeignKey("expenses.id"), nullable=True, index=True)

    __table_args__ = (
        Index("ix_shift_cash_movements_shift", "business_id", "shift_id"),
    )


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
    uid               = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
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
# PURCHASE INVOICE (RECEIVED BILLS)
# ---------------------------------------------------------------------------

class PurchaseInvoice(Base, BusinessOwnedMixin, GSTFieldsMixin):
    """Received supplier invoice / purchase bill."""
    __tablename__ = "purchase_invoices"

    id             = Column(Integer, primary_key=True, index=True)
    supplier_id    = Column(Integer, ForeignKey("vendors.id"), nullable=True, index=True)
    supplier_name  = Column(String, nullable=True)
    invoice_number = Column(String, index=True, nullable=True)
    invoice_date   = Column(String, nullable=True)
    due_date       = Column(String, nullable=True)
    status         = Column(String, nullable=True, default="Pending")
    notes          = Column(Text,   nullable=True)
    file_id        = Column(Integer, nullable=True, index=True)
    godown_id      = Column(Integer, nullable=True, index=True)

    supplier_ref   = relationship("Vendor", back_populates="purchase_invoices", foreign_keys=[supplier_id])
    line_items     = relationship(
        "PurchaseInvoiceLineItem", back_populates="purchase_invoice",
        cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_purchase_invoice_business_status", "business_id", "status"),
        Index("ix_purchase_invoice_business_date",   "business_id", "invoice_date"),
    )


class PurchaseInvoiceLineItem(Base, TimestampMixin):
    """One product line on a purchase invoice."""
    __tablename__ = "purchase_invoice_line_items"

    id                  = Column(Integer, primary_key=True, index=True)
    uid                 = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
    purchase_invoice_id = Column(Integer, ForeignKey("purchase_invoices.id"), nullable=False, index=True)
    product_id          = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)

    product_name      = Column(String, nullable=False)
    hsn_sac           = Column(String, nullable=True)
    unit              = Column(String, nullable=True, default="Nos")
    quantity          = Column(Float,  nullable=False, default=1.0)
    purchase_unit     = Column(String, nullable=True)
    conversion_factor = Column(Float,  nullable=False, default=1.0)
    unit_price        = Column(Float,  nullable=False, default=0.0)
    cgst_rate         = Column(Float,  nullable=True,  default=0.0)
    sgst_rate         = Column(Float,  nullable=True,  default=0.0)
    igst_rate         = Column(Float,  nullable=True,  default=0.0)
    taxable_value     = Column(Float,  nullable=True,  default=0.0)
    cgst_amount       = Column(Float,  nullable=True,  default=0.0)
    sgst_amount       = Column(Float,  nullable=True,  default=0.0)
    igst_amount       = Column(Float,  nullable=True,  default=0.0)
    line_total        = Column(Float,  nullable=True,  default=0.0)
    batch             = Column(String, nullable=True)
    expiry            = Column(String, nullable=True)
    confidence_score  = Column(Float,  nullable=True,  default=1.0)
    is_matched        = Column(Boolean, default=True)

    purchase_invoice   = relationship("PurchaseInvoice", back_populates="line_items")
    product_ref        = relationship("Product", foreign_keys=[product_id])


# ---------------------------------------------------------------------------
# CHAT / AI  (unchanged)
# ---------------------------------------------------------------------------

class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id            = Column(Integer, primary_key=True, index=True)
    business_id   = Column(Integer, index=True)
    role          = Column(String)
    content       = Column(String)
    timestamp     = Column(DateTime, default=utc_now)
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
    timestamp     = Column(DateTime, default=utc_now)


class RateLimitConfig(Base, TimestampMixin):
    __tablename__ = "rate_limit_configs"

    id                  = Column(Integer, primary_key=True, index=True)
    uid                 = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
    business_id         = Column(Integer, unique=True, index=True)
    requests_per_minute = Column(Integer, default=10)
    requests_per_day    = Column(Integer, default=500)
    max_tokens_per_day  = Column(Integer, default=50000)
    complex_per_day     = Column(Integer, default=20)
    active              = Column(Boolean, default=True)
    updated_at          = Column(DateTime, default=utc_now, onupdate=utc_now)


class AlertConfig(Base, TimestampMixin):
    __tablename__ = "alert_configs"

    id                    = Column(Integer, primary_key=True, index=True)
    uid                   = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
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
    created_at            = Column(DateTime, default=utc_now)
    updated_at            = Column(DateTime, default=utc_now, onupdate=utc_now)


class ActionLog(Base, TimestampMixin):
    """Audit trail for every gated agentic action."""
    __tablename__ = "action_logs"

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    action      = Column(String)
    target      = Column(String, nullable=True)
    amount      = Column(Float,  nullable=True)
    detail      = Column(Text,   nullable=True)
    status      = Column(String, default="logged")
    created_at  = Column(DateTime, default=utc_now)


# ---------------------------------------------------------------------------
# FEEDBACK / CORRECTIONS  (answer quality loop)
# ---------------------------------------------------------------------------

class AIFeedback(Base, TimestampMixin):
    """Append-only log of thumbs up/down on answers — every wrong answer becomes
    a labelled example for offline seed/regex tuning."""
    __tablename__ = "ai_feedback"

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    session_id  = Column(String,  nullable=True)
    query       = Column(Text)
    route       = Column(String,  nullable=True)   # route the answer was served from
    handler_key = Column(String,  nullable=True)   # handler the answer was served from
    verdict     = Column(String)                    # 'up' | 'down'
    correction  = Column(String,  nullable=True)    # intent the user says it SHOULD be
    created_at  = Column(DateTime, default=utc_now)


class AIQueryOverride(Base, TimestampMixin):
    """Active per-user correction: an exact (normalized) query routes to a fixed
    intent. Applied at the top of routing so a corrected query returns the right
    answer on re-run. One row per (business_id, query_norm) — upserted."""
    __tablename__ = "ai_query_overrides"
    __table_args__ = (
        UniqueConstraint("business_id", "query_norm", name="uq_ai_query_overrides_biz_query"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True)
    query_norm  = Column(String,  index=True)       # lowercased, whitespace-collapsed
    route       = Column(String)                     # DIRECT | AI_SIMPLE | AI_COMPLEX | CONVERSATIONAL
    handler_key = Column(String,  nullable=True)     # for DIRECT
    created_at  = Column(DateTime, default=utc_now)
    updated_at  = Column(DateTime, default=utc_now, onupdate=utc_now)


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


# ---------------------------------------------------------------------------
# CORE (BILLING ECOSYSTEM) TABLES — defined in core/models.py
# ---------------------------------------------------------------------------
# The billing ecosystem owns its own tables (StockLedger, ProductBarcode,
# BusinessSettings, …) and defines them in `core/models.py` so the schema is
# organised by domain. They register on this SAME shared `Base` (one database,
# one metadata — a modular monolith, not separate DBs), so a sale can write
# shared `Invoice`/`InvoiceLineItem` and core `StockLedger` in one atomic
# transaction. This import at the bottom (after the mixins/shared models above)
# pulls them in so the tables register on `Base.metadata` whenever the shared
# models are loaded, and keeps `from database.models import StockLedger` working.
from core.models import (  # noqa: E402,F401
    StockLedger, ProductBarcode, BusinessSettings, InvoicePayment, IdempotencyKey,
    B2BConnection, B2BInviteCode, B2BOrder, B2BOrderLineItem, B2BLedger,
    Expense, Godown, StockTransfer, StockTransferLineItem,
    JournalEntry, JournalLine, PeriodLock,
)


# ---------------------------------------------------------------------------
# SYNC ENGINE MODELS & EVENT HOOKS (Phase 2)
# ---------------------------------------------------------------------------

class SyncQueue(Base):
    __tablename__ = "sync_queue"

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True, nullable=True)
    entity      = Column(String, index=True, nullable=False)        # table name, e.g. 'invoices'
    entity_id   = Column(Integer, index=True, nullable=False)       # primary key of target
    operation   = Column(String, nullable=False)                    # 'INSERT', 'UPDATE', 'DELETE'
    payload     = Column(Text, nullable=True)                       # JSON serialized columns
    created_at  = Column(DateTime, default=utc_now, nullable=False)
    synced_at   = Column(DateTime, nullable=True)
    error       = Column(Text, nullable=True)


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id          = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, index=True, nullable=True)
    entity      = Column(String, nullable=True)
    entity_id   = Column(Integer, nullable=True)
    operation   = Column(String, nullable=True)
    synced_at   = Column(DateTime, default=utc_now, nullable=False)
    status      = Column(String, nullable=False)                    # 'success', 'failed'
    error       = Column(Text, nullable=True)


class ConflictLog(Base):
    __tablename__ = "conflict_logs"

    id               = Column(Integer, primary_key=True, index=True)
    business_id      = Column(Integer, index=True, nullable=True)
    entity           = Column(String, index=True, nullable=False)
    entity_id        = Column(Integer, index=True, nullable=False)
    local_updated_at = Column(DateTime, nullable=True)
    cloud_updated_at = Column(DateTime, nullable=True)
    local_payload    = Column(Text, nullable=True)
    cloud_payload    = Column(Text, nullable=True)
    resolved_at      = Column(DateTime, nullable=True)
    resolution       = Column(String, nullable=True)                # 'local_won', 'cloud_won', 'merged'


_SYNC_TABLES = {
    "businesses",
    "users",
    "customers",
    "vendors",
    "products",
    "invoices",
    "purchase_invoices",
    "purchase_orders",
    "invoice_line_items",
    "purchase_invoice_line_items",
    "purchase_order_line_items",
    "alert_configs",
    "rate_limit_configs",
    "business_settings",
    "payments",
    "invoice_payments",
    "inventory",
    "stock_ledger",
    "product_barcodes",
    "godowns",
    "expenses",
    "stock_transfers",
    "stock_transfer_line_items",
    "b2b_ledgers",
    "table_alterations",
    # register_shifts is the PARENT of invoices/invoice_payments (shift_id FK).
    # It was present in the apply-side MODEL_MAP but missing here, so shift rows
    # were never enqueued/pushed — leaving their child invoices perpetually
    # deferred on the cloud ("parent register_shifts … not in this DB yet") and
    # the outbox stuck at "N pending". Enqueue shifts (and their cash movements)
    # so children can resolve their parent and drain.
    "register_shifts",
    "shift_cash_movements",
}


from sqlalchemy import event, text
from sqlalchemy.orm import Mapper
import json

def _serialize_orm_obj(obj, connection=None) -> dict:
    d = {}
    for column in obj.__table__.columns:
        val = getattr(obj, column.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[column.name] = val

    if connection is not None:
        for fk in obj.__table__.foreign_keys:
            parent_col_name = fk.parent.name
            parent_val = getattr(obj, parent_col_name)
            if parent_val is not None:
                parent_table_name = fk.column.table.name
                try:
                    row = connection.execute(
                        text(f'SELECT uid FROM "{parent_table_name}" WHERE "{fk.column.name}" = :id'),
                        {"id": parent_val}
                    ).fetchone()
                    if row and row[0]:
                        uid_str = str(row[0])
                        d[f"{parent_col_name}_uid"] = uid_str
                        if parent_col_name.endswith("_id"):
                            base_name = parent_col_name[:-3]
                            d[f"{base_name}_uid"] = uid_str
                except Exception:
                    pass
    return d

def _get_business_id(obj) -> int | None:
    bid = getattr(obj, "business_id", None)
    if bid is not None:
        try:
            return int(bid)
        except (ValueError, TypeError):
            pass
    if obj.__tablename__ == "users":
        return obj.parent_business_id or obj.id
    return None

def _queue_change(connection, target, operation):
    from database.db import sync_disabled_var
    # 1. Skip if sync is disabled (e.g. during pull updates)
    if sync_disabled_var.get() == True:
        return
    # 2. Skip tracking tables
    tbl = target.__tablename__
    if tbl in ("sync_queue", "sync_logs", "conflict_logs"):
        return
    # 3. Only sync tables in our export/sync set
    if tbl not in _SYNC_TABLES:
        return
    
    # 4. Only queue if dialect is sqlite (local client)
    if connection.dialect.name != "sqlite":
        return

    bid = _get_business_id(target)
    if bid is None:
        return

    # Check if hybrid mode is configured for this specific business ID.
    try:
        res = connection.execute(
            text("SELECT parent_business_id, settings FROM users WHERE id = :bid"),
            {"bid": bid}
        ).fetchone()
        
        if not res:
            return
            
        parent_id, settings_str = res[0], res[1]
        
        # If parent_business_id is set, settings are on the parent owner's user record
        if parent_id is not None:
            res_parent = connection.execute(
                text("SELECT settings FROM users WHERE id = :parent_id"),
                {"parent_id": parent_id}
            ).fetchone()
            if res_parent:
                settings_str = res_parent[0]
                
        if not settings_str:
            return
            
        s = json.loads(settings_str)
        if s.get("general", {}).get("hosting_mode") != "hybrid":
            return
    except Exception:
        # users table might not exist yet during initial DB creation/seeds, or query failed
        return

    # 5. Extract values and queue it
    entity_id = getattr(target, "id", None)
    if entity_id is None:
        pks = target.__table__.primary_key.columns.keys()
        if pks:
            entity_id = getattr(target, pks[0], None)

    if entity_id is None:
        return

    payload = None
    if operation != "DELETE":
        try:
            payload = json.dumps(_serialize_orm_obj(target, connection), default=str)
        except Exception:
            pass
    else:
        try:
            payload = json.dumps({"id": entity_id, "business_id": bid}, default=str)
        except Exception:
            pass

    # Insert into sync_queue using connection
    try:
        connection.execute(
            text(
                "INSERT INTO sync_queue (business_id, entity, entity_id, operation, payload, created_at) "
                "VALUES (:business_id, :entity, :entity_id, :operation, :payload, :created_at)"
            ),
            {
                "business_id": bid,
                "entity": tbl,
                "entity_id": entity_id,
                "operation": operation,
                "payload": payload,
                "created_at": utc_now()
            }
        )
    except Exception as e:
        # Fail silently to prevent blocking main database writes
        pass


@event.listens_for(Mapper, "after_insert")
def handle_after_insert(mapper, connection, target):
    _queue_change(connection, target, "INSERT")


@event.listens_for(Mapper, "after_update")
def handle_after_update(mapper, connection, target):
    _queue_change(connection, target, "UPDATE")


@event.listens_for(Mapper, "after_delete")
def handle_after_delete(mapper, connection, target):
    _queue_change(connection, target, "DELETE")
# (sync-touch)

# ── USER FEEDBACK ────────────────────────────────────────────────────────────

class UserFeedback(Base):
    """User submitted support feedback and issues."""
    __tablename__ = "user_feedback"

    id            = Column(Integer, primary_key=True, index=True)
    business_id   = Column(Integer, index=True)
    username      = Column(String, nullable=True)
    message       = Column(Text)
    log_file_path = Column(String, nullable=True)
    created_at    = Column(DateTime, default=utc_now)


# ── CAMPAIGNS / ANNOUNCEMENTS / OFFERS (Admin Console growth half) ──────────
# REVIEW_1 §4.3: admin-authored promotions delivered in-app (channel "in_app"
# ships first; "email"/"whatsapp" ride on the notifier when those land).
# Cloud-only tables — written via /admin/* (ADMIN_API_ENABLED gate) and read
# by merchants through GET /announcements. Never part of merchant sync.

class Campaign(Base):
    """One promotion/announcement authored in the Admin Console."""
    __tablename__ = "campaigns"

    id            = Column(Integer, primary_key=True, index=True)
    title         = Column(String, nullable=False)
    body_md       = Column(Text,   nullable=False)             # markdown body
    channel       = Column(String, nullable=False, default="in_app")  # in_app|email|whatsapp
    # Audience filter JSON: {"plans": ["free","pro"], "business_types": [...],
    #                        "bizids": ["BA-XXXXXX", ...]}  — empty/missing = everyone
    audience      = Column(Text,   nullable=True)
    # Optional attached offer code (rendered as a redeem button in the client)
    offer_code    = Column(String, nullable=True)
    status        = Column(String, nullable=False, default="draft")   # draft|active|paused|done
    starts_at     = Column(DateTime, nullable=True)
    ends_at       = Column(DateTime, nullable=True)
    created_by    = Column(String, nullable=True)              # admin username
    created_at    = Column(DateTime, default=utc_now)
    updated_at    = Column(DateTime, default=utc_now, onupdate=utc_now)


class CampaignDelivery(Base):
    """Per-business delivery/engagement record — powers the campaign funnel
    (delivered → seen → clicked/dismissed) in the Admin Console."""
    __tablename__ = "campaign_deliveries"
    __table_args__ = (
        UniqueConstraint("campaign_id", "business_id", name="uq_campaign_delivery"),
    )

    id            = Column(Integer, primary_key=True, index=True)
    campaign_id   = Column(Integer, ForeignKey("campaigns.id"), index=True, nullable=False)
    business_id   = Column(Integer, index=True, nullable=False)
    delivered_at  = Column(DateTime, default=utc_now)
    seen_at       = Column(DateTime, nullable=True)
    clicked_at    = Column(DateTime, nullable=True)
    dismissed_at  = Column(DateTime, nullable=True)


class Offer(Base):
    """Redeemable offer code. `effect` describes what redemption grants —
    v1: {"plan": "pro", "days": 30}. Applied through the same
    users.settings.subscription machinery the Admin Console uses."""
    __tablename__ = "offers"

    id              = Column(Integer, primary_key=True, index=True)
    code            = Column(String, unique=True, index=True, nullable=False)
    description     = Column(String, nullable=True)
    effect          = Column(Text,   nullable=False)           # JSON effect payload
    max_redemptions = Column(Integer, nullable=True)           # NULL = unlimited
    redeemed_count  = Column(Integer, nullable=False, default=0, server_default="0")
    redeem_by       = Column(DateTime, nullable=True)          # NULL = no deadline
    active          = Column(Boolean, nullable=False, default=True, server_default="1")
    created_by      = Column(String, nullable=True)
    created_at      = Column(DateTime, default=utc_now)


class OfferRedemption(Base):
    """Who redeemed what, when — audit + max_redemptions enforcement."""
    __tablename__ = "offer_redemptions"
    __table_args__ = (
        UniqueConstraint("offer_id", "business_id", name="uq_offer_redemption_once"),
    )

    id           = Column(Integer, primary_key=True, index=True)
    offer_id     = Column(Integer, ForeignKey("offers.id"), index=True, nullable=False)
    business_id  = Column(Integer, index=True, nullable=False)
    redeemed_at  = Column(DateTime, default=utc_now)


# ── TABLE ALTERATION AUDITING ───────────────────────────────────────────────

class TableAlteration(Base):
    """Audit log of database table insertions, updates, and deletions by users."""
    __tablename__ = "table_alterations"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, nullable=True)
    username    = Column(String, nullable=True)
    business_id = Column(Integer, nullable=True)
    table_name  = Column(String, index=True)
    action      = Column(String)  # INSERT, UPDATE, DELETE
    record_id   = Column(String, nullable=True)
    old_values  = Column(Text, nullable=True)  # JSON-serialized old values
    new_values  = Column(Text, nullable=True)  # JSON-serialized new values
    created_at  = Column(DateTime, default=utc_now)
    # Step 3 durable UID for cross-DB sync
    uid         = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))


from sqlalchemy.orm import Session
from sqlalchemy import inspect
import json

EXCLUDED_TABLES = {
    "table_alterations", "action_log", "action_logs", "token_usage",
    "chat_messages", "document_embeddings", "alembic_version",
    "uploaded_files", "sync_queue", "sync_logs", "conflict_logs",
    "telemetry_events",
    # Campaign system data — high-churn, admin-owned, not business books
    "campaigns", "campaign_deliveries", "offers", "offer_redemptions",
}

def serialize_val(val):
    if val is None:
        return None
    from datetime import datetime, date
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, (int, float, str, bool)):
        return val
    return str(val)

@event.listens_for(Session, "before_flush")
def audit_before_flush(session, flush_context, instances):
    # Retrieve context variables
    from database.db import current_user_id_var, current_username_var, current_business_id_var
    user_id = current_user_id_var.get()
    username = current_username_var.get()
    business_id = current_business_id_var.get()

    pending = getattr(session, "_pending_audits", None)
    if pending is None:
        pending = []
        session._pending_audits = pending

    # Track inserts
    for obj in session.new:
        tbl = getattr(obj, "__tablename__", None)
        if not tbl or tbl in EXCLUDED_TABLES:
            continue
        new_vals = {}
        for col in obj.__table__.columns:
            val = getattr(obj, col.name, None)
            new_vals[col.name] = serialize_val(val)
        pending.append({
            "action": "INSERT",
            "table_name": tbl,
            "obj": obj,
            "old_values": None,
            "new_values": json.dumps(new_vals),
            "user_id": user_id,
            "username": username,
            "business_id": business_id or getattr(obj, "business_id", None)
        })

    # Track updates
    for obj in session.dirty:
        if not session.is_modified(obj):
            continue
        tbl = getattr(obj, "__tablename__", None)
        if not tbl or tbl in EXCLUDED_TABLES:
            continue
        
        old_vals = {}
        new_vals = {}
        state = inspect(obj)
        for attr in state.attrs:
            if attr.history.has_changes():
                col_name = attr.key
                old_val = attr.history.deleted[0] if attr.history.deleted else None
                new_val = attr.value
                old_vals[col_name] = serialize_val(old_val)
                new_vals[col_name] = serialize_val(new_val)
                
        if old_vals:
            pending.append({
                "action": "UPDATE",
                "table_name": tbl,
                "obj": obj,
                "old_values": json.dumps(old_vals),
                "new_values": json.dumps(new_vals),
                "user_id": user_id,
                "username": username,
                "business_id": business_id or getattr(obj, "business_id", None)
            })

    # Track deletes
    for obj in session.deleted:
        tbl = getattr(obj, "__tablename__", None)
        if not tbl or tbl in EXCLUDED_TABLES:
            continue
        old_vals = {}
        for col in obj.__table__.columns:
            val = getattr(obj, col.name, None)
            old_vals[col.name] = serialize_val(val)
        pending.append({
            "action": "DELETE",
            "table_name": tbl,
            "obj": obj,
            "old_values": json.dumps(old_vals),
            "new_values": None,
            "user_id": user_id,
            "username": username,
            "business_id": business_id or getattr(obj, "business_id", None)
        })

@event.listens_for(Session, "after_flush")
def audit_after_flush(session, flush_context):
    pending = getattr(session, "_pending_audits", None)
    if not pending:
        return
    
    session._pending_audits = []
    
    for item in pending:
        obj = item.pop("obj")
        pk = inspect(obj).identity
        record_id = str(pk[0]) if pk else None
        
        # Insert raw SQL directly on the connection to prevent session flushes recursive loops
        connection = session.connection()
        connection.execute(
            text(
                "INSERT INTO table_alterations (user_id, username, business_id, table_name, action, record_id, old_values, new_values, created_at, uid) "
                "VALUES (:user_id, :username, :business_id, :table_name, :action, :record_id, :old_values, :new_values, :created_at, :uid)"
            ),
            {
                "user_id": item["user_id"],
                "username": item["username"],
                "business_id": item["business_id"],
                "table_name": item["table_name"],
                "action": item["action"],
                "record_id": record_id,
                "old_values": item["old_values"],
                "new_values": item["new_values"],
                "created_at": utc_now(),
                "uid": str(uuid.uuid4())
            }
        )
