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
    # ── BizID — THE ONLY BUSINESS IDENTIFIER THAT MAY CROSS A DATABASE ──────
    #
    # `id` above is a per-database integer. The same business is `7` locally and
    # `42` on the cloud, by design — rows are created independently on each side,
    # so their autoincrement ids cannot agree. `public_id` is the same string
    # everywhere and is what payloads, URLs, registry keys, uploaded filenames
    # and replicated columns must carry.
    #
    # Full rule, the three defects that came from breaking it, and the pattern
    # that is correct: see core/identity.py.
    #
    # Owners only. A staff row must NOT have one — `_backfill_biz_ids` used to
    # give every cashier a BizID, which made 32 staff read as separate
    # businesses to every per-business sweep.
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
    # Stamped on every successful authentication. NULL means this account has
    # NEVER been used to log in — which is the only reliable way to tell a real
    # counter from one created during testing and forgotten. Without it, the
    # Staff Management screen showed a name, a role and nothing else, so 22
    # abandoned accounts sat indistinguishable from the 2 real ones.
    last_login    = Column(DateTime, nullable=True)


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
    # Advance/credit the customer has on account (e.g. an overpayment from a
    # lump-sum settlement). Auto-applied to the next sale invoice.
    credit_balance = Column(Float, nullable=True, default=0.0)
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
    customer_id       = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    godown_id         = Column(Integer, nullable=True, index=True)
    parent_invoice_id = Column(Integer, ForeignKey("invoices.id"),  nullable=True, index=True)  # link credit note → sale

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
    returned_qty  = Column(Float,  nullable=True,  default=0.0, server_default="0.0")    # cumulative returned quantity (§3 return limit enforcement)
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
    # Quantity is fractional for weight/length/volume based products. The stock
    # ledger already stores a Float; keeping this rebuildable projection as an
    # Integer silently rounded the value used by inventory valuation reports.
    stock         = Column(Float,   nullable=True)
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
    parent_invoice_id = Column(Integer, ForeignKey("purchase_invoices.id"), nullable=True, index=True)  # link debit note → purchase

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
    returned_qty      = Column(Float,  nullable=True,  default=0.0, server_default="0.0")    # cumulative returned quantity (§3 return limit enforcement)
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

    # ── Per-row backoff — the outbox half of what `sync_inbox` already had ────
    # A DEFERRED row keeps `synced_at = NULL` on purpose (M-20: a deferral is not
    # a rejection) and was therefore re-sent on EVERY cycle, forever, with no
    # counter and no delay. Measured 2026-08-04 on the local DB: 31 pending rows
    # against 13 distinct targets — the same three rows re-queued 7 times each
    # over one day, because a deferred child is re-queued by the heal scan while
    # its parent never arrives.
    #
    # Two costs. Every cycle spends its push budget re-sending rows the cloud has
    # already refused; and the drain window is `ORDER BY id LIMIT 100`, so once
    # stuck rows fill it, nothing else for that business ever syncs again. The
    # queue was on a path to that, not at it — which is why this is backoff, not
    # a bigger rescue.
    #
    # `attempts` is NOT reset when a row is re-queued with a fresher payload: the
    # re-queue is the symptom of the stall, so letting it reset the timer would
    # defeat the backoff entirely.
    # `server_default` as well as `default`, and not for symmetry: rows reach
    # this table by raw `INSERT INTO sync_queue (...)` from the ORM event, not
    # through the mapper, so a Python-side default never fires for them. The
    # migration's `ADD COLUMN attempts INTEGER DEFAULT 0` gives an existing
    # database the server default; without this line a table built fresh by
    # `create_all` would have `NOT NULL` and no default, and every raw enqueue
    # that omitted the column would fail the constraint.
    attempts        = Column(Integer, default=0, server_default="0", nullable=False)
    next_attempt_at = Column(DateTime, index=True, nullable=True)


