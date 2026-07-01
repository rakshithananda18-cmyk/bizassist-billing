"""
core/models.py — the billing ecosystem's OWN tables.
====================================================
These tables belong to `core/` (the billing ecosystem), kept in their own file
so the schema is organised by domain — separate from the AI/legacy tables in
`database/models.py`.

ONE DATABASE, ONE METADATA. They register on the SAME shared `Base` as every
other table (imported from `database.db`), because the product is a modular
monolith, not microservices: a sale writes `Invoice` + `InvoiceLineItem`
(shared) AND `StockLedger` (core) in ONE atomic transaction with foreign keys
between them, and the AI advisor reads the shared `Invoice`/`Product` tables.
Splitting into separate databases would break those FKs and that atomicity — so
we split the *files*, never the database.

Dependency arrow: core/models → database (shared Base + mixins). The shared
layer never imports core, so there is no cycle. `database/models.py` imports
these at the bottom purely so the tables register on `Base.metadata` whenever
the shared models are loaded (and for backward-compatible imports).

Tables here:
  StockLedger       append-only stock truth   (Phase 1, D4)
  ProductBarcode    one product → many codes   (Phase 1)
  BusinessSettings  per-vertical template config (Phase 1B)
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, DateTime,
    Boolean, Text, ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database.db import Base, TimestampMixin, BusinessOwnedMixin


# ---------------------------------------------------------------------------
# BILLING FOUNDATION — Stock Ledger  (Phase 1, decision D4)
# ---------------------------------------------------------------------------

class StockLedger(Base, TimestampMixin):
    """
    APPEND-ONLY record of every stock movement. The TRUTH for inventory.

    `inventory.stock` is a cached projection; the real quantity of a product is
    the SUM of `qty_delta` across this ledger for that (business_id, product).
    Nothing here is ever updated or deleted — a correction is a NEW row (e.g. a
    negative `adjustment`). This makes stock fully explainable ("why is it 3?")
    and rebuildable, and is the foundation the purchase/sales/order modules all
    write through. See FOUNDATION.md → "Append-only ledgers".

    Movement types (`movement_type`):
      purchase        +  goods received from a supplier
      sale            -  goods sold on an invoice
      return_in       +  customer returned goods
      return_out      -  goods returned to a supplier
      damage          -  write-off / breakage / expiry
      adjustment      ±  manual correction (signed)
      order_reserved  -  held for an open order (soft-allocated)
      order_released  +  reservation released (order cancelled/fulfilled)
      opening         +  opening balance at switch-in import

    `reference_type`/`reference_id` link the movement back to what caused it
    (e.g. ("invoice", 42) or ("purchase_invoice", 7) or ("import", null)) so the
    paper trail is complete.
    """
    __tablename__ = "stock_ledger"

    id             = Column(Integer, primary_key=True, index=True)
    uid            = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
    business_id    = Column(Integer, index=True, nullable=False)

    # Product identity: keep BOTH a FK (app-created products) and a name snapshot
    # (CSV/legacy rows where product_id may be null) so a movement is never orphaned.
    product_id     = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    product_name   = Column(String,  nullable=True, index=True)

    movement_type  = Column(String,  nullable=False, index=True)   # see docstring
    qty_delta      = Column(Float,   nullable=False)               # signed: + adds, - removes
    balance_after  = Column(Float,   nullable=True)                # running balance snapshot (audit aid)

    reference_type = Column(String,  nullable=True)                # 'invoice'|'purchase_invoice'|'order'|'import'|'manual'
    reference_id   = Column(Integer, nullable=True)
    note           = Column(Text,    nullable=True)
    device_id      = Column(String,  nullable=True)                # which device created it (sync/audit)
    godown_id      = Column(Integer, nullable=True, index=True)
    batch_no       = Column(String,  nullable=True, index=True)
    expiry_date    = Column(String,  nullable=True)

    created_at     = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_stock_ledger_biz_product", "business_id", "product_id"),
        Index("ix_stock_ledger_biz_name",    "business_id", "product_name"),
    )


# ---------------------------------------------------------------------------
# BILLING FOUNDATION — Product Barcodes  (one product → MANY barcodes)
# ---------------------------------------------------------------------------

class ProductBarcode(Base, TimestampMixin):
    """
    A product accumulates MANY barcodes over its life — manufacturers revise
    packaging, new cartons carry new EAN/UPC codes, and old stock still scans
    the old code. So a single `Product.barcode` column is wrong; one product
    maps to many codes. `Product.barcode` is kept only as the *primary/display*
    code (a cache); the real scan→product lookup goes through this table.

    Rules:
      • A scanned code must resolve to exactly ONE product within a business →
        UNIQUE (business_id, barcode).
      • Codes are not deleted when retired — set `active=False` so old stock
        still resolves and the history is kept (append-friendly).
      • Exactly one `is_primary=True` per product (the one printed on labels).
    """
    __tablename__ = "product_barcodes"
    __table_args__ = (
        UniqueConstraint("business_id", "barcode", name="uq_product_barcode_biz_code"),
        Index("ix_product_barcode_biz_code", "business_id", "barcode"),
        Index("ix_product_barcode_product",  "business_id", "product_id"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    uid         = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
    business_id = Column(Integer, index=True, nullable=False)
    product_id  = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    barcode     = Column(String,  nullable=False, index=True)
    is_primary  = Column(Boolean, default=False)         # the label/display code
    active      = Column(Boolean, default=True)          # retire without deleting
    label       = Column(String,  nullable=True)         # e.g. "old pack", "2025 carton"
    source      = Column(String,  nullable=True)         # 'manual'|'scan'|'purchase'|'import'

    created_at  = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# BUSINESS TEMPLATE SYSTEM — per-vertical customization  (Phase 1B)
# ---------------------------------------------------------------------------

class BusinessSettings(Base, TimestampMixin):
    """
    One row per business: which vertical TEMPLATE it runs (`template_key`) and the
    owner's per-setting `overrides` (JSON). The app's effective config =
    template defaults ⊕ overrides, computed by core.templates.resolve_for().

    Templates change PRESENTATION + DEFAULTS only (labels, which fields a product
    form shows, tax-inclusive default, entry mode, print layout, enabled
    workflows) — never the money math or tenant scoping. Vertical-specific
    product fields live in `Product.attributes` (JSON), so a new vertical needs
    NO schema change — only a new JSON template file.

    `overrides` is stored as JSON-in-Text (SQLite-friendly, like the rest of the
    schema); serialise/parse at the edge.
    """
    __tablename__ = "business_settings"
    __table_args__ = (
        UniqueConstraint("business_id", name="uq_business_settings_biz"),
    )

    id           = Column(Integer, primary_key=True, index=True)
    uid          = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
    business_id  = Column(Integer, index=True, nullable=False)
    template_key = Column(String,  nullable=False, default="general")  # the chosen vertical
    overrides    = Column(Text,    nullable=True)                       # JSON: owner's per-setting tweaks

    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------------------------------------------------------------------
# INVOICE PAYMENT  (structured payment records — Phase 1B)
# ---------------------------------------------------------------------------

class InvoicePayment(Base, TimestampMixin):
    """
    Append-only payment receipt against an Invoice.

    NEVER delete or overwrite — a reversal is a new row with a negative amount
    (but typical flows: partial, then full, each as a new positive row).

    Idempotent on `idempotency_key` (business_id + idempotency_key UNIQUE).
    The caller should pass a client-generated UUID; on retry the existing row
    is returned without double-posting.
    """
    __tablename__ = "invoice_payments"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "idempotency_key",
            name="uq_invoice_payments_biz_idem"
        ),
        Index("ix_invoice_payments_invoice", "business_id", "invoice_id"),
        Index("ix_invoice_payments_customer", "business_id", "customer_id"),
    )

    id              = Column(Integer, primary_key=True, index=True)
    uid             = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
    business_id     = Column(Integer, index=True, nullable=False)

    invoice_id      = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    customer_id     = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)

    amount_paid     = Column(Float,  nullable=False)
    payment_mode    = Column(String, nullable=True)   # Cash|UPI|Card|Cheque|NEFT…
    payment_date    = Column(String, nullable=True)   # YYYY-MM-DD
    note            = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True, index=True)

    created_at      = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# OFFLINE-FIRST SYNC — HTTP-level exactly-once replay guard  (R7b, Slice 1)
# ---------------------------------------------------------------------------

class IdempotencyKey(Base):
    """
    HTTP-level exactly-once replay guard for offline-first sync (R7b).

    The client generates a stable UUID per user-intent mutation and sends it in
    the `X-Client-Request-Id` header. The FIRST request to arrive does the work
    and stores its response here; any retry (flaky network, offline outbox
    replay on reconnect) finds the stored row and gets back the SAME response —
    never a double-post and never a confusing "duplicate" error. Tenant-scoped:
    UNIQUE(business_id, client_request_id).

    This is the OUTER wall. The per-command idempotency that already exists
    (sale `invoice_no`, payment `idempotency_key`, `post_entry` source-key, the
    B2B order-sync guard) remains the INNER wall — so even two *concurrent*
    identical requests that both miss this table still cannot double-post. The
    two walls compose: the inner one guarantees correctness, the outer one
    guarantees the client always gets a consistent reply on replay.

    Append-only: a row is written once after the mutation commits and never
    mutated. `response_json` is JSON-in-Text (SQLite-friendly, like the rest of
    the schema); the stored body is replayed verbatim.
    """
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "client_request_id",
            name="uq_idempotency_biz_key",
        ),
        Index("ix_idempotency_biz_key", "business_id", "client_request_id"),
    )

    id                = Column(Integer, primary_key=True, index=True)
    business_id       = Column(Integer, index=True, nullable=False)
    client_request_id = Column(String,  nullable=False, index=True)

    method            = Column(String,  nullable=True)   # audit: which HTTP verb
    path              = Column(String,  nullable=True)   # audit: which route
    status_code       = Column(Integer, nullable=False, default=200)
    response_json     = Column(Text,    nullable=False)  # stored body (JSON-in-Text)

    created_at        = Column(DateTime, default=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# B2B ECOSYSTEM — Connections and Ordering (Phase 3)
# ---------------------------------------------------------------------------

class B2BConnection(Base, TimestampMixin):
    """
    Consented connection between two businesses.
    A connection represents a private communication pipe.
    """
    __tablename__ = "b2b_connections"
    __table_args__ = (
        UniqueConstraint(
            "seller_business_id", "buyer_business_id",
            name="uq_b2b_connections_seller_buyer"
        ),
        Index("ix_b2b_connections_seller", "seller_business_id"),
        Index("ix_b2b_connections_buyer", "buyer_business_id"),
    )

    id                  = Column(Integer, primary_key=True, index=True)
    seller_business_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    buyer_business_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    price_tier          = Column(String, nullable=False, default="standard")  # standard|wholesale|distributor
    discount_pct        = Column(Float, nullable=False, default=0.0)          # direct percentage discount (e.g. 5.0)
    credit_limit        = Column(Float, nullable=False, default=0.0)
    outstanding_balance = Column(Float, nullable=False, default=0.0)
    stock_visibility    = Column(String, nullable=False, default="exact")     # exact|band|hidden
    catalog_category    = Column(String, nullable=True)                       # category filter (none=all)
    status              = Column(String, nullable=False, default="accepted")    # accepted|revoked

    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class B2BInviteCode(Base, TimestampMixin):
    """
    Single-use, expiring code generated by a seller to link a buyer.
    """
    __tablename__ = "b2b_invite_codes"
    __table_args__ = (
        Index("ix_b2b_invite_codes_seller_code", "seller_business_id", "code"),
    )

    id                 = Column(Integer, primary_key=True, index=True)
    seller_business_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    code               = Column(String, unique=True, index=True, nullable=False)
    is_used            = Column(Boolean, nullable=False, default=False)
    expires_at         = Column(DateTime, nullable=False)
    created_at         = Column(DateTime, default=datetime.utcnow)


class B2BOrder(Base, TimestampMixin):
    """
    B2B order placed by a buyer to a connected seller.
    """
    __tablename__ = "b2b_orders"
    __table_args__ = (
        Index("ix_b2b_orders_buyer", "buyer_business_id"),
        Index("ix_b2b_orders_seller", "seller_business_id"),
    )

    id                 = Column(Integer, primary_key=True, index=True)
    buyer_business_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    seller_business_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    order_number       = Column(String, unique=True, index=True, nullable=False)
    order_date         = Column(String, nullable=False)  # YYYY-MM-DD
    status             = Column(String, nullable=False, default="pending")  # pending|accepted|packed|dispatched|completed|cancelled
    
    subtotal           = Column(Float, nullable=False, default=0.0)
    cgst_total         = Column(Float, nullable=False, default=0.0)
    sgst_total         = Column(Float, nullable=False, default=0.0)
    igst_total         = Column(Float, nullable=False, default=0.0)
    total_amount       = Column(Float, nullable=False, default=0.0)
    notes              = Column(Text, nullable=True)
    # Phase 4 sync: the seller sale invoice this order posted to (NULL until the
    # order is completed). Its presence is the exactly-once guard for the sync.
    seller_invoice_id  = Column(Integer, nullable=True)

    created_at         = Column(DateTime, default=datetime.utcnow)
    updated_at         = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    line_items = relationship(
        "B2BOrderLineItem", back_populates="order",
        cascade="all, delete-orphan", lazy="selectin"
    )


class B2BOrderLineItem(Base, TimestampMixin):
    """
    Line items for a B2B order.
    """
    __tablename__ = "b2b_order_line_items"
    __table_args__ = (
        Index("ix_b2b_order_line_items_order", "order_id"),
    )

    id            = Column(Integer, primary_key=True, index=True)
    order_id      = Column(Integer, ForeignKey("b2b_orders.id"), nullable=False)
    product_id    = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    product_name  = Column(String, nullable=False)
    hsn_sac       = Column(String, nullable=True)
    unit          = Column(String, nullable=False, default="Nos")
    quantity      = Column(Float, nullable=False, default=1.0)
    unit_price    = Column(Float, nullable=False, default=0.0)
    cgst_rate     = Column(Float, nullable=False, default=0.0)
    sgst_rate     = Column(Float, nullable=False, default=0.0)
    igst_rate     = Column(Float, nullable=False, default=0.0)
    line_total    = Column(Float, nullable=False, default=0.0)
    created_at    = Column(DateTime, default=datetime.utcnow)

    order = relationship("B2BOrder", back_populates="line_items")


class B2BLedger(Base, TimestampMixin):
    """
    Append-only ledger of shared transactions between seller and buyer.
    Tracks credit, payments, and invoices.
    """
    __tablename__ = "b2b_ledgers"
    __table_args__ = (
        Index("ix_b2b_ledgers_seller_buyer", "seller_business_id", "buyer_business_id"),
    )

    id                 = Column(Integer, primary_key=True, index=True)
    uid                = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
    seller_business_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    buyer_business_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    transaction_type   = Column(String, nullable=False)  # order|invoice|payment|credit_note
    reference_id       = Column(Integer, nullable=True)
    amount             = Column(Float, nullable=False)   # + for sales/debts, - for payments/credits
    balance_snapshot   = Column(Float, nullable=False, default=0.0)
    created_at         = Column(DateTime, default=datetime.utcnow)


class Expense(Base, BusinessOwnedMixin):
    """
    Direct and indirect business expenses (e.g., rent, utilities, salaries).
    """
    __tablename__ = "expenses"

    expense_date = Column(String, nullable=False)   # YYYY-MM-DD
    category     = Column(String, nullable=False)   # Rent|Utilities|Salaries|Marketing|Others
    expense_type = Column(String, nullable=False)   # Direct|Indirect
    amount       = Column(Float, nullable=False)
    payment_mode = Column(String, nullable=False)   # Cash|UPI|Bank
    note         = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_expenses_business_category", "business_id", "category"),
        Index("ix_expenses_business_date", "business_id", "expense_date"),
    )


class Godown(Base, BusinessOwnedMixin):
    """
    Godown / Warehouse location for storing inventory.
    """
    __tablename__ = "godowns"

    name      = Column(String, nullable=False)
    address   = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index("ix_godowns_business", "business_id"),
    )


class StockTransfer(Base, BusinessOwnedMixin):
    """
    Bulk transfer of items between godowns.
    """
    __tablename__ = "stock_transfers"

    transfer_date  = Column(String, nullable=False)  # YYYY-MM-DD
    from_godown_id = Column(Integer, nullable=False)
    to_godown_id   = Column(Integer, nullable=False)
    notes          = Column(Text, nullable=True)

    line_items = relationship(
        "StockTransferLineItem", back_populates="transfer",
        cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_stock_transfers_business", "business_id"),
    )


class StockTransferLineItem(Base, TimestampMixin):
    """
    Line items for a stock transfer.
    """
    __tablename__ = "stock_transfer_line_items"

    id            = Column(Integer, primary_key=True, index=True)
    uid           = Column(String(36), nullable=True, default=lambda: str(uuid.uuid4()))
    transfer_id   = Column(Integer, ForeignKey("stock_transfers.id"), nullable=False)
    product_id    = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    product_name  = Column(String, nullable=False)
    quantity      = Column(Float, nullable=False)
    unit          = Column(String, nullable=True, default="Nos")

    transfer = relationship("StockTransfer", back_populates="line_items")


# ---------------------------------------------------------------------------
# ACCOUNTING — Posted double-entry journal (Phase: accounting depth)
# ---------------------------------------------------------------------------

class JournalEntry(Base, BusinessOwnedMixin):
    """
    APPEND-ONLY double-entry journal header, POSTED at transaction time (not
    reconstructed on read). One entry per source document (sale, credit note,
    purchase, debit note, expense, payment); its `lines` always foot
    (Σ debit == Σ credit), enforced by the posting service.

    Idempotency: at most one entry per (business_id, source_type, source_id) —
    re-running a command never double-posts. This is the true audit trail: a
    permanent Dr/Cr record of every money movement, never updated or deleted
    (a correction is a new reversing entry).
    """
    __tablename__ = "journal_entries"

    entry_date  = Column(String,  nullable=False, index=True)  # YYYY-MM-DD
    source_type = Column(String,  nullable=False, index=True)   # sale|credit_note|purchase|debit_note|expense|payment
    source_id   = Column(Integer, nullable=True,  index=True)   # id of the source document
    ref_no      = Column(String,  nullable=True)
    narration   = Column(Text,    nullable=True)

    # Tamper-evident hash chain (R3): entry_hash = SHA256(canonical(entry+lines)
    # + prev_hash), where prev_hash is the previous entry's entry_hash for this
    # business ("GENESIS" for the first). Any edit/delete/reorder of a posted
    # entry breaks the chain from that point on — verifiable via verify_chain().
    prev_hash   = Column(String,  nullable=True)
    entry_hash  = Column(String,  nullable=True, index=True)

    lines = relationship(
        "JournalLine", back_populates="entry",
        cascade="all, delete-orphan", lazy="selectin",
    )

    __table_args__ = (
        Index("ix_journal_entries_source", "business_id", "source_type", "source_id"),
        Index("ix_journal_entries_biz_date", "business_id", "entry_date"),
    )


class JournalLine(Base, TimestampMixin):
    """One Dr/Cr posting line of a JournalEntry. Append-only."""
    __tablename__ = "journal_lines"

    id        = Column(Integer, primary_key=True, index=True)
    entry_id  = Column(Integer, ForeignKey("journal_entries.id"), nullable=False, index=True)
    account   = Column(String,  nullable=False, index=True)
    debit     = Column(Float,   nullable=False, default=0.0)
    credit    = Column(Float,   nullable=False, default=0.0)

    entry = relationship("JournalEntry", back_populates="lines")


class PeriodLock(Base, BusinessOwnedMixin):
    """
    APPEND-ONLY period close/lock log (one row per lock OR unlock *event*).

    Locking "closes the books" through an inclusive date: once a business locks
    through YYYY-MM-DD, no journal entry (sale, payment, purchase, expense, …)
    may be POSTED with `entry_date <= locked_through`. Corrections to a locked
    period must be made as a NEW reversing entry dated in the still-open period —
    the books are never edited in place.

    State is event-sourced (never updated/deleted): the *effective* lock is the
    most recent row by (created_at, id). If that row `is_active`, the boundary is
    its `locked_through`; an `is_active=False` row is an unlock event that lifts
    the boundary. This keeps a full, tamper-evident lock/unlock history.
    """
    __tablename__ = "period_locks"

    locked_through = Column(String,  nullable=True)               # inclusive YYYY-MM-DD (NULL on unlock events)
    is_active      = Column(Boolean, nullable=False, default=True)  # True=lock event, False=unlock event
    note           = Column(String,  nullable=True)

    __table_args__ = (
        Index("ix_period_locks_biz", "business_id", "id"),
    )



