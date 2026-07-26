"""
database/sync_map.py
====================
Single source of truth for the hybrid-sync table→model mapping and the
entity→broadcast-channel mapping.

(R-7) Previously this map was duplicated verbatim in `routes/sync.py` and
`services/sync_worker.py`. A table added to one but not the other silently
stopped syncing in one direction. Both modules now import from here so they
can never drift.
"""
import logging
from typing import Any, Dict

from sqlalchemy import text

from database.models import (
    User, Customer, Vendor, Product, Invoice, InvoiceLineItem,
    Inventory, LegacyPayment, StockLedger, ProductBarcode, BusinessSettings,
    InvoicePayment, B2BLedger, Expense, Godown, StockTransfer,
    StockTransferLineItem, PurchaseInvoice, PurchaseInvoiceLineItem,
    PurchaseOrder, PurchaseOrderLineItem, AlertConfig, RateLimitConfig,
    TableAlteration, RegisterShift, ShiftCashMovement,
)
from core.models import B2BConnection, B2BOrder, B2BOrderLineItem, PeriodLock

# table name -> SQLAlchemy ORM model
MODEL_MAP: Dict[str, Any] = {
    # NOTE: `users` is intentionally NOT synced. Identity is established by
    # registration/login and resolved by BizID/username — copying a user row
    # across databases carries its PK + UNIQUE public_id (BizID), which collides
    # (e.g. local id=122 and cloud id=7 share the unified BizID → UNIQUE failed).
    # Only business *data* syncs; the account/identity does not.
    "customers": Customer,
    "vendors": Vendor,
    "products": Product,
    # register_shifts MUST appear before invoices: an invoice carries a shift_id
    # FK, so the parent shift has to sync first or every invoice defers forever
    # ("parent register_shifts … not in this DB yet"), stalling the whole outbox.
    # (RegisterShift was designed to sync — it was just missing from this map.)
    "register_shifts": RegisterShift,
    # Child of register_shifts (shift_id FK) — synced after its parent shift.
    "shift_cash_movements": ShiftCashMovement,
    "invoices": Invoice,
    "invoice_line_items": InvoiceLineItem,
    "inventory": Inventory,
    "payments": LegacyPayment,
    "stock_ledger": StockLedger,
    "product_barcodes": ProductBarcode,
    "business_settings": BusinessSettings,
    "invoice_payments": InvoicePayment,
    "b2b_ledgers": B2BLedger,
    "expenses": Expense,
    "godowns": Godown,
    "stock_transfers": StockTransfer,
    "stock_transfer_line_items": StockTransferLineItem,
    "purchase_invoices": PurchaseInvoice,
    "purchase_invoice_line_items": PurchaseInvoiceLineItem,
    "purchase_orders": PurchaseOrder,
    "purchase_order_line_items": PurchaseOrderLineItem,
    "alert_configs": AlertConfig,
    "rate_limit_configs": RateLimitConfig,
    "table_alterations": TableAlteration,
    # Period locks ARE ordinary owner-scoped data and must travel (M-2): a
    # period the owner closed on one device was not closed on the other, so a
    # backdated write still landed there. Event-sourced and append-only, so
    # LWW has nothing to lose — the effective lock is the latest row either way.
    #
    # NOTE the deliberate absence of `journal_entries` / `journal_lines`. They
    # are DERIVED, carry a per-database hash chain and a per-database
    # `source_id`, and are re-posted on arrival by core/accounting/repost.py.
    # Adding them here would replicate an invalid chain pointing at wrong
    # document ids. See docs/STRATEGIC_REVIEW_JUL2026.md M-2.
    "period_locks": PeriodLock,
    # ── B2B: PULL-ONLY mirror (see PULL_ONLY_TABLES below) ──────────────────
    # Order matters: connections, then orders, then their line items, so the
    # FK-uid resolution always finds the parent inside the same batch.
    "b2b_connections": B2BConnection,
    "b2b_orders": B2BOrder,
    "b2b_order_line_items": B2BOrderLineItem,
}