class SyncInbox(Base):
    """The PULL-side counterpart of ``sync_queue`` — rows the cloud sent that
    this database could not apply yet.

    WHY THIS TABLE EXISTS
    ---------------------
    Push has an outbox: a row that cannot be delivered STAYS queued, is visible
    in Ops, and is retried independently of every other row. Pull had no such
    thing, and paid for it twice:

    1. **Deferred rows were dropped.** ``resolve_parent_fk_uids`` returns True
       when a child's parent is not local yet, and its documented contract is
       that the row "re-applies on a later sync once the parent lands". The
       pull-apply loop honoured the deferral with a bare ``continue`` — no record
       anywhere. Because nothing was recorded, the cursor advanced, and the cloud
       never re-offered the row (its ``updated_at`` had not changed). The row was
       gone.

       This is M-20 exactly, on the read side. The push side's own comment
       describes the identical failure it had already fixed: *"the row is
       DEFERRED, the client MUST be told … The outbox row was gone, so the
       'later sync' could never happen."*

    2. **A rejected row froze everything behind it.** The only recovery
       mechanism was to HOLD the global pull cursor, which blocks all 29 tables,
       bounded by ``_PULL_MAX_FAILED_STREAK`` — after which the row was abandoned
       with a CRITICAL log saying it "needs a human". That is a forced choice
       between stalling every later row and losing this one. Push never faces
       that choice, because a stuck outbox row waits its turn while the rest
       drains.

    With an inbox, the cursor can ALWAYS advance: a row that cannot apply is
    durable here, retried on its own schedule, and visible in Ops with the same
    retry control the outbox has.

    ``attempts`` / ``next_attempt_at`` implement per-row backoff, so a row whose
    parent is genuinely never coming does not re-run on every cycle forever.
    Nothing is ever deleted by the drain — a row is marked ``applied_at`` or it
    stays for a human. Losing a row silently is the bug this table exists to end.
    """
    __tablename__ = "sync_inbox"

    id              = Column(Integer, primary_key=True, index=True)
    business_id     = Column(Integer, index=True, nullable=False)
    entity          = Column(String, index=True, nullable=False)   # table name
    # The CLOUD's row identity. `uid` is the durable one and is what the drain
    # matches on; `remote_id` is kept for operator legibility only and must never
    # be written to a local FK (that is M-9, money on the wrong invoice).
    uid             = Column(String, index=True, nullable=True)
    remote_id       = Column(Integer, nullable=True)
    payload         = Column(Text, nullable=False)                 # JSON of the cloud row
    reason          = Column(String, nullable=False)               # 'deferred' | 'rejected'
    error           = Column(Text, nullable=True)
    attempts        = Column(Integer, default=0, nullable=False)
    created_at      = Column(DateTime, default=utc_now, nullable=False)
    last_attempt_at = Column(DateTime, nullable=True)
    next_attempt_at = Column(DateTime, index=True, nullable=True)
    applied_at      = Column(DateTime, index=True, nullable=True)

    __table_args__ = (
        # One live entry per (business, entity, uid). A row re-offered by a later
        # pull must UPDATE its inbox entry, not stack a second copy — otherwise a
        # child whose parent is slow to arrive accumulates one row per pull cycle.
        Index("ix_sync_inbox_dedup", "business_id", "entity", "uid"),
        Index("ix_sync_inbox_pending", "business_id", "applied_at", "next_attempt_at"),
    )


class SyncCursor(Base):
    """Durable per-entity pull watermark.

    REPLACES ``sync_worker._PULL_CURSOR``, a module-level dict.

    Two defects came from that dict being in memory:

    * **It did not survive a restart.** The fallback re-derived the cursor from
      ``SyncLog.synced_at`` with an ``.offset(1 if queue_items else 0)``
      heuristic — a proxy for what was applied, not a record of it. When the
      proxy lands LATER than what actually applied, the rows in between are
      skipped permanently. That is M-12 on the read side, reintroduced by any
      process restart.
    * **``_PULL_FAILED_STREAK`` reset too**, so the bounded give-up counter
      restarted on every boot.

    Per-ENTITY rather than one global timestamp so a poison row in
    ``stock_ledger`` cannot hold back ``invoices``. The old design gave 29 tables
    a single shared fate.
    """
    __tablename__ = "sync_cursors"

    id              = Column(Integer, primary_key=True, index=True)
    business_id     = Column(Integer, index=True, nullable=False)
    # "*" is the whole-pull watermark used by the timestamp-based endpoint; a
    # table name is used once an entity has its own high-water mark.
    entity          = Column(String, nullable=False)
    cursor_value    = Column(String, nullable=True)                # ISO ts or id
    failed_streak   = Column(Integer, default=0, nullable=False)
    updated_at      = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("business_id", "entity", name="uq_sync_cursor_biz_entity"),
    )


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
    # NOTE: "businesses" used to be listed here. There is no `businesses` table
    # and no model that maps to one — a business IS a `users` row with
    # `parent_business_id IS NULL`. It was a name that could never match a
    # `__tablename__`, so it gated nothing and queued nothing. Removed rather
    # than left as a decoy for the next person reading this set.
    #
    # ── `users` is DELIBERATELY ABSENT. Do not add it back. ──────────────────
    #
    # It was here, and the cloud never accepted a single row: `users` is not in
    # `MODEL_MAP`, so `push_changes` hit `_MODEL_MAP.get("users") -> None` and
    # skipped every one with "unknown entity on this server". The outbox acked
    # them anyway (the worker counts what it SENT), so nothing errored and
    # nothing accumulated — it was simply a guaranteed-wasted round trip.
    #
    # Measured on the live database 2026-07-31: 31 `users` rows queued, 31
    # acked, 0 applied. Ever.
    #
    # Worse than wasted: a `users` payload is `_serialize_orm_obj` over the whole
    # row — the bcrypt password hash and the full settings JSON — serialised into
    # `sync_queue.payload` and put on the wire to a server that discards it.
    # `routes/sync_staff.py` says why that must not happen:
    #
    #     Staff users carry hashed passwords — the generic sync entity pipeline
    #     intentionally excludes `users` to avoid leaking identity data through
    #     the normal LWW change log.
    #
    # That was the design; this table was contradicting it. Staff replication has
    # its own path (`POST /api/sync/staff-push`) which sends only the fields it
    # needs, and the subscription block comes back via
    # `_sync_subscription_from_cloud`. Nothing else about a `users` row is meant
    # to travel.
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
    # NOTE: "table_alterations" used to be listed here too. It is the local audit
    # log and is no longer replicated at all — see the block comment where it was
    # removed from MODEL_MAP in database/sync_map.py. In practice it never
    # queued anyway: audit rows are written with raw SQL on the connection
    # (see `audit_after_flush`), which bypasses the ORM events `_queue_change`
    # listens on. Listing it here only made the set look like it did something.
    #
    # register_shifts is the PARENT of invoices/invoice_payments (shift_id FK).
    # It was present in the apply-side MODEL_MAP but missing here, so shift rows
    # were never enqueued/pushed — leaving their child invoices perpetually
    # deferred on the cloud ("parent register_shifts … not in this DB yet") and
    # the outbox stuck at "N pending". Enqueue shifts (and their cash movements)
    # so children can resolve their parent and drain.
    "register_shifts",
    "shift_cash_movements",
    # M-2: period locks must travel in BOTH directions. Listing them only in the
    # apply-side MODEL_MAP would enable pull and not push — the same asymmetry
    # that left register_shifts stuck above. A period the owner closed on one
    # device was not closed on the other, so a backdated write still landed
    # there. Append-only and event-sourced, so LWW has nothing to discard: the
    # effective lock is the latest row on either side.
    "period_locks",
}


from sqlalchemy import event, text
from sqlalchemy.orm import Mapper
import json

# Which parent tables actually HAVE a `uid` column, read from live metadata.
# Cached because _serialize_orm_obj runs per row per foreign key on every push
# and pull.
_PARENT_HAS_UID_CACHE: dict = {}


def _parent_has_uid(parent_table_name: str) -> bool:
    """True when `parent_table_name` has a `uid` column to resolve against.

    Not every FK target is a synced, uid-bearing table. `users` in particular has
    `id` and `public_id` but NO `uid`, and both `register_shifts.user_id` and
    `shift_cash_movements.user_id` point at it — so the enrichment below used to
    issue `SELECT uid FROM "users" ...` for those rows on every single sync.
    """
    if parent_table_name not in _PARENT_HAS_UID_CACHE:
        tbl = Base.metadata.tables.get(parent_table_name)
        _PARENT_HAS_UID_CACHE[parent_table_name] = bool(tbl is not None and "uid" in tbl.c)
    return _PARENT_HAS_UID_CACHE[parent_table_name]


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

                # Skip parents with no `uid` column instead of asking for one.
                #
                # THIS IS THE FIX FOR THE INVISIBLE POSTGRES ABORT.
                # `SELECT uid FROM "users"` raises UndefinedColumn on Postgres,
                # which ABORTS THE ENTIRE TRANSACTION — and the handler below was
                # a bare `except Exception: pass`, so nothing was logged and
                # nothing rolled back. Every subsequent statement on that session
                # then failed with InFailedSqlTransaction, which is why
                # sync/pull reported `shift_cash_movements` and `b2b_orders` as
                # "failed querying" when neither was the actual problem: the real
                # error was this swallowed lookup, one table earlier.
                #
                # SQLite tolerated it because it has no aborted-transaction state,
                # so this only ever broke against the cloud.
                if not _parent_has_uid(parent_table_name):
                    continue

                try:
                    # SAVEPOINT: if the lookup fails for any OTHER reason, only
                    # this statement is rolled back. An outer transaction carrying
                    # 20+ other tables must not die for one FK enrichment, which
                    # is best-effort by design.
                    with connection.begin_nested():
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
                except Exception as e:
                    # Reported, not swallowed. Enrichment is optional; silence is
                    # what turned a one-column problem into twenty phantom table
                    # failures.
                    logging.getLogger("bizassist.sync_queue").warning(
                        "_serialize_orm_obj: uid lookup failed for %s.%s -> %s (%s) — "
                        "row is still serialized without the parent uid",
                        obj.__table__.name, parent_col_name, parent_table_name, e,
                    )
    return d