# ── Directionality ──────────────────────────────────────────────────────────
# Every other table has ONE owner, so local→cloud push with last-write-wins is
# safe. B2B rows are the exception: a connection or an order is a SHARED record
# between a buyer and a seller who live in different tenants, and usually in
# different databases. If both sides could author locally and push, LWW would
# silently discard one party's write — on the one table where a lost write means
# a lost order.
#
# So the CLOUD is the sole authority for B2B. The frontend pins every B2B call
# to the cloud backend (see frontend-billing/src/b2b/b2bClient.js), and each
# local install keeps a READ-ONLY MIRROR pulled down from it. The mirror exists
# so the counter can still SEE its connections and orders when the internet
# drops — never so it can author them offline.
#
# Consumers:
#   · services/sync_worker.py pull-apply — applies these normally.
#   · database/models.py::_queue_change  — refuses to enqueue them for push.
PULL_ONLY_TABLES: frozenset = frozenset({
    "b2b_connections",
    "b2b_orders",
    "b2b_order_line_items",
})


# B2B tables are scoped by TWO owner columns instead of the usual single
# `business_id`, so tenant-isolation filters have to OR them. Single source of
# truth for the cloud pull endpoint.
TWO_SIDED_OWNER_COLUMNS: dict = {
    "b2b_connections": ("seller_business_id", "buyer_business_id"),
    "b2b_orders": ("seller_business_id", "buyer_business_id"),
}

# Synced entities whose `user_id` FK points at the NON-synced `users` table.
# The source DB's integer user_id won't exist in the destination DB, and the
# column is NOT NULL, so the apply side must re-point it at the resolved owner
# (business_id) rather than let the insert fail its FK. Single source of truth
# for both apply paths (push route + pull worker).
_USER_FK_REPOINT_ENTITIES = frozenset({"register_shifts", "shift_cash_movements"})


logger = logging.getLogger("bizassist.sync_map")