# M-21 — child tables that carry NO business_id column of their own.
#
# `_get_business_id` used to return None for these, and `_queue_change` declines
# on None, so EVERY row of every table below was refused by the outbox. They are
# all listed in `_SYNC_TABLES` and all present in the cloud's apply-side
# MODEL_MAP: the cloud has always been able to receive them, the client has
# never once sent one. Measured on the real database 2026-07-28:
#
#     invoice_line_items   184 rows local   0 EVER queued
#
# That is the same asymmetry as register_shifts (apply-side supported,
# push-side impossible) with a different mechanism, and it is why invoice
# LCL-OW-0030 reached the cloud showing "No items on this invoice" while the
# local copy had two.
#
#     table -> (parent table, FK column on the child)
_BUSINESS_ID_VIA_PARENT = {
    "invoice_line_items": ("invoices", "invoice_id"),
    "purchase_invoice_line_items": ("purchase_invoices", "purchase_invoice_id"),
    "purchase_order_line_items": ("purchase_orders", "purchase_order_id"),
    # NOT stock_transfer_id — the column is `transfer_id`. Guessing the name
    # from the table would have silently resolved to None here, i.e. produced
    # exactly the defect being fixed. Every entry above is verified against
    # __table__.columns by test_child_fk_columns_all_exist.
    "stock_transfer_line_items": ("stock_transfers", "transfer_id"),
}


def _get_business_id(obj, connection=None) -> int | None:
    bid = getattr(obj, "business_id", None)
    if bid is not None:
        try:
            return int(bid)
        except (ValueError, TypeError):
            pass
    if obj.__tablename__ == "users":
        return obj.parent_business_id or obj.id

    # Child row: borrow the owner from its parent. Needs the connection because
    # the parent may have been INSERTed in this very flush and not be readable
    # from any other session yet.
    spec = _BUSINESS_ID_VIA_PARENT.get(obj.__tablename__)
    if spec is not None and connection is not None:
        parent_tbl, fk_col = spec
        fk_val = getattr(obj, fk_col, None)
        if fk_val is None:
            return None
        try:
            row = connection.execute(
                text(f'SELECT business_id FROM "{parent_tbl}" WHERE id = :i'),
                {"i": fk_val}).fetchone()
        except Exception as e:
            # A resolver that fails quietly is how this defect survived in the
            # first place (rule 33).
            _sync_queue_logger().warning(
                "[SYNC_QUEUE] could not resolve business_id for %s#%s via "
                "%s.%s=%s: %s. The row is NOT queued.",
                obj.__tablename__, getattr(obj, "id", "?"), parent_tbl, fk_col,
                fk_val, e)
            return None
        if row is not None and row[0] is not None:
            try:
                return int(row[0])
            except (ValueError, TypeError):
                return None
    return None

def queue_row_if_absent(executor, *, business_id, entity, entity_id,
                        operation, payload, created_at=None):
    """Queue an outbox row, or refresh the pending one that is already there.

    THE ONLY WAY A ROW SHOULD ENTER `sync_queue`. Three call sites reach this
    table by raw SQL — the ORM-event enqueue below, `_heal_unqueued_rows`, and
    the parity sweep's missing-row branch — and before the partial unique index
    existed all three could stack duplicates of the same unsent row. That is how
    one target ended up with seven pending copies in a day.

    Now that `uix_sync_queue_pending_target` exists, a blind INSERT does not
    merely duplicate, it RAISES. On Postgres that aborts the whole transaction
    and every later statement dies with InFailedSqlTransaction (rule 58) — the
    exact failure the parity sweep's `INSERT OR IGNORE` comment describes
    already having been paid for once. So the check lives here, once, rather
    than in each caller's own try/except.

    Written as SELECT-then-UPDATE/INSERT rather than `ON CONFLICT`: the upsert
    form has to infer the partial index, and on a database that has not run the
    migration yet it fails instead of inserting. Callers swallow to protect the
    business write (M-20a), so that would silently drop the row. This form is
    correct with or without the index; the index is only the backstop.

    `attempts` / `next_attempt_at` are deliberately NOT reset on refresh. The
    heal scan re-queues a deferred row every cycle, so resetting would hand it a
    fresh timer each time and cancel the backoff entirely.
    """
    existing = executor.execute(
        text(
            # NULL-safe on business_id: `= NULL` is never true, and some rows
            # do carry a NULL business_id.
            "SELECT id FROM sync_queue WHERE "
            "((business_id IS NULL AND :business_id IS NULL) OR business_id = :business_id) "
            "AND entity = :entity AND entity_id = :entity_id "
            "AND operation = :operation AND synced_at IS NULL LIMIT 1"
        ),
        {"business_id": business_id, "entity": entity,
         "entity_id": entity_id, "operation": operation},
    ).fetchone()

    if existing:
        executor.execute(
            text("UPDATE sync_queue SET payload = :payload WHERE id = :id"),
            {"payload": payload, "id": existing[0]},
        )
        return False

    executor.execute(
        text(
            "INSERT INTO sync_queue (business_id, entity, entity_id, operation, "
            "payload, created_at, attempts) "
            "VALUES (:business_id, :entity, :entity_id, :operation, :payload, "
            ":created_at, 0)"
        ),
        {"business_id": business_id, "entity": entity, "entity_id": entity_id,
         "operation": operation, "payload": payload,
         "created_at": created_at or utc_now()},
    )
    return True


def _sync_queue_logger():
    """Lazily resolved so importing models.py never depends on logging setup."""
    import logging
    return logging.getLogger("bizassist.sync_queue")


def _decline(tbl, target, operation, why, level="debug"):
    """Record WHY a row was not queued for sync, then decline.

    M-20a. Every `return` in `_queue_change` was silent, so "this row is not in
    the outbox" had no explanation anywhere — and on 2026-07-27 that turned into
    a register whose shift never reached the cloud, which in turn stranded every
    sale rung on it. Three shifts were skipped and no line of any log said so.

    Most declines are entirely normal and fire on nearly every write, so they
    are DEBUG. The two that are NOT routine — a business that cannot be resolved,
    and a row with no primary key — are WARNING: those mean a syncable row is
    being dropped for a reason that is probably a bug.
    """
    getattr(_sync_queue_logger(), level)(
        "[SYNC_QUEUE] not queued: %s#%s (%s) - %s",
        tbl, getattr(target, "id", "?"), operation, why)


_NOT_HYBRID_SEEN: set = set()

# Counters for pull-apply suppression noise. Each key is (table, operation);
# the value is the count of rows suppressed in the current pull-apply block.
# Reset at the start of every pull (via sync_disabled_var context) via the
# summary log path: first hit = INFO summary, subsequent hits = silent count.
# This collapses hundreds of DEBUG lines per sync cycle into one INFO per table.
_PULL_APPLY_SUPPRESS_SEEN: dict = {}


def _note_not_hybrid(bid, tbl, mode) -> bool:
    """True the FIRST time this (business, table, mode) declines in this process.

    A local-only business declines on every single write, so logging each one
    would bury the signal it exists to provide (and rule 33's point is that a
    check nobody reads is a check that cannot see). One line per combination
    per process answers "why is nothing syncing" and then stays quiet.

    Keyed on the mode too, so a hybrid -> local flip mid-process is reported
    rather than swallowed by an earlier entry.
    """
    key = (bid, tbl, mode)
    if key in _NOT_HYBRID_SEEN:
        return False
    # Bounded: a runaway key set must never be the thing that ends the process.
    if len(_NOT_HYBRID_SEEN) > 2000:
        _NOT_HYBRID_SEEN.clear()
    _NOT_HYBRID_SEEN.add(key)
    return True