def resolve_parent_fk_uids(db, model_cls, data: dict, log_prefix: str = "sync") -> bool:
    """(Step 3 / R-3) Resolve a synced row's parent foreign keys from the durable
    parent ``uid`` carried in the payload (``<fk>_uid`` / ``<base>_uid``),
    rewriting each FK column to the LOCAL parent id.

    Single source of truth for both apply paths — ``routes/sync.py::push_changes``
    and ``services/sync_worker.py`` pull-apply — so the resolution/deferral logic
    can never drift between them.

    Returns ``True`` if the row must be **deferred**: the parent could not be
    resolved in THIS database. The caller skips it; it re-applies on a later sync
    once the parent lands. Writing the source-DB integer id instead creates a
    wrong-row link. Mutates ``data[fk_col]`` in place on each resolution.

    THE HOLE THIS CLOSES (review finding M-9)
    -----------------------------------------
    The deferral used to sit inside ``if parent_uid_val:`` — so it only fired
    when a uid was PRESENT but unresolvable. When the payload carried **no** uid
    at all, nothing was checked and the caller's ``setattr`` loop wrote the raw
    ``invoice_id`` **from the source database**, which points at whatever
    unrelated row happens to hold that integer locally.

    Found in production data (26 Jul 2026), on money::

        invoice_payments #53  note "Initial payment for invoice LCL-OW-0002"
                              → attached to C1-0002   (a ₹2,533 invoice)
        invoice_payments #45  note "Initial payment for invoice LCL-OW-0006"
                              → attached to OW-0003   (a ₹124 invoice)

    Both landed on the wrong customer's invoice. That is money credited to the
    wrong account: one invoice looked part-paid when it was not, another looked
    overpaid. It also poisoned the M-7 paid-state repair, which read those
    foreign rows as evidence and "corrected" two invoices in the wrong direction.

    THE RULE NOW: a FOREIGN KEY IS ONLY WRITTEN WHEN IT IS PROVEN LOCAL.
    A raw FK value that survives from the payload is verified to exist in this
    database (and, for business-scoped parents, to belong to the same business)
    before it is accepted. An FK that cannot be verified is not "probably fine" —
    it is a silent mis-link, and on a payment row it is misallocated money.

    WHAT HAPPENS TO AN UNVERIFIABLE FK depends on whether the column can be NULL,
    and getting this wrong trades one silent data loss for another:

      NOT NULL (``invoice_payments.invoice_id``, ``*_line_items.<parent>_id``)
          DEFER the row. It cannot be written without the link, and a wrong link
          is misallocated money — this is the M-9 case that actually bit.

      NULLABLE (``invoices.customer_id``, ``stock_ledger.product_id``, …)
          Write the row with the FK set to NULL, and log it. The first version of
          this fix deferred these too, which would have stranded an INVOICE
          whenever its customer could not be resolved — turning a wrong-customer
          link into a MISSING SALE on the destination. That is strictly worse,
          and it is the same "never lose a sale" rule that §9.3b and M-3 turn on.
          An invoice with no customer attached is visibly incomplete and
          recoverable; an invoice that never arrived is neither.
    """
    table_name = getattr(model_cls, "__tablename__", str(model_cls))

    for fk in model_cls.__table__.foreign_keys:
        fk_col = fk.parent.name
        parent_table = fk.column.table.name
        parent_pk = fk.column.name

        parent_uid_val = None
        for suffix in [f"{fk_col}_uid", f"{fk_col[:-3]}_uid" if fk_col.endswith("_id") else ""]:
            if suffix and suffix in data:
                parent_uid_val = data[suffix]
                break

        if parent_uid_val:
            try:
                row = db.execute(
                    text(f'SELECT "{parent_pk}" FROM "{parent_table}" WHERE uid = :uid'),
                    {"uid": parent_uid_val},
                ).fetchone()
                if row:
                    data[fk_col] = row[0]
                    continue
                logger.info(
                    "%s: deferring %s — parent %s uid=%s not in this DB yet",
                    log_prefix, table_name, parent_table, parent_uid_val,
                )
                return True
            except Exception as e:
                logger.warning(
                    "%s: failed to resolve FK %s via uid %s: %s",
                    log_prefix, fk_col, parent_uid_val, e,
                )
                return True          # unproven → defer, never write a guess

        # ── No uid supplied (M-9). The raw value is a SOURCE-database id and
        #    means nothing here unless it happens to be valid locally. Verify
        #    before trusting it; `users` is exempt because it is deliberately
        #    not synced and its ids are re-pointed by the caller.
        raw = data.get(fk_col)
        if raw in (None, ""):
            continue
        if parent_table == "users":
            continue

        try:
            parent_cols = {c.name for c in fk.column.table.columns}
            q = f'SELECT "{parent_pk}" FROM "{parent_table}" WHERE "{parent_pk}" = :v'
            params = {"v": raw}
            # Same-tenant check where the parent carries an owner column — an id
            # that exists but belongs to ANOTHER business is the worst case: a
            # valid-looking link across tenants.
            if "business_id" in parent_cols and data.get("business_id") is not None:
                q += " AND business_id = :b"
                params["b"] = data["business_id"]
            if db.execute(text(q), params).fetchone() is None:
                if fk.parent.nullable:
                    # Drop the link, keep the row. See the docstring: stranding a
                    # whole invoice because its customer is unresolvable loses a
                    # sale, which is worse than an invoice with no customer.
                    logger.warning(
                        "%s: %s.%s=%s carries NO parent uid and does not resolve "
                        "to a local %s row — writing the row with %s = NULL rather "
                        "than attaching it to an unrelated record (M-9). The link "
                        "can be restored; a dropped row cannot.",
                        log_prefix, table_name, fk_col, raw, parent_table, fk_col,
                    )
                    data[fk_col] = None
                    continue
                logger.warning(
                    "%s: deferring %s — %s=%s carries NO parent uid and does not "
                    "resolve to a local %s row for this business. The column is "
                    "NOT NULL so the row cannot be written without a link, and a "
                    "wrong link is misallocated money (M-9).",
                    log_prefix, table_name, fk_col, raw, parent_table,
                )
                return True
        except Exception as e:
            logger.warning(
                "%s: could not verify FK %s=%s against %s (%s) — deferring rather "
                "than writing an unverified link",
                log_prefix, fk_col, raw, parent_table, e,
            )
            return True

    return False


# table name -> SSE channel name used to nudge the browser to refetch
ENTITY_BROADCAST_MAP: Dict[str, str] = {
    "customers": "party",
    "vendors": "party",
    "products": "product",
    "invoices": "invoice",
    "payments": "payment",
    "invoice_payments": "payment",
    "purchase_invoices": "purchase",
    "godowns": "godown",
    "purchase_orders": "order",
    "stock_transfers": "stock",
    "stock_ledger": "stock",
    "business_settings": "settings",
    "b2b_connections": "connection",
    "b2b_orders": "order",
    "b2b_order_line_items": "order",
}