def _queue_change(connection, target, operation):
    from database.db import sync_disabled_var
    tbl = target.__tablename__
    # 1. Skip if sync is disabled (e.g. during pull updates)
    #
    # This is the leading hypothesis for M-20a: a row written INSIDE a pull-apply
    # is suppressed here, correctly (it came FROM the cloud, pushing it back is
    # an echo). If a shift is ever created while this flag is set — a repair, a
    # restore, a migration that reuses the pull path — it is silently never
    # queued and can never reach the cloud. Now it says so.
    if sync_disabled_var.get() == True:
        # Pull-apply context: sync_disabled_var is set — this row came FROM the cloud,
        # so pushing it back would be an echo. It is suppressed here and will NEVER be pushed.
        # Collapse the per-row DEBUG spam into a per-table summary so the logs stay readable.
        # The first time we see (table, operation) in this context we log once
        # at DEBUG; after that we count silently. The summary is cheap: bounded
        # by the number of distinct (table, op) pairs in any pull batch.
        key = (tbl, operation)
        prev = _PULL_APPLY_SUPPRESS_SEEN.get(key, 0)
        _PULL_APPLY_SUPPRESS_SEEN[key] = prev + 1
        if prev == 0:
            # First hit — log once so the category is greppable
            _sync_queue_logger().debug(
                "[SYNC_QUEUE] pull-apply: suppressing %s %s rows from outbox "
                "(expected — rows came from cloud, not pushing back)",
                operation, tbl)
        return
    # 2. Skip tracking tables
    if tbl in ("sync_queue", "sync_logs", "conflict_logs"):
        return
    # 3. Only sync tables in our export/sync set
    if tbl not in _SYNC_TABLES:
        _decline(tbl, target, operation, "table is not in _SYNC_TABLES")
        return

    # 3b. PULL-ONLY tables are mirrored cloud->local and must never be pushed
    # back up. B2B rows are shared between two tenants, so a local push with
    # last-write-wins could discard the counterparty's write. They are already
    # absent from _SYNC_TABLES above; this is the explicit belt-and-braces so a
    # future edit to that set can't silently re-enable the wrong direction.
    try:
        from database.sync_map import PULL_ONLY_TABLES
        if tbl in PULL_ONLY_TABLES:
            _decline(tbl, target, operation, "PULL_ONLY table (cloud is the "
                                             "authority; pushing would clobber "
                                             "the counterparty)")
            return
    except Exception as e:
        _sync_queue_logger().warning(
            "[SYNC_QUEUE] could not check PULL_ONLY_TABLES for %s: %s", tbl, e)

    # 4. Only queue if dialect is sqlite (local client)
    if connection.dialect.name != "sqlite":
        return

    bid = _get_business_id(target, connection)
    if bid is None:
        # WARNING, not debug: this is a SYNCABLE table whose owning business
        # could not be determined, so a real row is being dropped from the
        # outbox for a reason that is probably a bug.
        _decline(tbl, target, operation,
                 "business_id could not be resolved - row is NOT queued",
                 level="warning")
        return

    # Check if hybrid mode is configured for this specific business ID.
    #
    # M-20a — THE CAUSE, FOUND 2026-07-28. This block held FOUR silent `return`s
    # and was the last unexplained exit in the enqueue path. It is why business 7
    # wrote 42 syncable rows between 2026-07-12 16:20 and 2026-07-26 21:59 and
    # queued NONE of them, including the three register_shifts whose absence
    # stranded the invoices rung on them (M-20).
    #
    # Declining is CORRECT for a local-only or cloud-only business — that is the
    # whole point of the setting. Declining SILENTLY is the defect: "hosting_mode
    # is not hybrid" and "sync is broken" produced byte-identical evidence, i.e.
    # none, so the gap could only be found by diffing tables against the outbox
    # a fortnight later. Proven on real data: after business 8 was switched to
    # 'local' it wrote 12 syncable rows, queued 0, and logged 0.
    #
    # The mode itself is not recoverable after the fact — flipping AWAY from
    # hybrid is the one settings write this same gate refuses to queue, so it
    # leaves no trace anywhere. The log line below is the trace.
    try:
        res = connection.execute(
            text("SELECT parent_business_id, settings FROM users WHERE id = :bid"),
            {"bid": bid}
        ).fetchone()

        if not res:
            # A syncable row whose owning user does not exist. Not routine.
            _decline(tbl, target, operation,
                     f"no users row for business_id={bid} - cannot read "
                     f"hosting_mode, so the row is NOT queued", level="warning")
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
            _decline(tbl, target, operation,
                     f"business_id={bid} has no settings at all - hosting_mode "
                     f"is unknown and the row is NOT queued", level="warning")
            return

        s = json.loads(settings_str)
        mode = s.get("general", {}).get("hosting_mode")
        if mode != "hybrid":
            # Routine and correct for a local/cloud business, so this must not
            # spam: one line per (business, table, mode) per process. That is
            # enough to answer "why is nothing syncing" and cheap enough to
            # leave on in production.
            if _note_not_hybrid(bid, tbl, mode):
                _sync_queue_logger().info(
                    "[SYNC_QUEUE] business_id=%s has hosting_mode=%r (not "
                    "'hybrid'), so %s rows are NOT being queued for sync. This "
                    "is correct for a local-only or cloud-only business. If you "
                    "expected this device to sync, change the mode - nothing "
                    "written while it is set will be pushed later on its own.",
                    bid, mode, tbl)
            return
    except Exception as e:
        # users table might not exist yet during initial DB creation/seeds, or
        # query failed. Either way a syncable row just fell out of the outbox,
        # so it does not get to be silent (WAS: bare `return`).
        _sync_queue_logger().warning(
            "[SYNC_QUEUE] could not read hosting_mode for business_id=%s while "
            "queueing %s#%s (%s): %s. The row is NOT queued and will never be "
            "pushed. Expected only during initial DB creation/seeding.",
            bid, tbl, getattr(target, "id", "?"), operation, e)
        return

    # 5. Extract values and queue it
    entity_id = getattr(target, "id", None)
    if entity_id is None:
        pks = target.__table__.primary_key.columns.keys()
        if pks:
            entity_id = getattr(target, pks[0], None)

    if entity_id is None:
        _decline(tbl, target, operation,
                 "no primary key value - row is NOT queued", level="warning")
        return

    payload = None
    if operation != "DELETE":
        try:
            payload = json.dumps(_serialize_orm_obj(target, connection), default=str)
        except Exception as e:
            # WAS `except Exception: pass`. A row queued with payload=NULL is a
            # row the cloud can never apply — the outbox holds a promise it
            # cannot keep, and nothing said so.
            _sync_queue_logger().error(
                "[SYNC_QUEUE] could NOT serialise %s#%s for biz=%s: %s. The row "
                "is being queued WITHOUT a payload and the cloud will not be "
                "able to apply it.", tbl, entity_id, bid, e, exc_info=True)
    else:
        try:
            payload = json.dumps({"id": entity_id, "business_id": bid}, default=str)
        except Exception as e:
            _sync_queue_logger().error(
                "[SYNC_QUEUE] could NOT serialise DELETE of %s#%s for biz=%s: %s",
                tbl, entity_id, bid, e, exc_info=True)

    # Insert into sync_queue using connection
    try:
        # ── Refresh the pending row rather than stacking another copy ─────────
        # Written as SELECT-then-UPDATE/INSERT rather than `ON CONFLICT`: the
        # upsert form has to infer the partial unique index, and if that index
        # is not there yet (a database that has not run the migration) it fails
        # instead of inserting. The except below swallows to protect the sale
        # (M-20a), so the row would be silently dropped — the exact failure this
        # whole file is scarred by. This form needs no index to be correct; the
        # index is only the backstop.
        #
        # `attempts` / `next_attempt_at` are deliberately NOT reset here. The
        # heal scan re-queues a deferred row every cycle, so resetting would
        # hand it a fresh timer each time and cancel the backoff.
        queue_row_if_absent(connection, business_id=bid, entity=tbl,
                            entity_id=entity_id, operation=operation,
                            payload=payload)
    except Exception as e:
        # ── M-20a · the swallow that can lose a whole register's takings ───────
        #
        # This was `except Exception as e: pass  # Fail silently to prevent
        # blocking main database writes`.
        #
        # Failing OPEN is right: a sync bookkeeping problem must never stop the
        # counter taking money. Failing open and SILENT is not, and this is the
        # single INSERT that decides whether a sale ever leaves this device.
        # When it throws, the row is never queued, never pushed, and never
        # missed by anything — the outbox looks perfectly drained.
        #
        # That is exactly the observed M-20a shape: `register_shifts` rows 1-6
        # were queued, 7/8/9 were not, invoices kept queueing throughout, and no
        # log line anywhere recorded a refusal. Every invoice rung on shift 9 is
        # now stuck behind a parent the cloud will never receive.
        #
        # Still swallowed — the write must not be rolled back — but at ERROR
        # with the entity, the id and the reason, so the next occurrence is one
        # grep instead of a four-hour investigation. (rule 13: a swallow is
        # judged by what it protects; this one protects the sale, not the
        # silence.)
        _sync_queue_logger().error(
            "[SYNC_QUEUE] FAILED to queue %s#%s (%s) for biz=%s: %s. This row "
            "will NEVER be pushed to the cloud and nothing else will notice. If "
            "it is a parent row (register_shifts, customers, products), every "
            "child that references it will be deferred by the cloud forever.",
            tbl, entity_id, operation, bid, e, exc_info=True)


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
    """Audit log of database table insertions, updates, and deletions by users.

    IDENTITY: `public_id` (BizID) is the only field here that means the same
    thing in two databases. `user_id` and `business_id` are per-database integers
    — local and cloud number the same business differently by design, and the
    BizID is the shared spine.

    That was not a theoretical concern. This table used to be REPLICATED between
    local and cloud (it was in MODEL_MAP), so cloud-authored rows landed locally
    carrying cloud integers. Measured 2026-07-31 on the live database:

        business_id=42   25 rows   — 42 is Varshini's CLOUD id; locally it is 7
        user_id 9, 42, 46, 86      — resolve against no local user at all

    Those rows are unattributable: `business_id=42` reads as "no such business"
    here, and worse, would read as *the wrong business* the day a local row is
    assigned id 42. Replication is now removed (see the block comment where this
    table was taken out of MODEL_MAP), which stops it getting worse, and
    `public_id` makes what is written from here on attributable regardless of
    which database it was written in.
    """
    __tablename__ = "table_alterations"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, nullable=True)
    username    = Column(String, nullable=True)
    # Per-database integer. Meaningful ONLY in the database that wrote this row.
    business_id = Column(Integer, nullable=True)
    # BizID — stable across every database. Prefer this for attribution.
    public_id   = Column(String, index=True, nullable=True)
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
    # BizID — the ONE identifier that means the same thing in the local and the
    # cloud database. `business_id` above is a per-database integer, so an audit
    # row carrying only that is unattributable the moment it is read anywhere
    # other than where it was written. The middleware already sets this from the
    # token's `public_id` claim; it just was not being recorded.
    try:
        from logging_config import current_bizid_var
        public_id = current_bizid_var.get()
        if public_id in ("-", ""):
            public_id = None
    except Exception:
        public_id = None

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
            "business_id": business_id or getattr(obj, "business_id", None),
            # BizID: stable across databases, unlike the integer above.
            "public_id": public_id
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
                "business_id": business_id or getattr(obj, "business_id", None),
            # BizID: stable across databases, unlike the integer above.
            "public_id": public_id
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
            "business_id": business_id or getattr(obj, "business_id", None),
            # BizID: stable across databases, unlike the integer above.
            "public_id": public_id
        })

def _audit_record_id(obj):
    """Which row this audit entry is about.

    THE DEFECT THIS FIXES
    ---------------------
    This was `str(inspect(obj).identity[0]) if identity else None`. For an
    INSERT, `identity` is populated in `after_flush_postexec` — AFTER this
    listener runs — so it is `None` here and every INSERT in the audit log was
    written with `record_id = NULL`.

    Measured on the live database 2026-07-31: **every one of the 72 `users`
    INSERT rows ever audited had `record_id = NULL`**, i.e. the audit log could
    say that a user was created and never which one.

    That is not a cosmetic gap. Tracing 22 unexplained staff accounts had to be
    done by matching audit `created_at` against `users.created_at` to the
    millisecond, because the log that exists precisely to answer "what happened
    to this row" could not name the row. UPDATE and DELETE were unaffected —
    those objects are already persistent, so `identity` is set — which is why
    the hole survived: the log looked populated and mostly worked.

    The PK attribute IS set on the instance by this point (the INSERT has
    executed); only the identity map has not caught up. `primary_key_from_instance`
    reads the attribute, so it works for all three actions.
    """
    try:
        pk = inspect(obj).mapper.primary_key_from_instance(obj)
        if pk and pk[0] is not None:
            return str(pk[0])
    except Exception:
        pass
    # Fall back to the identity map for anything exotic (composite PKs on a
    # non-standard mapper, objects mid-detach).
    try:
        ident = inspect(obj).identity
        if ident:
            return str(ident[0])
    except Exception:
        pass
    return None


@event.listens_for(Session, "after_flush")
def audit_after_flush(session, flush_context):
    pending = getattr(session, "_pending_audits", None)
    if not pending:
        return
    
    session._pending_audits = []
    
    for item in pending:
        obj = item.pop("obj")
        record_id = _audit_record_id(obj)

        # Insert raw SQL directly on the connection to prevent session flushes recursive loops
        connection = session.connection()
        connection.execute(
            text(
                "INSERT INTO table_alterations (user_id, username, business_id, public_id, table_name, action, record_id, old_values, new_values, created_at, uid) "
                "VALUES (:user_id, :username, :business_id, :public_id, :table_name, :action, :record_id, :old_values, :new_values, :created_at, :uid)"
            ),
            {
                "user_id": item["user_id"],
                "username": item["username"],
                "business_id": item["business_id"],
                "public_id": item.get("public_id"),
                "table_name": item["table_name"],
                "action": item["action"],
                "record_id": record_id,
                "old_values": item["old_values"],
                "new_values": item["new_values"],
                "created_at": utc_now(),
                "uid": str(uuid.uuid4())
            }
        )
